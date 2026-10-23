# Rapport d'investigation : dossier de pièces

- **Dossier** : `data/demo/pieces` (50 pièces, 0 en échec)
- **Lecture des pièces** : `vlm-redhatai-qwen2-5-vl-72b-instruct-fp8-dynamic-p3279f0cb`
- **Généré le** : 2026-10-23 02:02 UTC, en local
- **Méthode** : les liens et les anomalies sont trouvés par des algorithmes déterministes (résolution de noms, Tarjan, Johnson, Brandes) ; le modèle de langage ne fait que lire les pièces et, en option, rédiger les notes. Chaque fait renvoie à ses pièces.

> **Données.** Les sociétés, dirigeants et intermédiaires proviennent d'un vrai réseau des Panama Papers (base ICIJ Offshore Leaks, licence ODbL). Les virements, relevés, procurations et le bénéficiaire caché sont **simulés** pour la démonstration (la base ICIJ ne contient aucun montant). Aucun fait n'est imputé aux sociétés réelles citées.

## 1. Synthèse

- **Profil de prête-nom présumé** : Willowmere Trading S.A. est inscrit au registre de **12 sociétés** du dossier au titre de mandats ; hypothèse à vérifier.
- **Bénéficiaire caché possible** : Oskar Lindqvist détient une procuration non enregistrée sur Northwind Group S.A., Thornfield Capital Ltd. ([PIECE-0004](../../demo/pieces/PIECE-0004.pdf), [PIECE-0009](../../demo/pieces/PIECE-0009.jpg), [PIECE-0026](../../demo/pieces/PIECE-0026.pdf), [PIECE-0031](../../demo/pieces/PIECE-0031.pdf)).
- **Circuit fermé de flux** : Thornfield Capital Limited → Stonehaven Investments S.A. → Brightwater Group Corp. → Willowmere Capital Corp. → Thornfield Capital Limited, 2 002 500 USD injectés, 1 868 336 USD revenus.
- **Fractionnement possible** : Copperfield Investments Corp. → 6 relais → Northwind Group S.A. (55 806 USD collectés, virements sous 10 000 USD).
- **Solde net le plus élevé** : Oskar Lindqvist, **386 525 USD** sur l'ensemble des flux du dossier ([PIECE-0015](../../demo/pieces/PIECE-0015.jpg), [PIECE-0024](../../demo/pieces/PIECE-0024.pdf)).

## 2. Constats et qualifications envisagées

### 2.1. Circuit fermé (round-tripping)

> Circuit fermé de 4 sociétés : Thornfield Capital Limited -> Stonehaven Investments S.A. -> Brightwater Group Corp. -> Willowmere Capital Corp. -> Thornfield Capital Limited. 2,002,500 USD sortent de Thornfield Capital Limited et 1,868,336 USD y reviennent (écart 6.7 %, au plus 2.7 % par étape). Pièces : PIECE-0006, PIECE-0018, PIECE-0020, PIECE-0037.

