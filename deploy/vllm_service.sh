#!/usr/bin/env bash
# ==============================================================================
# FINENCLAVE : ORCHESTRATION vLLM MULTI-INSTANCE (ASUS ASCENT GX10 / GB10)
# ==============================================================================
# Profils :
#   ensemble         — T1 72B FP8 :8000, T2 PaddleOCR-VL :8001
#   ensemble-awq     — T1 72B AWQ (repli), T2 identique
#   pixtral-124b-awq — T1 Pixtral-Large 124B AWQ :8000, T2 identique :8001 (exploratoire)
#   mono             — T1 seul sur :8000
#   stop             — Arrêt des instances vLLM (Docker ou processus hôte)
#
# Usage : ./deploy/vllm_service.sh [ensemble|ensemble-awq|pixtral-124b-awq|mono|stop]
#
# Budget mémoire (somme --gpu-memory-utilization, vérifiée au démarrage) :
#   MEMORY_BUDGET_CAP=0.90 — marge OS + KV hors réservations vLLM (~119 GiB utiles).

set -euo pipefail

MEMORY_BUDGET_CAP="0.90"
ENSEMBLE_GPU_UTILS="0.65 0.08"
ENSEMBLE_AWQ_GPU_UTILS="0.50 0.08"
PIXTRAL_124B_AWQ_GPU_UTILS="0.65 0.08"
MONO_GPU_UTILS="0.78"

PROFILE="${1:-ensemble}"
VLLM_IMAGE="${VLLM_IMAGE:-vllm/vllm-openai:latest}"
HEALTH_RETRIES="${HEALTH_RETRIES:-400}"  # 400 * 3s = 1200s (20 minutes par défaut pour compilation CUDA 72B)
HEALTH_SLEEP_S="${HEALTH_SLEEP_S:-3}"

# T1 actes / gouvernance, T2 relevés bancaires
MODEL_T1_FP8="${T1_MODEL:-RedHatAI/Qwen2.5-VL-72B-Instruct-FP8-dynamic}"
MODEL_T1_AWQ="${T1_MODEL:-Qwen/Qwen2.5-VL-72B-Instruct-AWQ}"
MODEL_T1_PIXTRAL="${T1_MODEL:-mistralai/Pixtral-Large-Instruct-2411}"
MODEL_T2="PaddlePaddle/PaddleOCR-VL-1.6"

MAX_NUM_SEQS="${MAX_NUM_SEQS:-16}"
MAX_MODEL_LEN_VLM="${MAX_MODEL_LEN_VLM:-8192}"
MAX_MODEL_LEN_OCR="${MAX_MODEL_LEN_OCR:-4096}"
LIMIT_MM='{"image": 1}'

verify_gpu_budget() {
    local -a utils=("$@")
    local sum="0"
    local u
    for u in "${utils[@]}"; do
        sum=$(awk -v a="$sum" -v b="$u" 'BEGIN { printf "%.4f", a + b }')
    done
    awk -v s="$sum" -v cap="$MEMORY_BUDGET_CAP" 'BEGIN {
        if (s > cap + 0.0001) {
            printf "ERREUR: somme gpu-memory-utilization=%.4f > cap=%s\n", s, cap > "/dev/stderr"
            exit 1
        }
    }'
    echo "  Budget GPU vérifié : somme=${sum} (cap ${MEMORY_BUDGET_CAP})"
}

