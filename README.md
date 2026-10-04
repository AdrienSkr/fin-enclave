# FinEnclave : qui détient quoi, et où va l'argent

**Un dossier de pièces en vrac (scans, photos, PDF image) en entrée. En sortie : qui détient
quelles sociétés, qui contrôle vraiment, où va l'argent, avec la pièce qui fonde chaque lien.**
Tout tourne en local sur une station ASUS Ascent GX10. Aucune pièce ne quitte la machine.

### Le problème métier : le goulet d'étranglement de l'ingestion

Dans une enquête financière (blanchiment d'argent, fraude fiscale, démantèlement de sociétés écrans), les analystes
disposent déjà de logiciels de visualisation de graphes réputés (**IBM i2 Analyst's Notebook**, **Linkurious**,
**Palantir**).

Mais le marché souffre d'un vide critique :
1. **Les plateformes complètes (Palantir Gotham, ChapsVision)** coûtent des millions d'euros par an et sont
   réservées aux agences de renseignement centrales (DGSI, ministères).
2. **Les outils d'analyse de terrain (IBM i2, Linkurious)** sont des moteurs *post-ingestion* : ils exigent des
   données déjà parfaitement structurées en tableaux. Face à des centaines de scans de relevés bancaires et
   d'actes saisis, les enquêteurs passent des **semaines entières à tout ressaisir manuellement**.
3. **Le Cloud public (OpenAI, Claude) est strictement interdit par la loi :** le secret bancaire pénal
   (Art. L. 511-33 CMF) et le secret de l'instruction (Art. 11 CPP) punissent d'un an de prison ferme toute
   divulgation, sous peine de nullité procédurale (Art. 170 CPP).

**FinEnclave comble ce chaînon manquant :** une appliance souveraine clé en main sur ASUS Ascent GX10 qui
ingère directement les scans bruts, extrait les tableaux bancaires sans perte, reconstruit mathématiquement le
graphe des flux, et prouve chaque lien avec sa pièce source (vérifiable en un clic). Il fonctionne de manière
100 % autonome ou s'interface avec **Neo4j**, **Linkurious** et **IBM i2**.

### Démonstration en une commande

Ce POC répond à une question : **faut-il vraiment un grand modèle, donc un GX10, ou un petit
modèle sur une carte RTX suffit-il ?** On fait lire le même dossier par trois stations et on
compte ce que chacune retrouve.

```powershell
uv sync --extra dev
uv run python main.py
```

La commande lit les 44 pièces de démonstration en **4 secondes**, produit le rapport, ouvre le
graphe interactif et affiche le tableau de comparaison chiffré. Sans clé ni serveur, tout est rejoué depuis
les lectures scellées versionnées (`data/demo/pieces.extractions/`), sans aucun appel réseau.

## Le résultat : pourquoi la station GX10 est indispensable

Pour répondre rigoureusement à la question matérielle, le projet compare trois stations sur le
même dossier :
1. **CPU sans LLM** (règles regex + Tesseract OCR) : station bureautique classique sans GPU ;
2. **Petit modèle 8B** (`qwen/qwen3-vl-8b-instruct`) : ce qui tient dans la VRAM d'une carte grand public RTX 4090 (24 Go) ;
3. **Grand modèle 235B** (`qwen/qwen3-vl-235b-a22b-instruct`) : ce qui requiert les 128 Go de mémoire unifiée de l'ASUS Ascent GX10.

Les deux modèles de vision sont de la **même famille** (Qwen3-VL) et reçoivent le même prompt, les
mêmes garde-fous et les mêmes algorithmes de graphe. Seule la taille change.

---

### 1. Résultat principal : dossier réaliste (typologies IBM AMLworld)

Le dossier réaliste combine la topologie de gouvernance issue des Panama Papers (ICIJ) et les motifs
de blanchiment d'[IBM AMLworld](https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml)
(NeurIPS 2023). Ses paramètres ont été **justifiés et gelés a priori**, sans ajustement a posteriori :
- **Relevés judiciaires propres** : PDF natifs ou scans propres (une banque répond à une réquisition par un PDF ou un scan, jamais par une photo de smartphone). Les autres pièces (actes, statuts, procurations) conservent un mélange réaliste de scans et de photos ;
- **Format bancaire réaliste** : 20 lignes par page en police 20 pt, multi-pages, colonnes Débit / Crédit, soldes reportés, libellés en français et en espagnol ;
- **Bruit d'activité modéré** : 3 à 12 mouvements par compte (une société écran a peu d'activité commerciale réelle) ;
- **Typologies d'instruction ciblées** : 3 schémas typiques d'investigation financière :
  - **CYCLE (Circuit fermé)** : l'argent quitte une société A, transite par plusieurs sociétés relais B et C, et revient à l'émetteur A ($A \to B \to C \to A$) pour masquer l'origine des fonds ;
  - **FAN-OUT (Dispersion en éventail / Schtroumpfage)** : un compte émetteur fractionne une grosse somme en plusieurs virements sous le seuil d'alerte vers de multiples comptes relais ou « mules » ($A \to B_1, B_2, B_3\dots$) ;
  - **SCATTER-GATHER (Dispersion puis regroupement)** : fractionnement complet où des fonds dispersés vers plusieurs comptes intermédiaires sont aussitôt reconcentrés vers un compte collecteur final ($A \to [B_1, B_2, \dots] \to C$) ;
