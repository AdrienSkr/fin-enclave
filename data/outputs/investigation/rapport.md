# Rapport d'investigation : dossier de pièces

- **Dossier** : `data/demo/realiste` (42 pièces, 0 en échec)
- **Lecture des pièces** : `vlm-qwen-qwen3-vl-235b-a22b-instruct-p3279f0cb`
- **Généré le** : 2026-10-04 19:50 UTC, en local
- **Méthode** : les liens et les anomalies sont trouvés par des algorithmes déterministes (résolution de noms, Tarjan, Johnson, Brandes) ; le modèle de langage ne fait que lire les pièces et, en option, rédiger les notes. Chaque fait renvoie à ses pièces.

> **Données.** Les sociétés, dirigeants et intermédiaires proviennent d'un vrai réseau des Panama Papers (base ICIJ Offshore Leaks, licence ODbL). Les virements, relevés, procurations et le bénéficiaire caché sont **simulés** pour la démonstration (la base ICIJ ne contient aucun montant). Aucun fait n'est imputé aux sociétés réelles citées.

## 1. Synthèse Judiciaire : Infractions & Constats Clés

> **Cadrage de l'enquête :** Ce rapport distingue rigoureusement deux niveaux :
> 1. **Les infractions délictueuses caractérisées** : circuits fermés de blanchiment et dissimulations d'UBO.
> 2. **La cartographie globale du réseau saisi** : l'organigramme de toutes les sociétés gérées et les soldes bancaires cumulés de tous les comptes saisis.

- **Prête-nom central du réseau** : Oakridge Enterprises Limited est inscrit dans les registres de **11 sociétés** du dossier (profil de prête-nom professionnel).
- **Prête-nom central du réseau** : Sigrid Castille est inscrit dans les registres de **4 sociétés** du dossier (profil de prête-nom professionnel).
- **Circuit fermé de blanchiment** : Ironwood Holdings Limited → Mistvale Partners Limited → Ironwood Holdings Limited, 19 529 USD injectés, 16 607 USD revenus. *(Ces sociétés sont toutes deux administrées par le prête-nom central).*
- **Destination globale des fonds** : Mistvale Enterprises Ltd., solde net créditeur de **98 001 USD** sur l'ensemble des flux du dossier ([PIECE-0032](../../demo/realiste/PIECE-0032.png), [PIECE-0034](../../demo/realiste/PIECE-0034.pdf)).

## 2. Organigramme des Sociétés Saisies (Qui détient / dirige quoi)

> Tableau exhaustif des structures juridiques saisies dans le dossier.

