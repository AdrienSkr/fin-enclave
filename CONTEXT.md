# 📖 CONTEXT.md — Modèle de Domaine, Verrous & Invariants FinEnclave

Ce document constitue la **source unique de vérité (Single Source of Truth)** sémantique, juridique et architecturale pour le module `fin-enclave/`. Tout agent intervenant sur le code, les prompts ou les algorithmes doit s'aligner sur les définitions, verrous et invariants décrits ci-dessous.

---

## 🎯 1. Le "Pourquoi" : Le Verrou Juridique & Technologique 2026

### A. L'Interdiction Pénale Absolue du Cloud Public
Dans les enquêtes pour blanchiment de capitaux, fraude fiscale internationale et corruption d'agents publics :
1. **Secret Bancaire Pénal (Art. L. 511-33 du Code monétaire et financier) :**
   La révélation d'une information couverte par le secret bancaire est punie d'un an d'emprisonnement et de 15 000 € d'amende, assortie de sanctions disciplinaires ACPR pouvant atteindre **100 millions d'euros**.
2. **Secret de l'Instruction (Art. 11 du Code de procédure pénale) :**
   Toute personne concourant à la procédure judiciaire est tenue au secret. La transmission de pièces de procédure à un fournisseur cloud tiers constitue une violation directe de ce serment.
3. **Risque de Nullité Procédurale (Art. 170 du CPP) :**
   Sous l'empire du **US CLOUD Act** et de la section 702 du **FISA**, les données traitées par des acteurs sous juridiction américaine sont susceptibles d'interception étrangère, rendant les preuves judiciairement inopposables ou nulles devant le tribunal correctionnel ou la cour d'assises.

### B. L'Échec Systémique du "RAG Naïf" (Vector Search & Cosine Similarity)
* Les réseaux criminels masquent les bénéficiaires effectifs derrière des cascades de 5 à 12 sociétés écrans réparties entre plusieurs paradis fiscaux (Panama, BVI, Chypre, Belize).
* Un système de RAG conventionnel (Vector Database + Cosine Similarity) est **aveugle aux topologies criminelles** : il recherche des proximités sémantiques ou lexicales là où la fraude repose sur des circuits cycliques fermés sans parenté de vocabulaire.
* **FinEnclave inverse le paradigme :** Approche *Graph-First déterministe* (topologie mathématique irréfutable) couplée à un *moteur de raisonnement sémantique local* sous contrainte de schéma.

### C. La Synergie Matérielle Unique : ASUS Ascent GX10
Le matériel cible (ASUS Ascent GX10 propulsé par la puce NVIDIA Grace Blackwell GB10) résout le compromis puissance / confidentialité :
* **Mémoire unifiée 128 Go LPDDR5x (273 Go/s) :** Permet de stocker simultanément en RAM le graphe complet des flux financiers (500 000 arêtes) et les poids d'un grand modèle de vision (Qwen3-VL-235B-A22B, ≈ 120 Go en 4 bits) qu'aucune carte RTX grand public ne peut charger.
* **Bus NVLink-C2C à 900 Go/s :** Le CPU Arm Neoverse V2 et le GPU Blackwell partagent le même espace d'adressage sans latence PCIe. Les sous-graphes détectés par le CPU sont interrogés par le GPU à la vitesse de la mémoire vive.
* **Format Desktop Silencieux (240W) :** Déployable directement sur le bureau d'un magistrat instructeur ou d'un officier du PNF, sans dépendance réseau.

---

## 🏛️ 2. Le "Quoi" : Modèle de Domaine & Typologies d'Infraction