- **Contreparties explicites** : libellés imprimant systématiquement le nom de la contrepartie.

Moyenne et écarts min-max mesurés sur **3 graines indépendantes** (42 pièces par dossier) :

| Métrique | CPU, sans LLM | Petit modèle 8B | Grand modèle 235B |
| :--- | :---: | :---: | :---: |
| Station | tout poste | RTX 4090 (24 Go) | **GX10 (128 Go unifiés)** |
| Mémoire des poids | — | ≈ 17 Go (BF16) | ≈ 120 Go (4 bits) |
| Entités lues (P / R) | 0,92 / 0,37 | 0,99 / 0,96 | 0,90 / **0,99** |
| Liens gouvernance (P / R) | 0,97 / 0,76 | 0,84 / 0,96 | **1,00 / 1,00** |
| Virements lus (P / R) | 1,00 / 0,00 | 0,06 / 0,02 | **0,19 / 0,19** |
| Hallucinations rejetées (OCR) | 0 [0 – 0] | 4,00 [4 – 4] | 4,67 [3 – 7] |
| Pièces illisibles | 0 | 0 | 0 |
| Circuit fermé (CYCLE) | 0 % | 0 % | **17,8 %** [0,0 – 33,3 %] |
| Éventail sortant (FAN-OUT) | 0 % | 0 % | **58,6 %** [14,3 – 90,0 %] |
| Dispersion-regroupement (SCATTER-GATHER) | 0 % | 5,6 % [0,0 – 16,7 %] | **27,8 %** [0,0 – 50,0 %] |

#### Ce que révèlent ces mesures :
- **Gouvernance & Sociétés écrans :** Le grand modèle 235B réalise un **sans-faute absolu (100 % de précision et 100 % de rappel)** sur les liens de détention et de direction. Le petit modèle 8B commet des fausses attributions (précision 0,84) et le CPU sans LLM rate près d'un quart des liens (rappel 0,76).
- **Virements bancaires & Typologies :** L'extraction de tableaux de relevés multi-colonnes en vision pure est l'épreuve la plus difficile.
  - Le CPU (Tesseract) est incapable de structurer les relevés (rappel 0,00).
  - Le modèle 8B s'effondre face aux tableaux (rappel 0,02 sur les virements, 0 % sur CYCLE et FAN-OUT).
  - Le grand modèle 235B extrait 19 % des mouvements et parvient à reconstituer la topologie des réseaux de blanchiment : **58,6 % des flux FAN-OUT** (jusqu'à 90 % selon les graines), **27,8 % des flux SCATTER-GATHER** et **17,8 % des CYCLES**.
- **La justification matérielle du GX10 :**
  Les poids du modèle 235B en quantification 4 bits occupent **≈ 120 Go d'espace mémoire**. Il est physiquement impossible de les charger sur une carte grand public RTX 4090 (24 Go VRAM) ni même sur une carte professionnelle de 48 Go. Ils requièrent les **128 Go de mémoire unifiée LPDDR5x** (273 Go/s) du superchip NVIDIA Grace Blackwell GB10.
  En contexte d'instruction financière, le **secret de l'instruction (Art. 11 CPP)** et le **secret bancaire pénal (Art. L. 511-33 CMF)** rendent tout recours au cloud tiers illégal. La station locale ASUS Ascent GX10 à 5 000 € est le seul moyen de faire tourner cette classe de modèle en environnement étanche (*air-gapped*).

#### Pourquoi les alternatives sur RTX (MoE compact ou Hybride OCR+LLM) échouent-elles ?
Pour évaluer si une carte grand public RTX 4090 (24 Go) pouvait suffire, nous avons testé deux architectures alternatives concurrentes :
1. **Un modèle MoE compact (`Qwen3-VL-30B-A3B`, 3B actifs par token, ~17 Go VRAM) :**
   Il remonte le rappel des virements (FAN-OUT à 28,6 %), mais sa **précision sur les liens de gouvernance s'effondre à 54 %** (multiples hallucinations de mandataires et d'actionnaires).