| Société | Inscrits au registre | Procuration | Agent | Pièces |
| :--- | :--- | :--- | :--- | :--- |
| Amberfield Partners Ltd. | Oakridge Enterprises Limited (actionnaire) | — | Coral Fiduciary Services Ltd. | [PIECE-0001](../../demo/realiste/PIECE-0001.png), [PIECE-0021](../../demo/realiste/PIECE-0021.pdf), [PIECE-0024](../../demo/realiste/PIECE-0024.png), [PIECE-0025](../../demo/realiste/PIECE-0025.png), [PIECE-0028](../../demo/realiste/PIECE-0028.jpg), [PIECE-0039](../../demo/realiste/PIECE-0039.png) |
| Ashcroft Enterprises Limited | Oakridge Enterprises Limited (actionnaire) | — | Coral Fiduciary Services Ltd. | [PIECE-0016](../../demo/realiste/PIECE-0016.pdf), [PIECE-0019](../../demo/realiste/PIECE-0019.png), [PIECE-0032](../../demo/realiste/PIECE-0032.png), [PIECE-0042](../../demo/realiste/PIECE-0042.jpg) |
| Fairhaven Holdings Inc. | Oakridge Enterprises Limited (actionnaire)<br>Glenbrook Trading Corp. (actionnaire)<br>Seaglass Investments S.A. (actionnaire)<br>Stonehaven Trading Inc. (actionnaire) | — | Coral Fiduciary Services Ltd. | [PIECE-0003](../../demo/realiste/PIECE-0003.png), [PIECE-0019](../../demo/realiste/PIECE-0019.png), [PIECE-0020](../../demo/realiste/PIECE-0020.png), [PIECE-0023](../../demo/realiste/PIECE-0023.png), [PIECE-0032](../../demo/realiste/PIECE-0032.png), [PIECE-0034](../../demo/realiste/PIECE-0034.pdf) |
| Ironwood Holdings Limited | Oakridge Enterprises Limited (actionnaire) | — | Coral Fiduciary Services Ltd. | [PIECE-0005](../../demo/realiste/PIECE-0005.jpg), [PIECE-0014](../../demo/realiste/PIECE-0014.png), [PIECE-0026](../../demo/realiste/PIECE-0026.pdf), [PIECE-0031](../../demo/realiste/PIECE-0031.pdf), [PIECE-0033](../../demo/realiste/PIECE-0033.pdf) |
| Ironwood Ventures S.A. | Oakridge Enterprises Limited (actionnaire)<br>Quentin Reynaud (actionnaire)<br>Priya Castille (actionnaire)<br>Sigrid Castille (bénéficiaire effectif) | — | Coral Fiduciary Services Ltd. | [PIECE-0008](../../demo/realiste/PIECE-0008.pdf), [PIECE-0009](../../demo/realiste/PIECE-0009.jpg), [PIECE-0024](../../demo/realiste/PIECE-0024.png), [PIECE-0029](../../demo/realiste/PIECE-0029.png), [PIECE-0039](../../demo/realiste/PIECE-0039.png) |
| Mistvale Enterprises Ltd. | Oakridge Enterprises Limited (actionnaire)<br>Sigrid Castille (bénéficiaire effectif) | — | Coral Fiduciary Services Ltd. | [PIECE-0015](../../demo/realiste/PIECE-0015.png), [PIECE-0032](../../demo/realiste/PIECE-0032.png), [PIECE-0034](../../demo/realiste/PIECE-0034.pdf), [PIECE-0037](../../demo/realiste/PIECE-0037.png) |
| Mistvale Partners Limited | Oakridge Enterprises Limited (actionnaire) | — | Coral Fiduciary Services Ltd. | [PIECE-0010](../../demo/realiste/PIECE-0010.jpg), [PIECE-0012](../../demo/realiste/PIECE-0012.pdf), [PIECE-0014](../../demo/realiste/PIECE-0014.png), [PIECE-0031](../../demo/realiste/PIECE-0031.pdf), [PIECE-0033](../../demo/realiste/PIECE-0033.pdf) |
| Northwind Assets Corp. | Oakridge Enterprises Limited (actionnaire)<br>Sigrid Castille (bénéficiaire effectif) | — | Coral Fiduciary Services Ltd. | [PIECE-0014](../../demo/realiste/PIECE-0014.png), [PIECE-0030](../../demo/realiste/PIECE-0030.png), [PIECE-0031](../../demo/realiste/PIECE-0031.pdf), [PIECE-0033](../../demo/realiste/PIECE-0033.pdf), [PIECE-0036](../../demo/realiste/PIECE-0036.jpg) |
| Seaglass Group Limited | Oakridge Enterprises Limited (actionnaire)<br>Clara Holmgren (bénéficiaire effectif)<br>Oakridge Management Corp. (actionnaire) | — | Atlas Nominees Bureau Ltd.<br>Coral Fiduciary Services Ltd. | [PIECE-0008](../../demo/realiste/PIECE-0008.pdf), [PIECE-0011](../../demo/realiste/PIECE-0011.pdf), [PIECE-0018](../../demo/realiste/PIECE-0018.pdf), [PIECE-0021](../../demo/realiste/PIECE-0021.pdf), [PIECE-0025](../../demo/realiste/PIECE-0025.png), [PIECE-0035](../../demo/realiste/PIECE-0035.png), [PIECE-0039](../../demo/realiste/PIECE-0039.png), [PIECE-0041](../../demo/realiste/PIECE-0041.pdf) |
| Stonehaven Trading Inc. | Oakridge Enterprises Limited (actionnaire)<br>Dimitri Lindholm (bénéficiaire effectif) | — | Coral Fiduciary Services Ltd. | [PIECE-0002](../../demo/realiste/PIECE-0002.png), [PIECE-0020](../../demo/realiste/PIECE-0020.png), [PIECE-0022](../../demo/realiste/PIECE-0022.pdf), [PIECE-0023](../../demo/realiste/PIECE-0023.png), [PIECE-0032](../../demo/realiste/PIECE-0032.png) |
| Willowmere Management Limited | Oakridge Enterprises Limited (actionnaire)<br>Sigrid Castille (bénéficiaire effectif) | — | Coral Fiduciary Services Ltd. | [PIECE-0006](../../demo/realiste/PIECE-0006.jpg), [PIECE-0008](../../demo/realiste/PIECE-0008.pdf), [PIECE-0021](../../demo/realiste/PIECE-0021.pdf), [PIECE-0024](../../demo/realiste/PIECE-0024.png), [PIECE-0025](../../demo/realiste/PIECE-0025.png), [PIECE-0040](../../demo/realiste/PIECE-0040.jpg) |

