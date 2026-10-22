#!/usr/bin/env bash
# ==============================================================================
# FINENCLAVE : BOOTSTRAP & DÉPLOIEMENT MACHINE (ASUS ASCENT GX10)
# ==============================================================================
# Installe uv, configure l'environnement virtuel Python 3.12, installe les paquets
# système requis (Tesseract OCR, Poppler) et prépare les répertoires de runs.

set -euo pipefail

BOLD="\033[1m"
GREEN="\033[0;32m"
RESET="\033[0m"

echo -e "${BOLD}1. Initialisation de uv...${RESET}"
if ! command -v uv >/dev/null 2>&1; then
    echo "Installation de uv via le script officiel Astral..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi
echo -e "${GREEN}uv est opérationnel : $(uv --version)${RESET}"

echo -e "\n${BOLD}2. Dépendances système Linux (Tesseract & Poppler)...${RESET}"
if command -v apt-get >/dev/null 2>&1; then
    echo "Mise à niveau et installation des bibliothèques OCR..."
    if [ "$(id -u)" -eq 0 ]; then
        apt-get update -qq
        apt-get install -y -qq tesseract-ocr tesseract-ocr-fra poppler-utils libgl1
    elif command -v sudo >/dev/null 2>&1; then
        sudo apt-get update -qq
        sudo apt-get install -y -qq tesseract-ocr tesseract-ocr-fra poppler-utils libgl1
    else
        echo "Avis : Pas de privilèges sudo. Assurez-vous que tesseract-ocr et poppler-utils sont présents."
    fi
fi

echo -e "\n${BOLD}3. Synchronisation de l'environnement Python FinEnclave...${RESET}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

uv python install 3.12
uv sync --extra dev

echo -e "\n${BOLD}4. Préparation des dossiers d'artéfacts et de cache...${RESET}"
mkdir -p data/cache/extractions runs data/outputs

echo -e "\n${BOLD}5. Validation de la suite de tests unitaires...${RESET}"
uv run pytest

echo -e "\n${GREEN}${BOLD}==============================================================================${RESET}"
echo -e "${GREEN}${BOLD}    DÉPLOIEMENT FINENCLAVE RÉUSSI SUR ASUS ASCENT GX10                        ${RESET}"
echo -e "${GREEN}${BOLD}==============================================================================${RESET}"