wait_for_health() {
    local port="$1"
    local label="$2"
    local container_name="${3:-}"
    if curl -s -m 2 "http://127.0.0.1:${port}/v1/models" >/dev/null 2>&1; then
        echo "  Santé ${label} (127.0.0.1:${port}) — OK"
        return 0
    fi
    local timeout_s=$((HEALTH_RETRIES * HEALTH_SLEEP_S))
    local timeout_min=$((timeout_s / 60))
    echo -n "  Attente santé ${label} (127.0.0.1:${port}, timeout ~${timeout_min} min)"
    local i
    for ((i = 1; i <= HEALTH_RETRIES; i++)); do
        if curl -s -m 2 "http://127.0.0.1:${port}/v1/models" >/dev/null 2>&1; then
            echo " — OK"
            return 0
        fi
        if [ -n "$container_name" ] && command -v docker >/dev/null 2>&1; then
            local status
            status=$(docker inspect -f '{{.State.Status}}' "$container_name" 2>/dev/null || echo "")
            if [ "$status" = "exited" ] || [ "$status" = "dead" ]; then
                echo -e "\n[ERREUR] Le conteneur ${container_name} s'est arrêté (voir: docker logs ${container_name})"
                return 1
            fi
        fi
        echo -n "."
        sleep "$HEALTH_SLEEP_S"
    done
    echo ""
    echo "[ATTENTION] ${label} pas prêt après ${timeout_s} s (${timeout_min} min) (voir logs)."
    return 1
}

launch_vllm_instance() {
    local name="$1"
    local model="$2"
    local port="$3"
    local gpu_util="$4"
    local max_len="$5"
    local extra_mm="${6:-}"
    local kv_cache="${7:-auto}"
    local extra_args="${8:-}"

    local -a extra_flags=()
    if [ -n "$extra_args" ]; then
        read -r -a extra_flags <<< "$extra_args"
    fi

    if command -v docker >/dev/null 2>&1; then
        local is_running
        is_running=$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null || echo "false")
        local cmd_json
        cmd_json=$(docker inspect -f '{{json .Config.Cmd}}' "$name" 2>/dev/null || echo "")

        if [ "$is_running" = "true" ] && [ "${FORCE_RESTART:-0}" != "1" ]; then
            if [[ "$cmd_json" == *"$model"* ]]; then
                if curl -s -m 2 "http://127.0.0.1:${port}/v1/models" >/dev/null 2>&1; then
                    echo "  [OK] Le conteneur ${name} est déjà actif et prêt (port ${port})."
                else
                    echo "  Le conteneur ${name} est déjà en cours d'exécution avec ${model} (démarrage/chauffe en cours)..."
                fi
                return 0
            else
                echo "  Remplacement de ${name} (modèle en cours différent de ${model})..."
                docker rm -f "$name" >/dev/null 2>&1 || true
            fi
        else
            if docker ps -a --format '{{.Names}}' | grep -q "^${name}$"; then
                docker rm -f "$name" >/dev/null 2>&1 || true
            fi
        fi

        local -a mm_flag=()
        if [ -n "$extra_mm" ]; then
            mm_flag=(--limit-mm-per-prompt "$extra_mm")
        fi
        docker run -d \
            --name "$name" \
            --gpus all \
            --ipc=host \
            --network=host \
            -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
            -e "HF_HUB_ENABLE_HF_TRANSFER=1" \
            -e "HF_XET_HIGH_PERFORMANCE=1" \
            "$VLLM_IMAGE" \
            --host 127.0.0.1 \
            --model "$model" \
            --port "$port" \
            --trust-remote-code \
            --gpu-memory-utilization "$gpu_util" \
            --max-model-len "$max_len" \
            --kv-cache-dtype "$kv_cache" \
            --tensor-parallel-size 1 \
            --max-num-seqs "$MAX_NUM_SEQS" \
            --enable-prefix-caching \
            --enable-chunked-prefill \
            "${mm_flag[@]}" \
            "${extra_flags[@]}"
    else
        if curl -s -m 2 "http://127.0.0.1:${port}/v1/models" >/dev/null 2>&1; then
            echo "  [OK] Service local ${name} déjà actif sur le port ${port}."
            return 0
        fi
        echo "Docker absent — instance native ${name} (port ${port}) en arrière-plan."
        local -a mm_flag=()
        if [ -n "$extra_mm" ]; then
            mm_flag=(--limit-mm-per-prompt "$extra_mm")
        fi
        uv run python -m vllm.entrypoints.openai.api_server \
            --host 127.0.0.1 \
            --model "$model" \
            --port "$port" \
            --trust-remote-code \
            --gpu-memory-utilization "$gpu_util" \
            --max-model-len "$max_len" \
            --kv-cache-dtype "$kv_cache" \
            --tensor-parallel-size 1 \
            --max-num-seqs "$MAX_NUM_SEQS" \
            --enable-prefix-caching \
            --enable-chunked-prefill \
            "${mm_flag[@]}" \
            "${extra_flags[@]}" &
    fi
}