## 3. Prête-noms & Centralité du Réseau Saisi (Qui est au centre)

> Identification des prête-noms institutionnels gérant des sociétés en cascade pour des tiers. Par exemple, *Oakridge Enterprises Limited* administre 11 sociétés, y compris celles impliquées dans les flux du circuit fermé.

| Acteur | Sociétés | Rôles | Profil |
| :--- | ---: | :--- | :--- |
| Oakridge Enterprises Limited | 11 | actionnaire ×11 | prête-nom présumé |
| Sigrid Castille | 4 | bénéficiaire effectif ×4 | prête-nom présumé |
| Clara Holmgren | 1 | bénéficiaire effectif ×1 |  |
| Dimitri Lindholm | 1 | bénéficiaire effectif ×1 |  |
| Glenbrook Trading Corp. | 1 | actionnaire ×1 |  |
| Oakridge Management Corp. | 1 | actionnaire ×1 |  |
| Priya Castille | 1 | actionnaire ×1 |  |
| Quentin Reynaud | 1 | actionnaire ×1 |  |

Seuil du profil de prête-nom : inscrit dans au moins 4 sociétés du dossier.
Sommet le plus central du graphe (Brandes) : **Fairhaven Holdings Inc.** (intermédiarité 0.1219).

## 4. Destination Globale des Fonds (Comptabilité de tous les comptes saisis)

Bilan net cumulé sur l'ensemble des 107 virements découverts dans le dossier (1 091 276 USD au total). Ce tableau montre où s'accumule la liquidité in fine sur l'ensemble des comptes étudiés, au-delà du seul circuit délictueux.

| Acteur | Reçu | Envoyé | Solde net | Pièces |
| :--- | ---: | ---: | ---: | :--- |
| Mistvale Enterprises Ltd. | 122 101 USD | 24 100 USD | **98 001 USD** | [PIECE-0032](../../demo/realiste/PIECE-0032.png), [PIECE-0034](../../demo/realiste/PIECE-0034.pdf) |
| Ironwood Holdings Limited | 143 791 USD | 64 297 USD | **79 495 USD** | [PIECE-0014](../../demo/realiste/PIECE-0014.png), [PIECE-0031](../../demo/realiste/PIECE-0031.pdf), [PIECE-0033](../../demo/realiste/PIECE-0033.pdf) |
| Redwood Telecom Inc | 31 104 USD | 0 USD | **31 104 USD** | [PIECE-0014](../../demo/realiste/PIECE-0014.png), [PIECE-0021](../../demo/realiste/PIECE-0021.pdf) |
| Seaglass Group Limited | 76 656 USD | 48 397 USD | **28 259 USD** | [PIECE-0021](../../demo/realiste/PIECE-0021.pdf), [PIECE-0025](../../demo/realiste/PIECE-0025.png), [PIECE-0039](../../demo/realiste/PIECE-0039.png) |
| Amberfield Partners Ltd. | 46 981 USD | 26 080 USD | **20 901 USD** | [PIECE-0021](../../demo/realiste/PIECE-0021.pdf), [PIECE-0024](../../demo/realiste/PIECE-0024.png), [PIECE-0025](../../demo/realiste/PIECE-0025.png), [PIECE-0039](../../demo/realiste/PIECE-0039.png) |
| Summit Cleaning Ltd | 20 066 USD | 0 USD | **20 066 USD** | [PIECE-0024](../../demo/realiste/PIECE-0024.png), [PIECE-0025](../../demo/realiste/PIECE-0025.png), [PIECE-0032](../../demo/realiste/PIECE-0032.png) |
| Crescent Cleaning Inc | 20 510 USD | 1 075 USD | **19 436 USD** | [PIECE-0019](../../demo/realiste/PIECE-0019.png), [PIECE-0025](../../demo/realiste/PIECE-0025.png), [PIECE-0031](../../demo/realiste/PIECE-0031.pdf), [PIECE-0034](../../demo/realiste/PIECE-0034.pdf) |
| Pinewood Couriers Ltd | 18 886 USD | 0 USD | **18 886 USD** | [PIECE-0023](../../demo/realiste/PIECE-0023.png), [PIECE-0032](../../demo/realiste/PIECE-0032.png) |
| Adrian Ortega | 17 563 USD | 0 USD | **17 563 USD** | [PIECE-0032](../../demo/realiste/PIECE-0032.png) |
| Paper Court | 16 798 USD | 0 USD | **16 798 USD** | [PIECE-0021](../../demo/realiste/PIECE-0021.pdf), [PIECE-0033](../../demo/realiste/PIECE-0033.pdf) |