### A. Les Entités Financières du Domaine
* **PersonnePhysique :** Individu (bénéficiaire effectif, prête-nom, mandataire social).
* **Societe :** Personne morale (société d'exploitation, holding, coquille offshore, SPV).
* **Intermediaire :** Cabinet d'avocats fiduciaires, banques gestionnaires, agents domiciliataires (ex. Mossack Fonseca).
* **CompteBancaire :** Nœud de routage des fonds identifié par IBAN, code SWIFT/BIC ou devise.

### B. Typologies d'Infractions Pénales Qualifiées
1. **BLANCHIMENT_CYCLE_FERME (Art. 324-1 & 324-2 Code Pénal) :**
   Opération de recyclage financier où les fonds quittent une entité d'origine, transitent par une série de prête-noms et reviennent sous forme d'investissements licites à leur initiateur direct ou indirect.
2. **CARROUSEL_TVA (Art. 1741 Code Général des Impôts) :**
   Circuit de refacturation circulaire transfrontalière exploitant le régime intracommunautaire d'exonération de TVA pour détourner des crédits d'impôt.
3. **DISSIMULATION_UBO_PRETE_NOM (Recommandations GAFI 24/25, Art. L. 561-46 CMF) :**
   Fragmentation délibérée du capital social et recours à des trusts ou actions au porteur pour maintenir l'actionnaire réel sous le seuil légal de déclaration (25 % des parts ou droits de vote).
4. **BACK_TO_BACK_LOAN :**
   Montage où des fonds illicites déposés dans une banque offshore garantissent un prêt bancaire légitime octroyé à une société nationale.
5. **SURFACTURATION_OFFSHORE :**
   Émission de fausses factures de conseil ou propriété intellectuelle vers une juridiction à fiscalité privilégiée pour siphonner les marges bénéficiaires.

---

## ⚙️ 3. Le "Comment" : Les 4 Étages du Pipeline FinEnclave

```text
[Pièces Brutes CSV/JSON/PDF]
            │
            ▼
┌────────────────────────────────────────────────────────┐
│ ÉTAGE 1 : Record Linkage Jaro-Winkler (Déterministe)   │
│ • Rapprochement flou des alias de prête-noms           │
│ • Seuil d'admissibilité par défaut : score >= 0.88     │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ ÉTAGE 2 : Théorie des Graphes Déterministe (CPU Arm)   │
│ • Algorithme de Tarjan : Composantes Fortement         │
│   Connexes (SCC) en O(V + E)                           │
│ • Algorithme de Johnson borné : Cycles fermés de flux  │
│ • Centralité d'Intermédiarité de Brandes : Nœud pivot  │
└───────────────────────────┬────────────────────────────┘
                            │ (Transfert Zéro-Copie NVLink-C2C)
                            ▼
┌────────────────────────────────────────────────────────┐
│ ÉTAGE 3 : Qualification Pénale par LLM (GPU Blackwell) │
│ • Inférence locale contrainte par Pydantic v2          │
│ • Application stricte des textes de loi (Art. 324-1 CP)│
│ • Fallback automatique sur moteur de règles certifié   │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│ ÉTAGE 4 : Scellé Cryptographique & Visualisation 3D    │
│ • Conformité ISO/IEC 27037 (Hash SHA-256 + Cote)       │
│ • Dashboard HTML Dark-Mode interactif (vis-network)    │
│ • Livrables judiciaires en JSON et Markdown scellés    │
└────────────────────────────────────────────────────────┘
```

---

## 📖 4. Vocabulaire Canonique (Ubiquitous Language)

Pour maintenir l'intégrité du code, des tests et des prompts, utilisez **strictement** ces termes sans dérive synonymique :

| Terme Canonique | Définition & Rôle dans le Projet |
| :--- | :--- |
| **UBO (*Ultimate Beneficial Owner*)** | Bénéficiaire effectif ultime qui contrôle en dernier ressort une personne morale ou une fiducie. |
| **Composante Fortement Connexe (SCC)** | Sous-graphe orienté maximal au sein duquel chaque sommet peut atteindre tous les autres. Calculé via l'algorithme de Tarjan. |
| **Cycle Fermé de Blanchiment** | Suite ordonnée de transactions orientées dont le sommet de départ coïncide avec le sommet d'arrivée ($A \to B \to C \to A$). |
| **Nœud Pivot** | Sommet possédant la plus forte centralité d'intermédiarité (Brandes). Il représente le goulot d'étranglement ou l'intermédiaire fiduciaire névralgique du réseau. |
| **Record Linkage** | Procédé déterministe de fusion d'alias textuels (ex. variantes typographiques de cabinets) avant l'injection dans le graphe. |
| **Entité Canonique** | Le nom normalisé d'un groupe d'alias fusionnés (ex. `Mossack Fonseca & Co.`). |
| **Scellé Numérique (ProofPoint)** | Objet cryptographique associant un hachage SHA-256, une cote de procédure et une date RFC 3161 à chaque élément de preuve. |
| **Chaîne de Preuve (*Chain of Custody*)** | Piste d'audit inviolable garantissant qu'aucune preuve n'a été altérée ou inventée entre la saisie et le tribunal (ISO/IEC 27037). |

---

## ⚖️ 5. Invariants Métier & Règles de Décision Non Négociables

1. **Pas de fusion d'entités sous le seuil d'admissibilité :**
   Deux raisons sociales ne doivent jamais être fusionnées si leur similarité Jaro-Winkler est inférieure à `0.88`, sauf instruction manuelle explicite (`ground_truth`).
2. **Primauté de la topologie sur le texte :**
   Un circuit de blanchiment n'est jamais qualifié si le graphe n'a pas formellement identifié un cycle fermé orienté ou une SCC non triviale (taille $\ge 2$).
3. **Inviolabilité de la preuve ISO/IEC 27037 :**
   Chaque fait présenté dans `AnomalyReport` doit impérativement provenir du `proof_ledger` et référencer une cote de procédure valide. Les hallucinations sont bloquées par la validation stricte Pydantic.
4. **Résilience et Mode Dégradé :**
   Si le backend LLM (`local_gx10` ou distant) est injoignable, le pipeline doit basculer de manière transparente sur le fallback heuristique certifié (`_heuristic_fallback_qualification`) sans interrompre la génération des livrables judiciaires.