start_ensemble() {
    local t1_model="$1"
    local extra_args="$2"
    shift 2
    local -a utils=("$@")
    echo "=== Profil ensemble : T1=${t1_model}, T2=${MODEL_T2} ==="
    verify_gpu_budget "${utils[@]}"

    launch_vllm_instance "finenclave-vllm-t1" "$t1_model" 8000 "${utils[0]}" \
        "$MAX_MODEL_LEN_VLM" "$LIMIT_MM" "fp8" "$extra_args"
    wait_for_health 8000 "T1-VLM" "finenclave-vllm-t1"

    launch_vllm_instance "finenclave-vllm-t2" "$MODEL_T2" 8001 "${utils[1]}" \
        "$MAX_MODEL_LEN_OCR" "$LIMIT_MM" "auto" "--no-enable-prefix-caching"
    wait_for_health 8001 "T2-OCR" "finenclave-vllm-t2"
}

start_mono() {
    local -a utils=($MONO_GPU_UTILS)
    echo "=== Profil mono : ${MODEL_T1_FP8} seul sur :8000 ==="
    verify_gpu_budget "${utils[@]}"
    launch_vllm_instance "finenclave-vllm-gx10" "$MODEL_T1_FP8" 8000 "${utils[0]}" \
        "$MAX_MODEL_LEN_VLM" "$LIMIT_MM" "fp8"
    wait_for_health 8000 "T1-mono" "finenclave-vllm-gx10"
}

stop_services() {
    echo "=== Arrêt des instances FinEnclave vLLM ==="
    if command -v docker >/dev/null 2>&1; then
        for name in finenclave-vllm-t1 finenclave-vllm-t2 finenclave-vllm-gx10; do
            if docker ps -a --format '{{.Names}}' | grep -q "^${name}$"; then
                echo "  Arrêt du conteneur ${name}..."
                docker rm -f "$name" >/dev/null 2>&1 || true
            fi
        done
    fi
    pkill -f "vllm.entrypoints.openai.api_server" 2>/dev/null || true
    echo "[OK] Instances vLLM arrêtées."
    exit 0
}

case "$PROFILE" in
    stop)
        stop_services
        ;;
    ensemble)
        read -r -a _utils <<< "$ENSEMBLE_GPU_UTILS"
        start_ensemble "$MODEL_T1_FP8" "" "${_utils[@]}"
        ;;
    ensemble-awq)
        read -r -a _utils <<< "$ENSEMBLE_AWQ_GPU_UTILS"
        start_ensemble "$MODEL_T1_AWQ" "--quantization awq" "${_utils[@]}"
        ;;
    pixtral-124b-awq)
        read -r -a _utils <<< "$PIXTRAL_124B_AWQ_GPU_UTILS"
        start_ensemble "$MODEL_T1_PIXTRAL" "--quantization awq" "${_utils[@]}"
        ;;
    mono)
        start_mono
        ;;
    *)
        echo "Profil inconnu : $PROFILE (attendu: ensemble, ensemble-awq, pixtral-124b-awq, mono, stop)" >&2
        exit 1
        ;;
esac

echo "[OK] Profil vLLM « ${PROFILE} » lancé (localhost uniquement, air-gap)."