**Circuit fermé** (2 sociétés) :

1. 2022-09-06 : Ironwood Holdings Limited → Mistvale Partners Limited, **19 529 USD** ([PIECE-0033](../../demo/realiste/PIECE-0033.pdf))
1. 2022-09-06 : Mistvale Partners Limited → Ironwood Holdings Limited, **16 607 USD** ([PIECE-0014](../../demo/realiste/PIECE-0014.png))

## 5. Qualifications envisagées

### 5.1. Circuit fermé (round-tripping)

> Circuit fermé de 2 sociétés : Ironwood Holdings Limited -> Mistvale Partners Limited -> Ironwood Holdings Limited. 19,529 USD sortent de Ironwood Holdings Limited le 2022-09-06 et 16,607 USD y reviennent le 2022-09-06 (écart 15.0 %, au plus 15.0 % par étape). Pièces : PIECE-0014, PIECE-0033.

- Montant en cause : **19 529 USD**
- Corroboration par l'OCR témoin : **100%** des noms et montants cités
- Rédaction de la note : deterministe
- Fondements à examiner : Art. 324-1 du Code pénal : blanchiment (dissimulation de l'origine des fonds) ; Art. L. 561-15 du Code monétaire et financier : déclaration de soupçon (TRACFIN)
- Actions proposées : Confronter les pièces citées aux originaux scellés avant toute exploitation ; Requérir les relevés complets des comptes du circuit sur la période ; Si confirmé : déclaration de soupçon (Art. L. 561-15 CMF)

### 5.2. Bénéficiaire caché derrière un prête-nom

> Oakridge Enterprises Limited est inscrit comme administrateur ou actionnaire de 11 sociétés du dossier (seuil prête-nom : 4). Absence de bénéficiaire effectif personne physique identifié pour ces entités. Profil de prête-nom institutionnel présumé aux fins de dissimulation d'avoirs. Pièces : PIECE-0001, PIECE-0002, PIECE-0005, PIECE-0011, PIECE-0012, PIECE-0016.

- Montant en cause : **0 USD**
- Corroboration par l'OCR témoin : **100%** des noms et montants cités
- Rédaction de la note : deterministe
- Fondements à examiner : Art. L. 561-2-2 du Code monétaire et financier : définition du bénéficiaire effectif ; Recommandation 24 du GAFI : transparence des bénéficiaires effectifs des personnes morales ; Art. 324-1 du Code pénal : blanchiment, si l'origine des fonds est établie
- Actions proposées : Requérir le registre des bénéficiaires effectifs (RBE) pour chaque société administrée ; Confronter la structure aux déclarations fiscales et bancaires de l'administrateur ; Vérifier l'absence de convention de prête-nom occulte (nominee agreement)


## 6. À valider par l'enquêteur

- Pièces non lues : 0
- Entités écartées (absentes de la lecture OCR témoin) : 7 : Redwood Telecom (PIECE-0021), Paper Court (PIECE-0021), Coral Fiduciary Services Ltd. (PIECE-0028), Redwood County Ltd (PIECE-0034), Redwood4900,00Ltd (PIECE-0039), Bluefin Catering Ltd 5.175,00 (PIECE-0039), Crescent Courier5.125,00 (PIECE-0039)
- Entités non vérifiables (pièce illisible pour l'OCR témoin) : 3
- Montants non corroborés par l'OCR témoin : 17
- Virements sans date lisible : 0
- Variantes de noms fusionnées : 52 : Seaglass Holdings Inc. = Seaglass Group Limited; Harbour Cleaning Ltd = Harbour Catering Ltd; Paper Catering Ltd = Paper Cleaning Ltd; Seaglass Holdings Inc. = Seaglass Group Limited; Crescent Cleaning Ltd = Crescent Cleaning Inc; Crescent Catering Ltd = Crescent Cleaning Inc

## 7. Fiabilité mesurée sur ce dossier (vérité terrain connue)

| Mesure | Précision | Rappel |
| :--- | ---: | ---: |
| Entités lues | 0.91 | 0.97 |
| Liens de détention / contrôle lus | 1.00 | 1.00 |
| Virements lus | 0.18 | 0.16 |
| Liens du graphe reconstruit | 1.00 | 0.97 |
| Flux du graphe reconstruit | 0.19 | 0.16 |

- Circuit caché retrouvé : **non** (faux circuits : 1)
- Fractionnement retrouvé : **non** (0/0 relais)
- Bénéficiaire caché retrouvé : **non**

## 8. Chaîne de preuve

| Cote | Fichier | Nature lue | SHA-256 |
| :--- | :--- | :--- | :--- |
| PIECE-0001 | [PIECE-0001.png](../../demo/realiste/PIECE-0001.png) | register_of_directors | `15ad2b86283ec27b…` |
| PIECE-0002 | [PIECE-0002.png](../../demo/realiste/PIECE-0002.png) | register_of_directors | `1008b90a02e7e99f…` |
| PIECE-0003 | [PIECE-0003.png](../../demo/realiste/PIECE-0003.png) | certificate_of_incorporation | `e88bddda428f6e02…` |
| PIECE-0004 | [PIECE-0004.jpg](../../demo/realiste/PIECE-0004.jpg) | invoice | `11b539c0590a79c8…` |
| PIECE-0005 | [PIECE-0005.jpg](../../demo/realiste/PIECE-0005.jpg) | register_of_directors | `f3f305d00b6bf933…` |
| PIECE-0006 | [PIECE-0006.jpg](../../demo/realiste/PIECE-0006.jpg) | certificate_of_incorporation | `c32f93e83813a19f…` |
| PIECE-0007 | [PIECE-0007.png](../../demo/realiste/PIECE-0007.png) | invoice | `3c5a6e55bdaefb7d…` |
| PIECE-0008 | [PIECE-0008.pdf](../../demo/realiste/PIECE-0008.pdf) | bank_statement | `f02ec49620f995d4…` |
| PIECE-0009 | [PIECE-0009.jpg](../../demo/realiste/PIECE-0009.jpg) | certificate_of_incorporation | `7f39927536c07ab1…` |
| PIECE-0010 | [PIECE-0010.jpg](../../demo/realiste/PIECE-0010.jpg) | certificate_of_incorporation | `281cd39e3839a3a9…` |
| PIECE-0011 | [PIECE-0011.pdf](../../demo/realiste/PIECE-0011.pdf) | register_of_directors | `b04d7c55453232be…` |
| PIECE-0012 | [PIECE-0012.pdf](../../demo/realiste/PIECE-0012.pdf) | register_of_directors | `2849e94a6f09abb6…` |
| PIECE-0013 | [PIECE-0013.jpg](../../demo/realiste/PIECE-0013.jpg) | invoice | `b5141cea654e7bd6…` |
| PIECE-0014 | [PIECE-0014.png](../../demo/realiste/PIECE-0014.png) | bank_statement | `de1d22c86307b2af…` |
| PIECE-0015 | [PIECE-0015.png](../../demo/realiste/PIECE-0015.png) | certificate_of_incorporation | `959ab0845411b07b…` |
| PIECE-0016 | [PIECE-0016.pdf](../../demo/realiste/PIECE-0016.pdf) | register_of_directors | `4fbd897e7e4d87fe…` |
| PIECE-0017 | [PIECE-0017.png](../../demo/realiste/PIECE-0017.png) | invoice | `ed6870808b3cf0fd…` |
| PIECE-0018 | [PIECE-0018.pdf](../../demo/realiste/PIECE-0018.pdf) | certificate_of_incorporation | `ba9a232a68f04fdb…` |
| PIECE-0019 | [PIECE-0019.png](../../demo/realiste/PIECE-0019.png) | bank_statement | `165aeab7a8239ea6…` |
| PIECE-0020 | [PIECE-0020.png](../../demo/realiste/PIECE-0020.png) | register_of_directors | `649299cf5ca9c9c3…` |
| PIECE-0021 | [PIECE-0021.pdf](../../demo/realiste/PIECE-0021.pdf) | bank_statement | `c873ca9451614985…` |
| PIECE-0022 | [PIECE-0022.pdf](../../demo/realiste/PIECE-0022.pdf) | certificate_of_incorporation | `07df9fd325455c6f…` |
| PIECE-0023 | [PIECE-0023.png](../../demo/realiste/PIECE-0023.png) | bank_statement | `fefc50d19a3b3aae…` |
| PIECE-0024 | [PIECE-0024.png](../../demo/realiste/PIECE-0024.png) | bank_statement | `7af9af45155779d4…` |
| PIECE-0025 | [PIECE-0025.png](../../demo/realiste/PIECE-0025.png) | bank_statement | `2200a2aff1c44a1a…` |
| PIECE-0026 | [PIECE-0026.pdf](../../demo/realiste/PIECE-0026.pdf) | certificate_of_incorporation | `8b2de79f0a5d1894…` |
| PIECE-0027 | [PIECE-0027.pdf](../../demo/realiste/PIECE-0027.pdf) | invoice | `1a717f131f93237a…` |
| PIECE-0028 | [PIECE-0028.jpg](../../demo/realiste/PIECE-0028.jpg) | certificate_of_incorporation | `0e0c3b6cfe13a013…` |
| PIECE-0029 | [PIECE-0029.png](../../demo/realiste/PIECE-0029.png) | register_of_directors | `e1f1f068452b4fc3…` |
| PIECE-0030 | [PIECE-0030.png](../../demo/realiste/PIECE-0030.png) | register_of_directors | `dca5c13266cb0885…` |
| PIECE-0031 | [PIECE-0031.pdf](../../demo/realiste/PIECE-0031.pdf) | bank_statement | `4e82d89250a1dd47…` |
| PIECE-0032 | [PIECE-0032.png](../../demo/realiste/PIECE-0032.png) | bank_statement | `3c59331b317520e2…` |
| PIECE-0033 | [PIECE-0033.pdf](../../demo/realiste/PIECE-0033.pdf) | bank_statement | `67469dbd2279064c…` |
| PIECE-0034 | [PIECE-0034.pdf](../../demo/realiste/PIECE-0034.pdf) | bank_statement | `6016d31b1be3199d…` |
| PIECE-0035 | [PIECE-0035.png](../../demo/realiste/PIECE-0035.png) | certificate_of_incorporation | `b3c6c19705278efb…` |
| PIECE-0036 | [PIECE-0036.jpg](../../demo/realiste/PIECE-0036.jpg) | certificate_of_incorporation | `ea7b94aaa08905f2…` |
| PIECE-0037 | [PIECE-0037.png](../../demo/realiste/PIECE-0037.png) | register_of_directors | `42340da67178e327…` |
| PIECE-0038 | [PIECE-0038.jpg](../../demo/realiste/PIECE-0038.jpg) | invoice | `25427945fe495306…` |
| PIECE-0039 | [PIECE-0039.png](../../demo/realiste/PIECE-0039.png) | bank_statement | `363cdd15acc02593…` |
| PIECE-0040 | [PIECE-0040.jpg](../../demo/realiste/PIECE-0040.jpg) | register_of_directors | `838e5f760ad62916…` |
| PIECE-0041 | [PIECE-0041.pdf](../../demo/realiste/PIECE-0041.pdf) | register_of_directors | `fdacde1c617effe1…` |
| PIECE-0042 | [PIECE-0042.jpg](../../demo/realiste/PIECE-0042.jpg) | certificate_of_incorporation | `93ad34709fbec192…` |
