#!/usr/bin/env bash
# ==============================================================================
# FINENCLAVE : EXÉCUTION DE LA MATRICE COMPLÈTE DE NUIT (ASUS ASCENT GX10)
# ==============================================================================
# Programme :
# 1. Profil 72B-FP8 nominal : Banc 1 (50 pièces) + Banc 2 (500 pièces / 10 affaires)
# 2. Profil 72B-AWQ quantifié : Banc 1 (50 pièces) + Banc 2 (500 pièces / 10 affaires)
# 3. Profil 7B (taille RTX) : Banc 1 (50 pièces avec T2 routé)
# 4. Comparateur multi-tiers : main.py (synthèse 4 colonnes & livrables)
# 5. Commits et push Git automatiques à chaque étape
#
# Durée totale estimée : ~6h15 à 6h30
# Usage : nohup ./scripts/run_overnight_matrix.sh > nuit_matrice.log 2>&1 &
# ==============================================================================

set -u

echo "=================================================================="
echo "FINENCLAVE : DÉMARRAGE DE LA MATRICE OFFICIELLE COMPLÈTE"
echo "Date de début : $(date)"
echo "Machine : $(hostname) (NVIDIA Grace Blackwell GB10)"
echo "=================================================================="

export LLM_BACKEND=local_gx10

# ------------------------------------------------------------------
# BLOC 1 : PROFIL NOMINAL 72B-FP8 (Banc 1 + Banc 2) ~3h25
# ------------------------------------------------------------------
echo ""
echo ">>> [1/4] Démarrage vLLM : 72B-FP8 nominal + PaddleOCR-VL (ensemble)..."
./deploy/vllm_service.sh stop
./deploy/vllm_service.sh ensemble

echo ">>> [1/4 - A] Banc 1 : 50 pièces étalon (72B-FP8 routed)..."
uv run python scripts/bench_gx10.py --profile 72b-fp8 --engine routed --dossier data/demo/pieces

echo ">>> [1/4 - B] Banc 2 : 500 pièces / 10 affaires (72B-FP8 routed)..."
uv run python scripts/bench_gx10.py --profile 72b-fp8 --engine routed --dossier-batch data/demo/charge_500

echo ">>> Sauvegarde intermédiaire 72B-FP8..."
git add runs/
git add -A data/demo/
git commit -m "feat(bench): matrice 72B-FP8 terminee (50 & 500 pieces)" || true
git push origin main || true

# ------------------------------------------------------------------
# BLOC 2 : PROFIL QUANTIFIÉ 72B-AWQ (Banc 1 + Banc 2) ~2h45
# ------------------------------------------------------------------
echo ""
echo ">>> [2/4] Démarrage vLLM : 72B-AWQ quantifié + PaddleOCR-VL (ensemble-awq)..."
./deploy/vllm_service.sh stop
./deploy/vllm_service.sh ensemble-awq

echo ">>> [2/4 - A] Banc 1 : 50 pièces étalon (72B-AWQ routed)..."
uv run python scripts/bench_gx10.py --profile 72b-awq --engine routed --dossier data/demo/pieces

echo ">>> [2/4 - B] Banc 2 : 500 pièces / 10 affaires (72B-AWQ routed)..."
uv run python scripts/bench_gx10.py --profile 72b-awq --engine routed --dossier-batch data/demo/charge_500

echo ">>> Sauvegarde intermédiaire 72B-AWQ..."
git add runs/
git add -A data/demo/
git commit -m "feat(bench): matrice 72B-AWQ terminee (50 & 500 pieces)" || true
git push origin main || true

# ------------------------------------------------------------------
# BLOC 3 : PROFIL 7B / RTX AVEC T2 (Banc 1) ~8 min
# ------------------------------------------------------------------
echo ""
echo ">>> [3/4] Démarrage vLLM : 7B + PaddleOCR-VL (ensemble)..."
./deploy/vllm_service.sh stop
T1_MODEL=Qwen/Qwen2.5-VL-7B-Instruct ./deploy/vllm_service.sh ensemble

echo ">>> [3/4 - A] Banc 1 : 50 pièces étalon (7B routed avec T2)..."
uv run python scripts/bench_gx10.py --profile 7b --engine routed --dossier data/demo/pieces

# ------------------------------------------------------------------
# BLOC 4 : COMPARATEUR MULTI-TIERS (4 colonnes) & LIVRABLES FINAUX
# ------------------------------------------------------------------
echo ""
echo ">>> [4/4] Exécution du comparateur et génération des livrables (main.py)..."
uv run python main.py || true

# ------------------------------------------------------------------
# CLÔTURE & PUSH FINAL
# ------------------------------------------------------------------
echo ""
echo ">>> Arrêt propre des services vLLM..."
./deploy/vllm_service.sh stop

echo ">>> Push final des résultats complets vers GitHub..."
git add runs/
git add -A data/demo/
git add -A data/outputs/
git commit -m "feat(bench): MATRICE OFFICIELLE COMPLETE ASUS GX10 (72B-FP8, 72B-AWQ, 7B, 50 & 500 pieces)" || true
git push origin main || true

echo "=================================================================="
echo "MATRICE COMPLÈTE TERMINÉE AVEC SUCCÈS : $(date)"
echo "=================================================================="