- Score de confiance : **100%**
- Rédaction de la note : deterministe
- Fondements à examiner : Art. 324-1 du Code pénal : blanchiment (dissimulation de l'origine des fonds) ; Art. L. 561-15 du Code monétaire et financier : déclaration de soupçon (TRACFIN)
- Actions proposées : Confronter les pièces citées aux originaux scellés avant toute exploitation ; Requérir les relevés complets des comptes du circuit sur la période ; Si confirmé : déclaration de soupçon (Art. L. 561-15 CMF)
- Cotes : PIECE-0006, PIECE-0018, PIECE-0020, PIECE-0037

### 2.2. Fractionnement (schtroumpfage)

> Copperfield Investments Corp. aurait fractionné 57,125 USD en 6 virements chacun sous le seuil de 10,000 USD vers 6 relais (Nadia Petrova, Irene Kowalski, Daniel Moreau, Lena Hartmann, Marco Fiore, Pablo Serrano), qui reversent 55,806 USD à Northwind Group S.A. ; les fonds repartent ensuite vers Oskar Lindqvist. Pièces : PIECE-0015, PIECE-0019.

- Score de confiance : **100%**
- Rédaction de la note : deterministe
- Fondements à examiner : Art. 324-1 du Code pénal : blanchiment (concours à une opération de dissimulation) ; Art. L. 561-15 du Code monétaire et financier : déclaration de soupçon (TRACFIN)
- Actions proposées : Identifier les titulaires réels des comptes relais (KYC des banques teneuses) ; Rechercher d'autres éventails du même émetteur hors de la période ; Si confirmé : déclaration de soupçon (Art. L. 561-15 CMF)
- Cotes : PIECE-0015, PIECE-0019

### 2.3. Bénéficiaire caché derrière un prête-nom

> Les registres désignent Willowmere Trading S.A. (profil de prête-nom présumé) pour Northwind Group S.A., Thornfield Capital Ltd.. Une procuration non enregistrée donne à Oskar Lindqvist le pouvoir d'opérer les comptes de ces sociétés ; Oskar Lindqvist reçoit 386,525 USD de flux attestés. Bénéficiaire effectif présumé, à confirmer. Pièces : PIECE-0004, PIECE-0009, PIECE-0015, PIECE-0024, PIECE-0026, PIECE-0031.

- Score de confiance : **100%**
- Rédaction de la note : deterministe
- Fondements à examiner : Art. L. 561-2-2 du Code monétaire et financier : définition du bénéficiaire effectif ; Recommandation 24 du GAFI : transparence des bénéficiaires effectifs des personnes morales ; Art. 324-1 du Code pénal : blanchiment, si l'origine des fonds est établie
- Actions proposées : Confronter Oskar Lindqvist au registre des bénéficiaires effectifs des juridictions ; Requérir les mandats bancaires et les signatures des comptes des sociétés citées ; Rechercher les autres sociétés sur lesquelles ce mandataire détient une procuration
- Cotes : PIECE-0004, PIECE-0009, PIECE-0015, PIECE-0024, PIECE-0026, PIECE-0031

**Fractionnement** : Copperfield Investments Corp. → Nadia Petrova, Irene Kowalski, Daniel Moreau, Lena Hartmann, Marco Fiore, Pablo Serrano → Northwind Group S.A. ; 57 125 USD envoyés, 55 806 USD collectés ([PIECE-0015](../../demo/pieces/PIECE-0015.jpg), [PIECE-0019](../../demo/pieces/PIECE-0019.png)).

### Chronologie des flux des constats

| Date | Émetteur | Bénéficiaire | Montant | Constat | Cotes |
| :--- | :--- | :--- | ---: | :--- | :--- |
| 2014-03-26 | Thornfield Capital Limited | Stonehaven Investments S.A. | 2 002 500 USD | Circuit fermé 1 | [PIECE-0037](../../demo/pieces/PIECE-0037.png) |
| 2014-04-03 | Stonehaven Investments S.A. | Brightwater Group Corp. | 1 949 047 USD | Circuit fermé 1 | [PIECE-0006](../../demo/pieces/PIECE-0006.jpg) |
| 2014-04-12 | Brightwater Group Corp. | Willowmere Capital Corp. | 1 899 955 USD | Circuit fermé 1 | [PIECE-0020](../../demo/pieces/PIECE-0020.jpg) |
| 2014-04-21 | Willowmere Capital Corp. | Thornfield Capital Limited | 1 868 336 USD | Circuit fermé 1 | [PIECE-0018](../../demo/pieces/PIECE-0018.pdf) |
| 2014-04-23 | Copperfield Investments Corp. | Nadia Petrova | 9 600 USD | Fractionnement 1 | [PIECE-0019](../../demo/pieces/PIECE-0019.png) |
| 2014-04-23 | Copperfield Investments Corp. | Marco Fiore | 9 350 USD | Fractionnement 1 | [PIECE-0019](../../demo/pieces/PIECE-0019.png) |
| 2014-04-23 | Copperfield Investments Corp. | Lena Hartmann | 9 525 USD | Fractionnement 1 | [PIECE-0019](../../demo/pieces/PIECE-0019.png) |
| 2014-04-24 | Copperfield Investments Corp. | Daniel Moreau | 9 650 USD | Fractionnement 1 | [PIECE-0019](../../demo/pieces/PIECE-0019.png) |
| 2014-04-24 | Copperfield Investments Corp. | Irene Kowalski | 9 725 USD | Fractionnement 1 | [PIECE-0019](../../demo/pieces/PIECE-0019.png) |
| 2014-04-24 | Copperfield Investments Corp. | Pablo Serrano | 9 275 USD | Fractionnement 1 | [PIECE-0019](../../demo/pieces/PIECE-0019.png) |
| 2014-04-25 | Nadia Petrova | Northwind Group S.A. | 9 317 USD | Fractionnement 1 | [PIECE-0015](../../demo/pieces/PIECE-0015.jpg) |
| 2014-04-25 | Irene Kowalski | Northwind Group S.A. | 9 465 USD | Fractionnement 1 | [PIECE-0015](../../demo/pieces/PIECE-0015.jpg) |
| 2014-04-26 | Daniel Moreau | Northwind Group S.A. | 9 386 USD | Fractionnement 1 | [PIECE-0015](../../demo/pieces/PIECE-0015.jpg) |
| 2014-04-26 | Lena Hartmann | Northwind Group S.A. | 9 424 USD | Fractionnement 1 | [PIECE-0015](../../demo/pieces/PIECE-0015.jpg) |
| 2014-04-27 | Marco Fiore | Northwind Group S.A. | 9 154 USD | Fractionnement 1 | [PIECE-0015](../../demo/pieces/PIECE-0015.jpg) |
| 2014-04-27 | Pablo Serrano | Northwind Group S.A. | 9 060 USD | Fractionnement 1 | [PIECE-0015](../../demo/pieces/PIECE-0015.jpg) |

## 3. Entités et flux

### 3.1. Qui détient / dirige quoi

| Société | Inscrits au registre | Procuration | Agent | Pièces |
| :--- | :--- | :--- | :--- | :--- |
| Amberfield Management Corp. | Willowmere Trading S.A. (actionnaire)<br>Mistvale Enterprises Ltd. (actionnaire)<br>Helena Morales (actionnaire) | — | Coral Fiduciary Services Ltd. | [PIECE-0017](../../demo/pieces/PIECE-0017.jpg), [PIECE-0028](../../demo/pieces/PIECE-0028.png) |
| Brightwater Group Corp. | Willowmere Trading S.A. (actionnaire)<br>Mistvale Enterprises Ltd. (actionnaire)<br>Oakridge Management Ltd. (actionnaire)<br>Thornfield Assets Ltd. (actionnaire) | — | Coral Fiduciary Services Ltd. | [PIECE-0029](../../demo/pieces/PIECE-0029.pdf), [PIECE-0035](../../demo/pieces/PIECE-0035.png) |
| Copperfield Investments Corp. | Willowmere Trading S.A. (actionnaire)<br>Mateo Pavlov (bénéficiaire effectif) | — | Coral Fiduciary Services Ltd. | [PIECE-0012](../../demo/pieces/PIECE-0012.pdf), [PIECE-0019](../../demo/pieces/PIECE-0019.png), [PIECE-0039](../../demo/pieces/PIECE-0039.png) |
| Ironwood Trading S.A. | Willowmere Trading S.A. (actionnaire) | — | Coral Fiduciary Services Ltd. | [PIECE-0003](../../demo/pieces/PIECE-0003.jpg), [PIECE-0005](../../demo/pieces/PIECE-0005.jpg), [PIECE-0033](../../demo/pieces/PIECE-0033.png) |
| Mistvale Assets S.A. | Willowmere Trading S.A. (actionnaire) | — | Coral Fiduciary Services Ltd. | [PIECE-0042](../../demo/pieces/PIECE-0042.png), [PIECE-0043](../../demo/pieces/PIECE-0043.png) |
| Northwind Group S.A. | Willowmere Trading S.A. (actionnaire)<br>Priya Ibarra (bénéficiaire effectif) | Oskar Lindqvist | Coral Fiduciary Services Ltd. | [PIECE-0015](../../demo/pieces/PIECE-0015.jpg), [PIECE-0026](../../demo/pieces/PIECE-0026.pdf), [PIECE-0031](../../demo/pieces/PIECE-0031.pdf), [PIECE-0040](../../demo/pieces/PIECE-0040.jpg) |
| Oakridge Partners Corp. | Willowmere Trading S.A. (actionnaire)<br>Mistvale Enterprises Ltd. (actionnaire)<br>Ashcroft Assets S.A. (actionnaire)<br>Nora Morales (actionnaire) | — | Coral Fiduciary Services Ltd. | [PIECE-0034](../../demo/pieces/PIECE-0034.png), [PIECE-0036](../../demo/pieces/PIECE-0036.png) |
| Oakridge Ventures Inc. | Willowmere Trading S.A. (actionnaire) | — | Coral Fiduciary Services Ltd. | [PIECE-0023](../../demo/pieces/PIECE-0023.jpg), [PIECE-0025](../../demo/pieces/PIECE-0025.png) |
| Silverpine Assets Corp. | Willowmere Trading S.A. (actionnaire) | — | Coral Fiduciary Services Ltd. | [PIECE-0010](../../demo/pieces/PIECE-0010.png), [PIECE-0032](../../demo/pieces/PIECE-0032.pdf) |
| Stonehaven Investments S.A. | Willowmere Trading S.A. (actionnaire) | — | Coral Fiduciary Services Ltd. | [PIECE-0007](../../demo/pieces/PIECE-0007.pdf), [PIECE-0008](../../demo/pieces/PIECE-0008.pdf) |
| Thornfield Capital Ltd. | Willowmere Trading S.A. (actionnaire)<br>Vincent Holmgren (bénéficiaire effectif) | Oskar Lindqvist | Coral Fiduciary Services Ltd. | [PIECE-0002](../../demo/pieces/PIECE-0002.png), [PIECE-0004](../../demo/pieces/PIECE-0004.pdf), [PIECE-0009](../../demo/pieces/PIECE-0009.jpg) |
| Willowmere Capital Corp. | Willowmere Trading S.A. (actionnaire)<br>Quentin Ibarra (actionnaire) | — | Maple Register Agents Ltd. | [PIECE-0001](../../demo/pieces/PIECE-0001.jpg), [PIECE-0041](../../demo/pieces/PIECE-0041.png) |

### 3.2. Portefeuilles de mandats

| Acteur | Sociétés | Rôles | Profil |
| :--- | ---: | :--- | :--- |
| Willowmere Trading S.A. | 12 | actionnaire ×12 | prête-nom présumé (à vérifier) |
| Mistvale Enterprises Ltd. | 3 | actionnaire ×3 |  |
| Ashcroft Assets S.A. | 1 | actionnaire ×1 |  |
| Helena Morales | 1 | actionnaire ×1 |  |
| Mateo Pavlov | 1 | bénéficiaire effectif ×1 | bénéficiaire effectif déclaré |
| Nora Morales | 1 | actionnaire ×1 |  |
| Oakridge Management Ltd. | 1 | actionnaire ×1 |  |
| Priya Ibarra | 1 | bénéficiaire effectif ×1 | bénéficiaire effectif déclaré |

Seuil du profil de prête-nom : au moins 4 sociétés au titre de mandats (les rôles de bénéficiaire effectif déclaré ne comptent pas).

Sommet le plus central du graphe (Brandes) : **Copperfield Investments Corp.** (intermédiarité 0.0052).

### 3.3. Destination des fonds

Bilan net cumulé sur 23 virements (8 238 505 USD au total).

| Acteur | Reçu | Envoyé | Solde net | Pièces |
| :--- | ---: | ---: | ---: | :--- |
| Oskar Lindqvist | 386 525 USD | 0 USD | **386 525 USD** | [PIECE-0015](../../demo/pieces/PIECE-0015.jpg), [PIECE-0024](../../demo/pieces/PIECE-0024.pdf) |
| Stonehaven Investments S.A. | 2 002 500 USD | 1 950 757 USD | **51 743 USD** | [PIECE-0006](../../demo/pieces/PIECE-0006.jpg), [PIECE-0022](../../demo/pieces/PIECE-0022.pdf), [PIECE-0037](../../demo/pieces/PIECE-0037.png) |
| Brightwater Group Corp. | 1 949 047 USD | 1 905 605 USD | **43 441 USD** | [PIECE-0006](../../demo/pieces/PIECE-0006.jpg), [PIECE-0011](../../demo/pieces/PIECE-0011.pdf), [PIECE-0020](../../demo/pieces/PIECE-0020.jpg) |
| Willowmere Capital Corp. | 1 899 955 USD | 1 868 336 USD | **31 619 USD** | [PIECE-0018](../../demo/pieces/PIECE-0018.pdf), [PIECE-0020](../../demo/pieces/PIECE-0020.jpg) |
| Redwood Telecom Ltd | 5 650 USD | 0 USD | **5 650 USD** | [PIECE-0011](../../demo/pieces/PIECE-0011.pdf) |
| Northwind Group S.A. | 55 806 USD | 50 225 USD | **5 581 USD** | [PIECE-0015](../../demo/pieces/PIECE-0015.jpg) |
| Pinewood Couriers Ltd | 4 515 USD | 0 USD | **4 515 USD** | [PIECE-0038](../../demo/pieces/PIECE-0038.png) |
| Summit Supplies Ltd | 3 856 USD | 0 USD | **3 856 USD** | [PIECE-0033](../../demo/pieces/PIECE-0033.png) |
| Pinewood Telecom Ltd | 3 480 USD | 0 USD | **3 480 USD** | [PIECE-0021](../../demo/pieces/PIECE-0021.png) |
| Harbour Printing Ltd | 1 710 USD | 0 USD | **1 710 USD** | [PIECE-0022](../../demo/pieces/PIECE-0022.pdf) |

### Chaîne de contrôle jusqu'à la personne physique

| Société d'un constat | Chaîne de détention | Personne physique | Pièces |
| :--- | :--- | :--- | :--- |
| Copperfield Investments Corp. | Copperfield Investments Corp. → Mateo Pavlov | Mateo Pavlov | [PIECE-0012](../../demo/pieces/PIECE-0012.pdf) |
| Copperfield Investments Corp. | Copperfield Investments Corp. → Willowmere Trading S.A. | *non atteinte (chaîne interrompue)* | [PIECE-0012](../../demo/pieces/PIECE-0012.pdf) |
| Northwind Group S.A. | Northwind Group S.A. → Priya Ibarra | Priya Ibarra | [PIECE-0031](../../demo/pieces/PIECE-0031.pdf) |
| Northwind Group S.A. | Northwind Group S.A. → Willowmere Trading S.A. | *non atteinte (chaîne interrompue)* | [PIECE-0026](../../demo/pieces/PIECE-0026.pdf), [PIECE-0031](../../demo/pieces/PIECE-0031.pdf) |
| Thornfield Capital Ltd. | Thornfield Capital Ltd. → Vincent Holmgren | Vincent Holmgren | [PIECE-0009](../../demo/pieces/PIECE-0009.jpg) |
| Thornfield Capital Ltd. | Thornfield Capital Ltd. → Willowmere Trading S.A. | *non atteinte (chaîne interrompue)* | [PIECE-0004](../../demo/pieces/PIECE-0004.pdf), [PIECE-0009](../../demo/pieces/PIECE-0009.jpg) |

### Priorisation des entités et des constats

Score explicable sur 100 : montant en jeu dans les constats (max 40), typologies distinctes (20), centralité (15), nombre de constats (25). Une société sans constat ne peut dépasser le seul poids de la centralité.

| Rang | Entité | Score | Décomposition | Typologies |
| ---: | :--- | ---: | :--- | :--- |
| 1 | Thornfield Capital Limited | **64.89** | amount 39.18 + typologies 10 + centrality 10.71 + findings 5 | cycle |
| 2 | Stonehaven Investments S.A. | **60.71** | amount 40 + typologies 10 + centrality 5.71 + findings 5 | cycle |
| 3 | Brightwater Group Corp. | **60.39** | amount 38.96 + typologies 10 + centrality 6.43 + findings 5 | cycle |
| 4 | Willowmere Capital Corp. | **60.28** | amount 38.14 + typologies 10 + centrality 7.14 + findings 5 | cycle |
| 5 | Copperfield Investments Corp. | **30.58** | amount 0.58 + typologies 10 + centrality 15 + findings 5 | fractionnement |
| 6 | Northwind Group S.A. | **29.85** | amount 0.56 + typologies 10 + centrality 14.29 + findings 5 | fractionnement |
| 7 | Oskar Lindqvist | **26.77** | amount 3.91 + typologies 10 + centrality 12.86 | contrôleur caché |
| 8 | Daniel Moreau | **15.9** | amount 0.19 + typologies 10 + centrality 0.71 + findings 5 | fractionnement |
| 9 | Irene Kowalski | **15.9** | amount 0.19 + typologies 10 + centrality 0.71 + findings 5 | fractionnement |
| 10 | Lena Hartmann | **15.9** | amount 0.19 + typologies 10 + centrality 0.71 + findings 5 | fractionnement |

| Rang | Constat | Score | Décomposition | Montant |
| ---: | :--- | ---: | :--- | ---: |
| 1 | Circuit fermé 1 | **84.29** | amount 60 + centrality 14.29 + entities 10 | 7 719 838 USD |
| 2 | Fractionnement 1 | **40.88** | amount 0.88 + centrality 20 + entities 20 | 112 931 USD |

## 4. À valider par l'enquêteur

### Contrôles de lecture

- Pièces non lues : 0
- Entités écartées (absentes de la lecture OCR témoin) : 0
- Entités non vérifiables (pièce illisible pour l'OCR témoin) : 0
- Montants non corroborés par l'OCR témoin : 0
- Virements sans date lisible : 0
- Variantes de noms fusionnées : 6 : Thornfield Capital Limited = Thornfield Capital Ltd.; Thornfield Capital Limited = Thornfield Capital Ltd.; Summit Telecom Inc = Summit Telecom Ltd; Redwood Printing Inc = Redwood Printing Ltd; Paper Supplies Ltd = Paper Supplies Inc; Crescent Supplies Inc = Crescent Supplies Ltd

### Réquisitions complémentaires à envisager

| Compte (titulaire) | Banque | Période à requérir | Motif | Confirmation | Pièces citant le compte |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Brightwater Group Corp. (constat) | non précisée dans les pièces | 2014-04-03 au 2014-05-20 | aucun relevé au dossier | — | [PIECE-0006](../../demo/pieces/PIECE-0006.jpg), [PIECE-0011](../../demo/pieces/PIECE-0011.pdf), [PIECE-0020](../../demo/pieces/PIECE-0020.jpg) |
| Daniel Moreau (constat) | non précisée dans les pièces | 2014-04-24 au 2014-04-26 | aucun relevé au dossier | — | [PIECE-0015](../../demo/pieces/PIECE-0015.jpg), [PIECE-0019](../../demo/pieces/PIECE-0019.png) |
| Irene Kowalski (constat) | non précisée dans les pièces | 2014-04-24 au 2014-04-25 | aucun relevé au dossier | — | [PIECE-0015](../../demo/pieces/PIECE-0015.jpg), [PIECE-0019](../../demo/pieces/PIECE-0019.png) |
| Lena Hartmann (constat) | non précisée dans les pièces | 2014-04-23 au 2014-04-26 | aucun relevé au dossier | — | [PIECE-0015](../../demo/pieces/PIECE-0015.jpg), [PIECE-0019](../../demo/pieces/PIECE-0019.png) |
| Marco Fiore (constat) | non précisée dans les pièces | 2014-04-23 au 2014-04-27 | aucun relevé au dossier | — | [PIECE-0015](../../demo/pieces/PIECE-0015.jpg), [PIECE-0019](../../demo/pieces/PIECE-0019.png) |
| Nadia Petrova (constat) | non précisée dans les pièces | 2014-04-23 au 2014-04-25 | aucun relevé au dossier | — | [PIECE-0015](../../demo/pieces/PIECE-0015.jpg), [PIECE-0019](../../demo/pieces/PIECE-0019.png) |
| Pablo Serrano (constat) | non précisée dans les pièces | 2014-04-24 au 2014-04-27 | aucun relevé au dossier | — | [PIECE-0015](../../demo/pieces/PIECE-0015.jpg), [PIECE-0019](../../demo/pieces/PIECE-0019.png) |
| Stonehaven Investments S.A. (constat) | non précisée dans les pièces | 2014-03-26 au 2014-05-19 | aucun relevé au dossier | — | [PIECE-0006](../../demo/pieces/PIECE-0006.jpg), [PIECE-0022](../../demo/pieces/PIECE-0022.pdf), [PIECE-0037](../../demo/pieces/PIECE-0037.png) |
| Thornfield Capital Limited (constat) | non précisée dans les pièces | 2014-03-26 au 2014-04-28 | aucun relevé au dossier | — | [PIECE-0018](../../demo/pieces/PIECE-0018.pdf), [PIECE-0024](../../demo/pieces/PIECE-0024.pdf), [PIECE-0037](../../demo/pieces/PIECE-0037.png) |
| Willowmere Capital Corp. (constat) | non précisée dans les pièces | 2014-04-12 au 2014-04-21 | aucun relevé au dossier | — | [PIECE-0018](../../demo/pieces/PIECE-0018.pdf), [PIECE-0020](../../demo/pieces/PIECE-0020.jpg) |
| Harbour Printing Ltd | non précisée dans les pièces | 2014-05-19 | aucun relevé au dossier | — | [PIECE-0022](../../demo/pieces/PIECE-0022.pdf) |
| Ironwood Trading S.A. | non précisée dans les pièces | 2014-04-17 | aucun relevé au dossier | — | [PIECE-0033](../../demo/pieces/PIECE-0033.png) |
| Oskar Lindqvist | non précisée dans les pièces | 2014-04-28 au 2014-04-29 | aucun relevé au dossier | — | [PIECE-0015](../../demo/pieces/PIECE-0015.jpg), [PIECE-0024](../../demo/pieces/PIECE-0024.pdf) |
| Pinewood Couriers Ltd | non précisée dans les pièces | 2014-04-04 | aucun relevé au dossier | — | [PIECE-0038](../../demo/pieces/PIECE-0038.png) |
| Pinewood Telecom Ltd | non précisée dans les pièces | 2014-04-04 | aucun relevé au dossier | — | [PIECE-0021](../../demo/pieces/PIECE-0021.png) |

4 autres comptes figurent dans le JSON scellé.

## 5. Annexes techniques

### 5.1. Fiabilité mesurée sur ce dossier (vérité terrain connue)

| Mesure | Précision | Rappel |
| :--- | ---: | ---: |
| Entités lues | 1.00 | 1.00 |
| Liens de détention / contrôle lus | 1.00 | 1.00 |
| Virements lus | 1.00 | 1.00 |
| Liens du graphe reconstruit | 1.00 | 1.00 |
| Flux du graphe reconstruit | 1.00 | 1.00 |

- Circuit caché retrouvé : **oui** (faux circuits : 0)
- Fractionnement retrouvé : **oui** (6/6 relais)
- Bénéficiaire caché retrouvé : **oui**

### 5.2. Chaîne de preuve

| Cote | Fichier | Nature lue | SHA-256 |
| :--- | :--- | :--- | :--- |
| PIECE-0001 | [PIECE-0001.jpg](../../demo/pieces/PIECE-0001.jpg) | certificate_of_incorporation | `38b7eb72236a4eff…` |
| PIECE-0002 | [PIECE-0002.png](../../demo/pieces/PIECE-0002.png) | certificate_of_incorporation | `472f7ca2cd6b789d…` |
| PIECE-0003 | [PIECE-0003.jpg](../../demo/pieces/PIECE-0003.jpg) | register_of_directors | `17ca62ecb954862c…` |
| PIECE-0004 | [PIECE-0004.pdf](../../demo/pieces/PIECE-0004.pdf) | power_of_attorney | `b9dff31a5428001f…` |
| PIECE-0005 | [PIECE-0005.jpg](../../demo/pieces/PIECE-0005.jpg) | certificate_of_incorporation | `7665eda8630f0a8c…` |
| PIECE-0006 | [PIECE-0006.jpg](../../demo/pieces/PIECE-0006.jpg) | bank_statement | `c60e8de14d2f87e3…` |
| PIECE-0007 | [PIECE-0007.pdf](../../demo/pieces/PIECE-0007.pdf) | register_of_directors | `8d3e7c49e3436ac3…` |
| PIECE-0008 | [PIECE-0008.pdf](../../demo/pieces/PIECE-0008.pdf) | certificate_of_incorporation | `f38f3ce6da98c55d…` |
| PIECE-0009 | [PIECE-0009.jpg](../../demo/pieces/PIECE-0009.jpg) | register_of_directors | `874b56d787d889ae…` |
| PIECE-0010 | [PIECE-0010.png](../../demo/pieces/PIECE-0010.png) | register_of_directors | `c38bf89276e43229…` |
| PIECE-0011 | [PIECE-0011.pdf](../../demo/pieces/PIECE-0011.pdf) | bank_statement | `2f529da173953a0a…` |
| PIECE-0012 | [PIECE-0012.pdf](../../demo/pieces/PIECE-0012.pdf) | register_of_directors | `3f27e5c532b644cd…` |
| PIECE-0013 | [PIECE-0013.pdf](../../demo/pieces/PIECE-0013.pdf) | invoice | `91d6e028da2f7a08…` |
| PIECE-0014 | [PIECE-0014.pdf](../../demo/pieces/PIECE-0014.pdf) | invoice | `336c1d6c21ec91d9…` |
| PIECE-0015 | [PIECE-0015.jpg](../../demo/pieces/PIECE-0015.jpg) | bank_statement | `98e928f2f32d1074…` |
| PIECE-0016 | [PIECE-0016.pdf](../../demo/pieces/PIECE-0016.pdf) | invoice | `db7441fdfcb70b6b…` |
| PIECE-0017 | [PIECE-0017.jpg](../../demo/pieces/PIECE-0017.jpg) | certificate_of_incorporation | `ebf1e80e34c378d4…` |
| PIECE-0018 | [PIECE-0018.pdf](../../demo/pieces/PIECE-0018.pdf) | bank_statement | `dd625d95581cfbc7…` |
| PIECE-0019 | [PIECE-0019.png](../../demo/pieces/PIECE-0019.png) | bank_statement | `16ff015f752e058b…` |
| PIECE-0020 | [PIECE-0020.jpg](../../demo/pieces/PIECE-0020.jpg) | bank_statement | `b0ec5c60e305778c…` |
| PIECE-0021 | [PIECE-0021.png](../../demo/pieces/PIECE-0021.png) | bank_statement | `cc51170a9272537d…` |
| PIECE-0022 | [PIECE-0022.pdf](../../demo/pieces/PIECE-0022.pdf) | bank_statement | `8d4082e0b1c5a489…` |
| PIECE-0023 | [PIECE-0023.jpg](../../demo/pieces/PIECE-0023.jpg) | register_of_directors | `fa58f336795b89cf…` |
| PIECE-0024 | [PIECE-0024.pdf](../../demo/pieces/PIECE-0024.pdf) | bank_statement | `bb4d15dc113049d0…` |
| PIECE-0025 | [PIECE-0025.png](../../demo/pieces/PIECE-0025.png) | certificate_of_incorporation | `86dff334acb97bf4…` |
| PIECE-0026 | [PIECE-0026.pdf](../../demo/pieces/PIECE-0026.pdf) | power_of_attorney | `abe41f7933f0edd2…` |
| PIECE-0027 | [PIECE-0027.jpg](../../demo/pieces/PIECE-0027.jpg) | invoice | `bf9fe846b91b9747…` |
| PIECE-0028 | [PIECE-0028.png](../../demo/pieces/PIECE-0028.png) | register_of_directors | `90a6413bb3a32548…` |
| PIECE-0029 | [PIECE-0029.pdf](../../demo/pieces/PIECE-0029.pdf) | certificate_of_incorporation | `6f505ff94320b841…` |
| PIECE-0030 | [PIECE-0030.pdf](../../demo/pieces/PIECE-0030.pdf) | invoice | `6a0b1ea04ffa7463…` |
| PIECE-0031 | [PIECE-0031.pdf](../../demo/pieces/PIECE-0031.pdf) | register_of_directors | `afa8539106b190b1…` |
| PIECE-0032 | [PIECE-0032.pdf](../../demo/pieces/PIECE-0032.pdf) | certificate_of_incorporation | `96138c21b472d77a…` |
| PIECE-0033 | [PIECE-0033.png](../../demo/pieces/PIECE-0033.png) | bank_statement | `99d4f6b7d1015637…` |
| PIECE-0034 | [PIECE-0034.png](../../demo/pieces/PIECE-0034.png) | register_of_directors | `12f052748bb5a09f…` |
| PIECE-0035 | [PIECE-0035.png](../../demo/pieces/PIECE-0035.png) | register_of_directors | `c17e1594113a5116…` |
| PIECE-0036 | [PIECE-0036.png](../../demo/pieces/PIECE-0036.png) | certificate_of_incorporation | `0a756650f320b25c…` |
| PIECE-0037 | [PIECE-0037.png](../../demo/pieces/PIECE-0037.png) | bank_statement | `dc74964f2df69ace…` |
| PIECE-0038 | [PIECE-0038.png](../../demo/pieces/PIECE-0038.png) | bank_statement | `bf70dd088729db87…` |
| PIECE-0039 | [PIECE-0039.png](../../demo/pieces/PIECE-0039.png) | certificate_of_incorporation | `9213d092d289a97f…` |
| PIECE-0040 | [PIECE-0040.jpg](../../demo/pieces/PIECE-0040.jpg) | certificate_of_incorporation | `8655a1c0608ce0dd…` |
| PIECE-0041 | [PIECE-0041.png](../../demo/pieces/PIECE-0041.png) | register_of_directors | `2d95fea24c32db35…` |
| PIECE-0042 | [PIECE-0042.png](../../demo/pieces/PIECE-0042.png) | register_of_directors | `07121c272cebcee4…` |
| PIECE-0043 | [PIECE-0043.png](../../demo/pieces/PIECE-0043.png) | certificate_of_incorporation | `c0f22e358f5e337a…` |
| PIECE-0044 | [PIECE-0044.jpg](../../demo/pieces/PIECE-0044.jpg) | invoice | `b7e7d5cd4434b538…` |
| PIECE-0045 | [PIECE-0045.pdf](../../demo/pieces/PIECE-0045.pdf) | invoice | `a41a2a2e198b218c…` |
| PIECE-0046 | [PIECE-0046.pdf](../../demo/pieces/PIECE-0046.pdf) | invoice | `a53c0a55535aa9b9…` |
| PIECE-0047 | [PIECE-0047.pdf](../../demo/pieces/PIECE-0047.pdf) | invoice | `bab7cab68d59ead1…` |
| PIECE-0048 | [PIECE-0048.png](../../demo/pieces/PIECE-0048.png) | invoice | `64505542f148c377…` |
| PIECE-0049 | [PIECE-0049.jpg](../../demo/pieces/PIECE-0049.jpg) | invoice | `8b8b3f960bbe47f3…` |
| PIECE-0050 | [PIECE-0050.pdf](../../demo/pieces/PIECE-0050.pdf) | invoice | `4cba9ad940e2cbcd…` |

### 5.3. Paramètres de détection

- Longueur des cycles : 2 à 8
- Tolérance de conservation du montant par étape : 15 %
- Seuil de fractionnement : 10 000 USD par virement ; au moins 5 relais en 7 jours
- Cycles écartés (conservation ou chronologie non respectées) : 0

### 5.4. Métriques d'exécution et télémétrie

- **Temps d'extraction / lecture** : 0.58 s
- **Temps de construction & détection graphe** : 0.12 s
- **Temps de qualification juridique** : 0.0 s
- **Durée totale d'investigation** : 0.7 s
- **Détails de l'analyse déterministe** : liaison `115.35 ms`, détection topologique `4.22 ms`, constats `0.47 ms`
- **Pic de mémoire vive (analyse)** : `0.24 Mo`
