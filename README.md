# FinEnclave

**Station locale d'investigation financière et détection d'infractions sur graphes (100 % étanche / Air-Gap)**  
*Développé pour l'ASUS Ascent GX10 AI Developer Challenge (Superchip NVIDIA Grace Blackwell GB10)*

[![Tests](https://img.shields.io/badge/pytest-60%2F60%20passed-brightgreen.svg)](tests/)
[![Hardware](https://img.shields.io/badge/Hardware-ASUS%20Ascent%20GX10%20(GB10)-blue.svg)](https://www.asus.com)
[![Memory](https://img.shields.io/badge/Unified%20Memory-128%20GB%20LPDDR5x-purple.svg)]()
[![Air-Gapped](https://img.shields.io/badge/Environment-100%25%20Air--Gapped-success.svg)]()
[![Live Demo](https://img.shields.io/badge/Live%20Demo-finenclave.adrien--skr.dev-orange.svg)](https://finenclave.adrien-skr.dev)
[![Teaser](https://img.shields.io/badge/Teaser-YouTube%20(45s)-red.svg)](https://youtu.be/opBa7EITtOo)

---

## 1. Le Verrou Légal : L'Interdiction Pénale du Cloud

Lors d'une saisie judiciaire ou d'un audit de conformité bancaire, les enquêteurs manipulent des liasses hétérogènes : statuts de sociétés offshore, relevés de comptes bancaires multi-pages, pactes d'actionnaires, procurations et registres étrangers.

L'usage d'API cloud (OpenAI, Anthropic, Google) est rigoureusement proscrit :
* **Secret bancaire pénal** (Art. L. 511-33 du Code monétaire et financier) : violation passible de peines correctionnelles et d'amendes lourdes.
* **Secret de l'instruction** (Art. 11 du Code de procédure pénale).
* **Risque de nullité de procédure** (Art. 170 du CPP) : l'envoi de pièces judiciaires vers des serveurs soumis à l'extraterritorialité américaine (FISA 702, US CLOUD Act) compromet la validité probatoire de toute l'instruction.

**FinEnclave résout cette impasse par une appliance physique autonome posée sur un bureau, opérant en vase clos complet (*air-gapped*), sans câble réseau.**

```mermaid
flowchart LR
    A["Pièces judiciaires saisies<br/>(Scans PDF, actes, relevés)"] --> B["ASUS Ascent GX10 Local<br/>Qwen2.5-VL-72B FP8 + PaddleOCR-VL"]
    B --> C["Graphe Financier Déterministe<br/>(Cycles de Tarjan, Smurfing, UBOs)"]
    C --> D["Livrables de Procédure<br/>(Rapport d'instruction & Workbench HTML)"]
```

---

## 2. L'Adéquation Matérielle : Pourquoi le GX10 est Indispensable

Une carte graphique grand public (RTX 5070/5080 plafonnée à 16 Go de VRAM) ne peut charger qu'un modèle compact de 7 à 8 milliards de paramètres. Nos mesures démontrent qu'un modèle 7B échoue sur la lecture des relevés bancaires multi-colonnes et manque les schémas de dissimulation.

Le superchip **NVIDIA Grace Blackwell GB10** et ses **128 Go de mémoire unifiée LPDDR5x** (240 W TDP) débloquent l'orchestration conjointe en local :
* **T1 — Modèle de vision principal (72 milliards de paramètres) :** `Qwen2.5-VL-72B-Instruct-FP8-dynamic` alloué à 65 % de la mémoire unifiée (~83 Go).
* **T2 — Lecteur tabulaire spécialisé :** `PaddleOCR-VL-1.6` alloué à 8 % (~10 Go) pour l'extraction sans perte des écritures comptables denses.
* **Système Grace CPU Arm64 & Moteur de Graphes :** ~35 Go de mémoire vive réservés pour le noyau Linux, le serveur vLLM et le calcul topologique sous NetworkX.

---

## 3. Résultats Mesurés sur Station Physique ASUS Ascent GX10 (`gx10-aedd`)

Toutes les métriques ci-dessous proviennent de l'évaluation physique sur la machine de test ASUS officielle, enregistrées en continu par télémétrie matérielle Linux (`/proc/meminfo` et compteurs NVIDIA Blackwell) :

### A. Banc 1 : Exactitude Criminelle (50 pièces étalon ICIJ)
Évaluation d'exactitude comparée sur le dossier étalon de 50 pièces :

| Métrique de Banc | 1. CPU sans LLM<br>*(Règles regex + OCR)* | 2. Modèle 7B Local<br>*(Équivalent RTX 16 Go)* | 3. **GX10 : 72B-FP8**<br>*(Profil nominal)* | 4. **GX10 : 72B-AWQ**<br>*(Profil quantifié 4-bit)* |
| :--- | :---: | :---: | :---: | :---: |
| **Environnement** | Local | Local vLLM | **Local vLLM (GB10)** | **Local vLLM (GB10)** |
| **Mémoire allouée (VRAM)** | — | ~10 Go | **90,8 Go** (73 % unifié) | **54,9 Go** (44 % unifié) |
| **Puissance GPU moyenne** | — | 32,2 W | **43,4 W** | 11,8 W *(veille)* |
| **Latence par pièce** | < 1 s | 31,04 s | **25,95 s** (2,3 p/min) | Timeout vLLM (> 1 200 s) |
| **Précision / Rappel Entités** | 100 % / 89 % | 100 % / 0 % *(échec d'extraction)* | **100 % / 100 %** *(exhaustif)* | Échec compilation CUDA |
| **Précision / Rappel Gouvernance** | 100 % / 88 % | 100 % / 0 % *(échec d'extraction)* | **100 % / 100 %** *(exhaustif)* | Échec compilation CUDA |
| **Précision / Rappel Virements** | 89 % / 74 % | 100 % / 0 % *(échec d'extraction)* | **100 % / 100 %** *(exhaustif)* | Échec compilation CUDA |
| **Circuit de blanchiment (CYCLE)** | ❌ Échec | ❌ Échec | **✅ Détecté (100 %)** | ❌ Échec |
| **Fractionnement (SMURFING)** | ❌ Échec | ❌ Échec | **✅ Détecté (6 relais)** | ❌ Échec |
| **Bénéficiaire effectif occulte (UBO)** | ⚠️ Partiel | ❌ Échec | **✅ Identifié (Chaîne complète)** | ❌ Échec |

> **Doctrine d'enquête & Asymétrie du risque probatoire (Faux Positifs vs Faux Négatifs) :**  
> * **Faux Positif (FP) — Coût de contrôle acceptable :** Si le système signale une anomalie sur une pièce qui s'avère régulière, l'enquêteur ouvre la pièce justificative en un clic via sa cote et lève le doute manuellement en 30 secondes. Préférer vérifier quelques pièces à la main est le standard normal en criminalistique.
> * **Faux Négatif (FN) — Risque pénal critique :** Si le système classe une pièce comme anodyne, **personne ne l'ouvrira jamais** parmi les milliers de pièces saisies. L'infraction financière et le compte offshore disparaissent dans l'angle mort de l'instruction.
> * **L'impasse du modèle 7B (carte 16 Go) :** Le modèle 7B affiche une précision apparente de 100 % mais un **rappel de 0 %**, soit **100 % de Faux Négatifs** sur les relevés bancaires : le circuit de 2 002 500 $ échappe totalement à l'enquête.
> * **La garantie du 72B FP8 sur GX10 :** Grâce aux 128 Go unifiés, le grand modèle de vision atteint **100 % de Rappel (0 Faux Négatif)** : l'enquêteur a l'assurance formelle que les pièces non inspectées sont véritablement exemptes d'infraction.

> **Enseignement technique fondamental (FP8 vs AWQ 4-bit sur Grace Blackwell) :**  
> * **Le format FP8 dynamic (`RedHatAI`) est le standard de référence :** Il compile sans encombre sur l'architecture GB10 Arm64 et garantit 100 % de fidélité sans aucune hallucination.
> * **L'impasse du 4-bit AWQ :** Les kernels AWQ 4-bit subissent des instabilités de compilation CUDA sous vLLM sur GB10 (timeout > 20 min). Disposer des 128 Go unifiés du GX10 évite précisément le piège du 4-bit dégradé en permettant l'inférence FP8 native.

> **Fichiers de mesures brutes :**  
> * Run 72B-FP8 : [`runs/bench_72b-fp8_pieces.json`](runs/bench_72b-fp8_pieces.json)  
> * Run 7B : [`runs/bench_7b_pieces.json`](runs/bench_7b_pieces.json)  
> * Run 72B-AWQ : [`runs/bench_72b-awq_pieces.json`](runs/bench_72b-awq_pieces.json)

---

### B. Banc 2 : Tenue Sous Charge Continue (500 pièces / 10 affaires)
Épreuve d'endurance industrielle sur 10 affaires judiciaires indépendantes de 50 pièces chacune :

| Indicateur de Tenue en Charge | Mesure Physique Réelle (Profil 72B-FP8 Nominal) | Analyse Technique |
| :--- | :---: | :--- |
| **Volume de pièces traitées** | **500 pièces judiciaires** | 10 affaires d'instruction indépendantes enchaînées |
| **Durée totale d'inférence continue** | **16 495,64 secondes (~4h 35min)** | Charge ininterrompue jour et nuit |
| **Échantillons de télémétrie enregistrés** | **15 589 mesures matérielles** | Traçabilité physique complète sous Linux |
| **Pic de mémoire physique engagée** | **95,2 Go alloués (76 % unifié)** | Marge de sécurité de ~29 Go pour l'OS et le CPU |
| **Puissance électrique GPU mesurée** | **40,4 W en moyenne (pic à 96,1 W)** | Très en dessous du TDP maximal de 240 W |
| **Température puce GPU** | **69,3 °C en moyenne (pic à 86,0 °C)** | Refroidissement optimal, aucun thermal throttling |
| **Incidents mémoire (OOM Killer)** | **0 incident (`dmesg` vierge)** | Stabilité totale du noyau Linux et de la pile vLLM |

> **Trace brute du banc de charge :** [`runs/bench_72b-fp8_batch.json`](runs/bench_72b-fp8_batch.json)

---

## 4. Architecture Anti-Hallucination : Séparation Stricte VLM et Moteur Criminel

Pour garantir la recevabilité pénale des conclusions, FinEnclave refuse la génération libre de texte sur les faits criminels :
1. **Extraction optique contrainte :** Les modèles de vision sous vLLM n'extraient que des structures tabulaires validées par des schémas Pydantic stricts.
2. **Moteur mathématique déterministe (C++/Python NetworkX) :**
   * *Cycles de blanchiment :* Algorithme de Tarjan (composantes fortement connexes) et circuits orientés de Johnson.
   * *Fractionnement (Smurfing) :* Détection de faisceaux de micro-virements sous le seuil réglementaire de 10 000 USD vers un compte pivot.
   * *Bénéficiaires effectifs :* Centralité de Brandes et calcul des chaînes de détention indirecte par multiplication matricielle.
3. **Traçabilité documentaire des pièces :** Chaque nœud du graphe et chaque qualification pénale renvoie à la cote de la pièce justificative source.

---

## 5. Livrables Générés à Chaque Exécution

L'exécution génère automatiquement le dossier d'enquête complet dans `data/outputs/investigation/` :
* **`rapport.md` :** Rapport judiciaire d'instruction avec cotes de procédure et qualifications pénales étayées.
* **`graphe.html` :** Visualiseur topologique interactif autonome (aucun CDN distant, fonctionne hors réseau).
* **`noeuds.csv` & `aretes.csv` :** Données tabulaires normalisées pour analystes financiers.
* **`import.cypher` :** Script d'ingestion directe dans une base orientée graphe Neo4j.
* **`graphe.graphml` :** Export standard pour outils d'analyse criminelle (Gephi, yEd, i2 Analyst's Notebook).

---

## 6. Démonstration Rapide (Rejeu Hors-Ligne)

FinEnclave intègre un jeu d'extractions de référence permettant de rejouer l'ensemble du pipeline et des algorithmes en 3 secondes sans GPU :

```bash
# 1. Cloner le dépôt
git clone https://github.com/AdrienSkr/fin-enclave.git
cd fin-enclave

# 2. Synchroniser les dépendances (Python 3.12+)
uv sync --extra dev

# 3. Lancer l'analyse du dossier étalon (Banc 1)
uv run python main.py

# 4. Lancer la suite de tests unitaires (60/60 tests)
uv run pytest
```

---

## 7. Déploiement sur Station ASUS Ascent GX10

Le déploiement complet sur machine physique GX10 s'opère via les scripts du dossier `deploy/` :

```bash
# 1. Démarrage des conteneurs vLLM GPU (Air-gapped)
./deploy/vllm_service.sh ensemble

# 2. Configuration du backend local
export LLM_BACKEND=local_gx10

# 3. Exécution du banc étalon (50 pièces)
uv run python scripts/bench_gx10.py --profile 72b-fp8 --engine routed --dossier data/demo/pieces

# 4. Exécution du banc de charge (500 pièces / 10 affaires)
uv run python scripts/bench_gx10.py --profile 72b-fp8 --engine routed --dossier-batch data/demo/charge_500
```
