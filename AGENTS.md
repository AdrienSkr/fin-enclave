# 🤖 AGENTS.md — Manuel Opérationnel & Mémoire Active FinEnclave

Ce document est la **mémoire active et le manuel de vol obligatoire** pour tout agent d'ingénierie logicielle ou d'investigation opérant au sein du dossier `fin-enclave/`. Il définit l'identité du projet, ses contraintes absolues, ses commandes de référence et ses règles d'or.

---

## 🎯 1. Identité & Mission du Projet

* **Nom :** FinEnclave-Local (Station Locale d'Investigation Financière sur Graphes)
* **Cadre :** ASUS Ascent GX10 – Local AI Developer Challenge (ASUS France & Defend Intelligence).
* **Objectif :** Fournir aux magistrats financiers (PNF), analystes TRACFIN et auditeurs forensic une station d'investigation déterministe et sémantique capable de détecter les circuits de blanchiment d'argent et les dissimulations d'UBO (*Ultimate Beneficial Owner*) en environnement **100 % étanche (air-gapped)**.
* **Cible Matérielle :** Station de bureau ASUS Ascent GX10 équipée du superchip **NVIDIA Grace Blackwell GB10** (CPU Arm Neoverse V2 20 cœurs + GPU Blackwell, 128 Go de mémoire unifiée LPDDR5x à 273 Go/s, bus NVLink-C2C à 900 Go/s, TDP 240W silencieux).

---

## 🏗️ 2. Stack Technique & Environnement d'Exécution

* **Langage :** Python 3.11+ (développé et testé sur Python 3.11 à 3.13)
* **Gestionnaire d'environnement & paquets :** [`uv`](https://github.com/astral-sh/uv) **uniquement**. Ne jamais invoquer `pip` directement.
* **Théorie des Graphes :** `networkx >= 3.2`
* **Validation & Typage :** `pydantic >= 2.7.0` et `pydantic-settings >= 2.2.0`
* **Interface & Rendu Console :** `rich >= 13.7.0`
* **Visualisation Interactive :** vis-network 9.1.2 locale (`lib/`), template HTML sur mesure en Dark-Mode
* **Lecture des pièces :** `pillow`, `pypdfium2`, Tesseract (OCR témoin, binaire système)
* **Moteur d'Inférence LLM :** Client `openai >= 1.30.0` pointant vers :
  * Serveur vLLM local déployé sur la puce GB10 (`http://localhost:8000/v1`) en production.
  * OpenRouter en développement, sur pièces générées uniquement.
* **Modèles comparés (même famille Qwen3-VL) :** `qwen3-vl-8b-instruct` (taille RTX) et
  `qwen3-vl-235b-a22b-instruct` (taille GX10, modèle par défaut).
* **Qualité de code & Tests :** `pytest >= 8.0.0`, `ruff >= 0.4.0`

---

## 📂 3. Cartographie des Fichiers du Module

```text
fin-enclave/
├── AGENTS.md                  ← Ce fichier (manuel opérationnel always-on)
├── CONTEXT.md                 ← Bounded context, verrous juridiques, glossaire Ubiquitous Language
├── pyproject.toml             ← Définition des dépendances uv, ruff et build hatchling
├── .env.example               ← Modèle de configuration des backends LLM
├── main.py                    ← Démo CLI Rich : investigation + comparaison des 3 stations
├── scripts/
│   └── aggregate_comparison.py ← Moyenne min-max CPU / 8B / 235B sur plusieurs graines
├── data/
│   ├── demo/pieces/           ← 44 pièces de démonstration (scans, photos, PDF image)
│   ├── demo/pieces.extractions/ ← Lectures et notes scellées par modèle (rejeu hors ligne)
│   ├── demo/pieces.*.json     ← Vérité terrain, scénario caché, extrait ICIJ anonymisé
│   ├── demo/realiste/         ← Dossier réaliste graine 1 (42 pièces, réquisitions bancaires propres)
│   ├── demo/realiste.extractions/ ← Lectures scellées CPU / 8B / 235B du dossier réaliste
│   ├── demo/realiste.*.json   ← Vérité, scénario (ibm_patterns), cas ICIJ anonymisé
│   ├── demo/complexe/         ← Dossier complexe graine 1 (motifs IBM AMLworld + ICIJ, stress)
│   ├── demo/complexe.extractions/ ← Lectures scellées CPU / 8B / 235B du dossier complexe
│   ├── demo/complexe.*.json   ← Vérité, scénario (ibm_patterns), cas ICIJ anonymisé
│   ├── external/ibm_aml/      ← HI-Small_Patterns.txt (Kaggle, ignoré par git)
│   └── outputs/               ← Sorties générées (HTML interactif, JSON scellé, Markdown)
├── lib/                       ← Dépendances web locales (vis-network, tom-select, bindings JS)
├── src/fin_enclave/
│   ├── config.py              ← Paramètres Pydantic Settings (bascule local_gx10 / openrouter)
│   ├── schemas.py             ← ProofPoint, AnomalyReport
│   ├── investigation.py       ← Orchestrateur : lecture → graphe → constats → rapports
│   ├── comparison.py          ← CPU sans LLM vs 8B (RTX) vs 235B (GX10) sur le même dossier
│   ├── reporting.py           ← Rapport Markdown, scellé JSON, graphe HTML
│   ├── documents/             ← Lecture (vision ou règles), OCR témoin, liens inter-pièces, forge
│   │   └── forge_complex.py   ← Générateur dossiers réaliste et stress (IBM + relevés multi-pages)
│   ├── ingestion/
│   │   ├── icij_loader.py     ← Import de la base ICIJ Offshore Leaks (pour --forge)
│   │   └── ibm_aml.py         ← Parsing et sélection des motifs IBM AMLworld
│   ├── graph/
│   │   ├── resolver.py        ← Record Linkage Jaro-Winkler déterministe
│   │   ├── detector.py        ← Tarjan (SCC), Johnson (cycles), éventails, Brandes (pivot)
│   │   ├── structural.py      ← Prête-noms et adresses-hubs (portefeuilles)
│   │   └── visualizer.py      ← Rendu HTML interactif Dark-Mode
│   └── reasoning/qualifier.py ← AnomalyReport sur les faits ; notes LLM contrôlées
└── tests/
```

---

## ⚡ 4. Commandes Usuelles de Référence

Toutes les commandes doivent être exécutées depuis le répertoire `fin-enclave/` :

```bash
# 1. Synchronisation de l'environnement virtuel
uv sync

# 2. Exécution de la démonstration d'investigation complète (dossier démo 44 pièces)
uv run python main.py

# 3. Dossier réaliste (résultat principal, 3 typologies IBM AMLworld, réquisitions propres)
uv run python main.py --forge-complex --preset realiste --seed 1 --dossier data/demo/realiste
uv run python main.py --dossier data/demo/realiste
uv run python scripts/aggregate_comparison.py --set realiste

# 4. Dossier complexe de test de résistance (7 typologies, bruit dense, photos dégradées)
uv run python main.py --forge-complex --preset stress --seed 1 --dossier data/demo/complexe
uv run python main.py --dossier data/demo/complexe
uv run python scripts/aggregate_comparison.py --set complexe

# 5. Lancement de la suite de tests unitaires et d'intégration
uv run pytest

# 6. Lancement d'un test spécifique avec logs verbeux
uv run pytest tests/test_investigation.py -vv -s

# 7. Linting et vérification du code
uv run ruff check .

# 8. Formatage automatique du code
uv run ruff format .
```

---

## 📜 5. Règles d'Or Impératives pour l'Agent (Non Négociables)

1. **Air-Gap Strict & Zéro Fuite de Données (Priorité Absolue) :**
   Les flux financiers analysés relèvent du **Secret Bancaire pénal (Art. L. 511-33 CMF)** et du **Secret de l'Instruction (Art. 11 CPP)**. Il est strictement interdit d'ajouter des dépendances ou du code qui transmettraient des données à un serveur tiers non sollicité. En mode station (`local_gx10`), l'inférence se fait exclusivement sur `localhost:8000`.

2. **Graph-First & Primauté du Déterminisme Mathématique :**
   L'intelligence artificielle probabiliste (LLM) ne doit **jamais** être chargée de chercher des cycles ou d'inventer des intermédiaires par tâtonnement.
   * La détection topologique relève des algorithmes déterministes C++/Python (`networkx`) : **Tarjan** pour les composantes fortement connexes, **Brandes** pour la centralité d'intermédiarité.
   * Le LLM intervient **uniquement en aval** pour la qualification pénale et la synthèse judiciaire sur la base des faits mathématiquement avérés.

3. **Traçabilité Judiciaire Numérique (ISO/IEC 27037) :**
   Tout sommet, toute arête et toute qualification pénale produite doit être indexée avec un objet `ProofPoint` contenant l'empreinte `SHA-256` du conteneur source, le hachage de la page, la cote de procédure formelle et l'horodatage RFC 3161. Ne jamais dégrader ou court-circuiter cette chaîne de preuve.

4. **Contrainte de Schéma Pydantic v2 Inviolable :**
   Toute sortie analytique du modèle de langage doit être encapsulée dans le schéma Pydantic `AnomalyReport` (`schemas.py`). Les faits (montants, entités, pièces) viennent des détecteurs, jamais du LLM. En cas de timeout, d'absence de clé API ou de note infidèle aux faits, la note déterministe de `reasoning/qualifier.py` prend le relais sans lever d'exception non gérée.

5. **Localité & Autonomie des Assets Frontend :**
   Les librairies JS/CSS (`vis-network`, `tom-select`, polices) doivent impérativement résider en local dans le dossier `lib/`. Aucun appel CDN externe (jsdelivr, cdnjs, Google Fonts) n'est toléré dans le template généré par `visualizer.py`.

6. **Standards de Code :**
   * Typage statique Python moderne (`T | None` au lieu de `Optional[T]`, `list[T]` au lieu de `List[T]`).
   * Longueur de ligne maximale : 100 caractères (configurée dans `pyproject.toml`).
   * Tous les tests doivent être verts (`uv run pytest`) avant toute conclusion d'intervention.
