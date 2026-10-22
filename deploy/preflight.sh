#!/usr/bin/env bash
# ==============================================================================
# FINENCLAVE : PREFLIGHT CHECKLIST (ASUS ASCENT GX10 / NVIDIA GB10)
# ==============================================================================
# Script de vérification non-destructif exécuté dès la première minute SSH.
# Vérifie : architecture aarch64, espace disque, internet/HuggingFace, GPU, Docker, uv.

set -uo pipefail

BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
RESET="\033[0m"

echo -e "${BOLD}==============================================================================${RESET}"
echo -e "${BOLD}    FINENCLAVE — PREFLIGHT MATÉRIEL & ENVIRONNEMENT (ASUS ASCENT GX10)       ${RESET}"
echo -e "${BOLD}==============================================================================${RESET}\n"

ERRORS=0
WARNINGS=0

pass() { echo -e "  [${GREEN}OK${RESET}] $1"; }
warn() { echo -e "  [${YELLOW}ATTENTION${RESET}] $1"; ((WARNINGS++)); }
fail() { echo -e "  [${RED}ERREUR${RESET}] $1"; ((ERRORS++)); }

# 1. Architecture CPU
echo -e "${BOLD}1. Architecture CPU & Système${RESET}"
ARCH=$(uname -m 2>/dev/null || echo "unknown")
OS=$(uname -s 2>/dev/null || echo "unknown")
echo "  Système détecté : $OS ($ARCH)"
if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
    pass "Architecture Arm64 (aarch64) conforme au CPU Arm Neoverse V2 du GX10."
else
    warn "Architecture '$ARCH' non-Arm64. Mode émulation ou poste de test x86_64."
fi

# 2. Espace Disque Disponible
echo -e "\n${BOLD}2. Espace Disque Disponible${RESET}"
DISK_AVAIL_GB=$(df -BG . 2>/dev/null | awk 'NR==2 {gsub(/G/,"",$4); print $4}' || echo "0")
echo "  Espace libre sur la partition courante : ${DISK_AVAIL_GB} Go"
if [ "$DISK_AVAIL_GB" -ge 300 ]; then
    pass "Espace suffisant pour les checkpoints quantifiés (>= 300 Go libres)."
elif [ "$DISK_AVAIL_GB" -ge 100 ]; then
    warn "Espace disque limité (${DISK_AVAIL_GB} Go). Téléchargement de multiples modèles MoE restreint."
else
    fail "Espace disque critique (${DISK_AVAIL_GB} Go < 100 Go). Risque d'interruption du run."
fi

# 3. Accès Réseau & Hugging Face Hub
echo -e "\n${BOLD}3. Connectivité Réseau & Téléchargement Modèles${RESET}"
if curl -s -m 3 -I "https://huggingface.co" >/dev/null 2>&1; then
    pass "Accès sortant HTTPS à Hugging Face opérationnel (téléchargement direct des poids possible)."
else
    warn "Hugging Face inaccessible ou réseau restreint (mode air-gap strict actif). Prévoir injection locale des poids."
fi

# 4. Superchip NVIDIA Grace Blackwell GB10
echo -e "\n${BOLD}4. Détection GPU & Pilote NVIDIA${RESET}"
if command -v nvidia-smi >/dev/null 2>&1; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1 || echo "Inconnu")
    DRIVER_VER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n 1 || echo "Inconnu")
    CUDA_VER=$(nvidia-smi 2>/dev/null | grep -o "CUDA Version: [0-9.]*" | head -n 1 || echo "Inconnu")
    pass "NVIDIA SMI détecté : $GPU_NAME (Pilote: $DRIVER_VER, $CUDA_VER)."
else
    fail "nvidia-smi non trouvé. Pilote NVIDIA absent ou GPU non accessible."
fi

# 5. Runtime Docker & Conteneurisation
echo -e "\n${BOLD}5. Runtime Conteneur (Docker & NVIDIA Container Toolkit)${RESET}"
if command -v docker >/dev/null 2>&1; then
    pass "Docker est installé."
    if docker info 2>/dev/null | grep -i -E "nvidia|cdi" >/dev/null 2>&1 || command -v nvidia-ctk >/dev/null 2>&1; then
        pass "NVIDIA Container Toolkit configuré pour vLLM / TensorRT-LLM."
    else
        warn "NVIDIA Container Toolkit non vérifié explicitement via docker info."
    fi
else
    warn "Docker non trouvé dans le PATH. vLLM devra être exécuté dans l'environnement Python hôte."
fi

# 6. Budget mémoire vLLM (profils deploy/vllm_service.sh)
echo -e "\n${BOLD}6. Budget Mémoire Unifiée — Profils vLLM${RESET}"
echo "  Cap somme gpu-memory-utilization : 0,90 (marge OS + KV, ~119 GiB utiles GB10)"
echo "  | Profil        | T1 :8000 | T2 :8001 | T3 :8002 | Somme |"
echo "  | ensemble FP8  | 0,58     | 0,05     | 0,12     | 0,75  |"
echo "  | ensemble AWQ  | 0,42     | 0,05     | 0,12     | 0,59  |"
echo "  | mono T1       | 0,78     | —        | —        | 0,78  |"
pass "Tableau budget mémoire documenté (voir deploy/README.md)."

# 7. Gestionnaire uv & Python
echo -e "\n${BOLD}7. Gestionnaire d'Environnement (uv)${RESET}"
if command -v uv >/dev/null 2>&1; then
    UV_VER=$(uv --version 2>/dev/null || echo "")
    pass "uv installé ($UV_VER)."
else
    warn "uv absent. Le script setup_gx10.sh l'installera automatiquement."
fi

echo -e "\n${BOLD}==============================================================================${RESET}"
if [ "$ERRORS" -eq 0 ]; then
    echo -e "${GREEN}${BOLD}RÉSULTAT PREFLIGHT : PRÊT POUR LA SESSION GX10 (${WARNINGS} avertissements)${RESET}"
    exit 0
else
    echo -e "${RED}${BOLD}RÉSULTAT PREFLIGHT : $ERRORS ERREURS BLOQUANTES DÉTECTÉES${RESET}"
    exit 1
fi
