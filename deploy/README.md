# Déploiement local sur ASUS Ascent GX10

Ce dossier contient l'outillage de déploiement et d'orchestration pour exécuter FinEnclave en environnement étanche (*air-gapped*) sur la station **ASUS Ascent GX10** (NVIDIA Grace Blackwell GB10, architecture `aarch64`, 128 Go de mémoire unifiée LPDDR5x).

---

## 1. Architecture mémoire et orchestration vLLM

FinEnclave exploite les 128 Go de mémoire unifiée pour faire tourner deux instances locales de vLLM en parallèle sans saturer la machine :

| Service | Modèle | Port | VRAM allouée | Rôle |
| :--- | :--- | :---: | :---: | :--- |
| **T1 : Vision & Actes** | `RedHatAI/Qwen2.5-VL-72B-Instruct-FP8-dynamic` | `:8000` | ~65 % (~83 Go) | Lecture des pièces juridiques (statuts, pactes d'actionnaires, procurations) |
| **T2 : Relevés bancaires** | `PaddlePaddle/PaddleOCR-VL-1.6` | `:8001` | ~8 % (~10 Go) | Extraction tabulaire des relevés de comptes |
| **T3 : Qualification** | *Moteur déterministe Python* | — | 0 % | Analyse topologique des flux et qualification pénale sans LLM |

Le script `vllm_service.sh` plafonne automatiquement l'allocation globale à **73 % de la mémoire unifiée** (`ensemble`), ce qui laisse ~35 Go libres pour le système d'exploitation, le CPU Arm et le graphe NetworkX en mémoire vive.

---

## 2. Déploiement pas-à-pas

### Étape 1 : Vérification de l'environnement (Preflight)

```bash
chmod +x deploy/*.sh
./deploy/preflight.sh
./deploy/setup_gx10.sh
```

Le script vérifie la présence du GPU GB10, la mémoire disponible et initialise l'environnement virtuel Python via `uv`.

### Étape 2 : Démarrage des serveurs d'inférence

```bash
# Lancement des deux serveurs vLLM (profil nominal 72B FP8 + PaddleOCR-VL)
./deploy/vllm_service.sh ensemble

# Configuration du backend local
export LLM_BACKEND=local_gx10
```

Pour vérifier que les services répondent :
```bash
curl http://127.0.0.1:8000/v1/models
curl http://127.0.0.1:8001/v1/models
```

*(En cas de contrainte mémoire plus forte, le profil `./deploy/vllm_service.sh ensemble-awq` bascule sur la version quantifiée 4-bit du 72B).*

---

## 3. Exécution des bancs de mesure

### Banc 1 : Dossier étalon (50 pièces)
Mesure de l'exactitude d'extraction et de la détection des infractions sur un dossier financier de référence :
```bash
uv run python scripts/bench_gx10.py --profile 72b-fp8 --engine routed --dossier data/demo/pieces
```

### Banc 2 : Test de charge (500 pièces / 10 affaires)
Évaluation du débit continu et de la stabilité thermique sur 10 affaires indépendantes :
```bash
uv run python scripts/bench_gx10.py --profile 72b-fp8 --engine routed --dossier-batch data/demo/charge_500
```

### Arrêt des services
```bash
./deploy/vllm_service.sh stop
```