2. **Une architecture hybride à deux étages (OCR neuronal RapidOCR + LLM textuel Qwen-2.5-7B, ~5 Go VRAM) :**
   Si l'OCR spécialisé extrait correctement les tableaux bancaires (rappel virements à 57 %), il aplatit la géométrie 2D des actes juridiques complexes (procurations, statuts avec signatures manuscrites et tampons). Privé de la perception visuelle de la page, le LLM textuel aval intervertit les rôles : **la précision sur la gouvernance s'effondre à 39 %** (6 fausses attributions sur 10 ! Inacceptable pour un juge d'instruction).
3. **Le verdict GX10 :**
   Seul le grand modèle multimodal **235B unifié** sur les **128 Go du GX10** élimine la rupture de chaîne entre la vision et le droit : il garantit **100 % de précision sur la gouvernance (zéro fausse accusation)** tout en reconstruisant les circuits de flux complexes, avec le graphe complet en mémoire vive sans goulot d'étranglement PCIe.

- **Temps d'inférence mesuré :** ≈ 1,1 s par pièce en moyenne (45 secondes pour un dossier complet de 42 pièces).

---

### 2. Dossier de démonstration (44 pièces scellées)

Le dossier de démonstration historique propose un scénario compact comportant un circuit fermé de
2 M USD, un fractionnement de 57 125 USD (6 comptes relais) et une dissimulation d'UBO via un
prête-nom (386 525 USD de flux).

Relecture complète avec les lectures scellées actualisées (`data/demo/pieces.extractions/`) :

| Métrique | CPU, sans LLM | Petit modèle 8B | Grand modèle 235B |
| :--- | :---: | :---: | :---: |
| Station | tout poste | RTX 4090 (24 Go) | **GX10 (128 Go unifiés)** |
| Mémoire des poids | — | ≈ 17 Go (BF16) | ≈ 120 Go (4 bits) |
| Entités lues (P / R) | 1,00 / 0,87 | 0,98 / 1,00 | 0,84 / **1,00** |
| Liens détention / contrôle (P / R) | 1,00 / 0,88 | 0,93 / 0,95 | **1,00 / 1,00** |
| Virements lus (P / R) | 0,89 / 0,74 | 1,00 / 0,43 | **1,00 / 1,00** |
| Hallucinations rejetées | 0 | 3 | 3 |
| Pièces illisibles | 0 | 0 | 0 |
| Circuit fermé (2 M USD) | non | **oui** | **oui** |
| Fractionnement (6 relais) | non | non | **oui (6/6 relais)** |
| Bénéficiaire caché | **oui** | **oui** | **oui** |
| Notes d'analyse fidèles aux faits | pas de LLM | 2 / 2 | **3 / 3** |

Sur ce dossier resserré, **seul le grand modèle 235B retrouve les 3 infractions**. Le petit modèle
8B rate complètement le fractionnement car il ignore plus de la moitié des mouvements de relevés
(rappel 43 %). Le CPU sans LLM rate le circuit fermé à cause des photos de téléphone.

---

### 3. Test de résistance : dossier complexe (stress maximal)

Ce dossier d'endurance pousse les pièges documentaires à l'extrême : un tiers des relevés multi-pages
photographiés avec du bruit et des ombres en JPEG dégradé (qualité 45), 20 à 40 mouvements de bruit
parasite par compte, et **7 typologies IBM AMLworld empilées** dans un même dossier.

Moyenne et écarts min-max sur **3 graines** (54 à 62 pièces par dossier) :

| Métrique | CPU, sans LLM | Petit modèle 8B | Grand modèle 235B |
| :--- | :---: | :---: | :---: |
| Station | tout poste | RTX 4090 (24 Go) | **GX10 (128 Go unifiés)** |
| Mémoire des poids | — | ≈ 17 Go (BF16) | ≈ 120 Go (4 bits) |
| Entités (P / R) | 0,84 / 0,13 | 0,96 / 0,72 | 0,41 / 0,28 |
| Liens gouvernance (P / R) | 0,99 / 0,74 | 0,77 / 0,80 | **1,00 / 1,00** |
| Virements (P / R) | 1,00 / 0,00 | 0,67 / 0,00 | **0,06 / 0,04** |
| Hallucinations rejetées | 0,33 [0 – 1] | 28,67 [18 – 47] | 24,67 [11 – 39] |
| Typologie IBM CYCLE | 0 % | 0 % | **41,1 %** [33,3 – 50,0 %] |
| Typologie IBM FAN-OUT | 0 % | 0 % | **53,8 %** [0,0 – 90,0 %] |
| Typologie IBM SCATTER-GATHER | 0 % | 0 % | **33,3 %** [0,0 – 66,7 %] |
| Typologies FAN-IN / GATHER-SCATTER / STACK / BIPARTITE | 0 % | 0 % | 0 % |

Même sous ces conditions de dégradation extrême, le 235B conserve un **rappel parfait (100 %) sur la
gouvernance** et retrouve 3 typologies IBM sur les flux (41 % des cycles, 54 % des éventails), là où
le 8B et le CPU restent à 0 % sur l'ensemble des typologies.

## Données : topologie réelle, noms fictifs, argent simulé

- **Topologie.** Le réseau (qui est actionnaire, dirigeant ou agent de qui) reproduit un vrai
  sous-graphe des Panama Papers, issu de la base
  [ICIJ Offshore Leaks](https://offshoreleaks.icij.org) (licence ODbL). Les documents bruts ne
  sont pas publics : on reconstruit des pièces à partir de cette topologie.
- **Noms.** Tous les noms sont **fictifs**. Aucune identité réelle n'est publiée.
- **Argent.** Virements, relevés et procurations sont **simulés** (la base ICIJ ne contient
  aucun montant). L'ICIJ rappelle qu'il existe des usages légitimes des sociétés offshore.
- **Motifs de blanchiment (dossier complexe).** Issus d'IBM AMLworld (CDLA-Sharing-1.0),
  représentant les schémas canoniques de dissimulation financière :
  - **CYCLE (Circuit fermé)** : l'argent quitte $A$, transite par plusieurs sociétés relais $B \to C$, et revient à $A$ pour blanchir son origine ;
  - **FAN-OUT (Dispersion en éventail / Schtroumpfage - *Smurfing*)** : un donneur d'ordre découpe un gros montant en multiples petits virements sous les seuils d'alerte bancaire vers des comptes relais ou « mules » ;
  - **FAN-IN (Collecte en éventail)** : schéma inverse, où plusieurs comptes relais regroupent leurs fonds vers un compte collecteur unique ;
  - **SCATTER-GATHER (Dispersion puis regroupement)** : schéma complet de schtroumpfage où les fonds dispersés vers plusieurs mules sont immédiatement reconcentrés vers une destination finale ;
  - **GATHER-SCATTER (Concentration puis redistribution)** : un compte pivot central collecte des fonds de plusieurs sources pour les redistribuer aussitôt vers d'autres entités ;
  - **STACK (Cascade linéaire)** : chaîne de virements successifs de compte en compte ($A \to B \to C \to D$) sans justification commerciale, servant à allonger la piste d'audit et multiplier les juridictions ;
  - **BIPARTITE (Flux croisés)** : transferts enchevêtrés entre deux ensembles distincts de sociétés écrans.

## Comment ça marche : la pipeline de données et le rôle du LLM

```text
pièces brutes (PNG / JPG / PDF image)
  │
  ├─► [Intervention 1 : VLM] Lecture visuelle pièce par pièce -> JSON contraint (Pydantic)
  │     └─ Contrôle témoin : OCR Tesseract indépendant (rejet des entités absentes)
  │
  ├─► [Zéro LLM - Déterministe] Mise en relation d'entités (Jaro-Winkler)
  │
  ├─► [Zéro LLM - Déterministe] Graphe multi-couches : détention / contrôle / flux
  │
  ├─► [Zéro LLM - Déterministe] Algorithmes de graphes :
  │     • Tarjan : composantes fortement connexes (SCC)
  │     • Johnson : détection mathématique des cycles de flux
  │     • Algorithmes de flux : éventails (fractionnement), portefeuilles (prête-noms)
  │     • Brandes : centralité d'intermédiarité (identification du nœud pivot)
  │
  └─► [Intervention 2 : LLM] Rédaction de la note judiciaire pour le magistrat (AnomalyReport)
        └─ Garde-fou strict : rejet de la note si le LLM cite un montant ou une cote hors des faits
```

### Le rôle exact du LLM et ce qui est évalué :

1. **Intervention 1 (VLM en entrée - Perception) : Transcrire fidèlement chaque pièce.**
   - Le modèle de vision lit l'image (scan, photo) et extrait un schéma structuré `DocumentExtraction` (entités, relations juridiques écrites, lignes de relevé bancaire).
   - **Règle absolue :** *"Transcrire, puis interpréter"*. Le modèle a interdiction de deviner des flux ou d'inventer des liens.
   - **C'est cette intervention qui est mesurée dans les tableaux de comparaison :** Précision/Rappel des entités, des liens de gouvernance et des virements. Si le VLM rate les lignes d'un tableau bancaire (comme le 8B sur les relevés multi-colonnes), le graphe aval est amputé et les algorithmes mathématiques ne peuvent pas détecter les circuits.

2. **Cœur de détection (Au centre) : 100 % Déterministe, ZÉRO LLM.**
   - L'IA probabiliste **ne cherche ni les liens, ni les coupables, ni les infractions**. 
   - La détection repose exclusivement sur la théorie des graphes et le déterminisme mathématique (Tarjan, Johnson, Brandes).

3. **Intervention 2 (LLM en sortie - Narration) : Rédiger la note de synthèse judiciaire.**
   - Le LLM reçoit en entrée **exclusivement les faits mathématiquement et cryptographiquement avérés** (montants, circuit de comptes, cotes de scellés `PIECE-xxxx`) et les bases légales (Art. 324-1 CP blanchiment, Art. L. 561-15 CMF soupçon TRACFIN, Recommandations GAFI).
   - Il traduit ces faits en un paragraphe clair, factuel et au conditionnel, destiné au juge d'instruction ou à l'analyste.
   - **Pourquoi la 2ème intervention n'est pas évaluée pour la détection :** Elle n'a aucun pouvoir décisionnel sur l'enquête. L'évaluation de cette étape est un simple verrou de sécurité binaire mesuré par la ligne *"Notes d'analyse fidèles aux faits"* (ex. 3/3) : si la note cite un montant ou une cote absent des faits scellés, elle est **automatiquement rejetée** et remplacée par la note déterministe pré-calculée.

- **Interopérabilité :** Le graphe généré est directement explorable dans le visualiseur HTML interactif
  autonome (`graphe.html`), et son modèle de données (nœuds et arêtes typées) s'interface avec les outils
  d'investigation d'entreprise (**Neo4j**, **Linkurious**, **IBM i2 Analyst's Notebook**).

## Air-gap et station GX10

En mode `local_gx10`, la configuration refuse tout serveur d'inférence qui n'est pas sur
`localhost` (voir `.env.example`). Pour mesurer à nouveau la comparaison avec une clé OpenRouter,
supprimer les lectures scellées des modèles voulus dans `data/demo/pieces.extractions/`.

```powershell
uv run python main.py --dossier CHEMIN      # un autre dossier de pièces
uv run python main.py --no-compare          # sans le tableau de comparaison
uv run python main.py --forge --seed 7      # régénérer la démo (base ICIJ dans data/external/oldb)

# Dossier réaliste (résultat principal)
uv run python main.py --forge-complex --preset realiste --seed 1 --dossier data/demo/realiste
uv run python main.py --dossier data/demo/realiste
uv run python scripts/aggregate_comparison.py --set realiste

# Dossier complexe (test de résistance)
uv run python main.py --forge-complex --preset stress --seed 1 --dossier data/demo/complexe
uv run python main.py --dossier data/demo/complexe
uv run python scripts/aggregate_comparison.py --set complexe

uv run pytest
uv run ruff check .
```
