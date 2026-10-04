import re
from typing import NamedTuple


class MergeResult(NamedTuple):
    original_id: str
    original_name: str
    canonical_id: str
    canonical_name: str
    score: float


def jaro_distance(s1: str, s2: str) -> float:
    """Calcul de la distance de Jaro entre deux chaînes."""
    if not s1 and not s2:
        return 1.0
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0

    len1, len2 = len(s1), len(s2)
    match_distance = max(len1, len2) // 2 - 1
    match_distance = max(match_distance, 0)

    s1_matches = [False] * len1
    s2_matches = [False] * len2

    matches = 0
    for i, c1 in enumerate(s1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if not s2_matches[j] and c1 == s2[j]:
                s1_matches[i] = True
                s2_matches[j] = True
                matches += 1
                break

    if matches == 0:
        return 0.0

    # Comptage des transpositions
    k = 0
    transpositions = 0
    for i, m1 in enumerate(s1_matches):
        if m1:
            while not s2_matches[k]:
                k += 1
            if s1[i] != s2[k]:
                transpositions += 1
            k += 1

    t = transpositions // 2
    return (matches / len1 + matches / len2 + (matches - t) / matches) / 3.0


def jaro_winkler_similarity(s1: str, s2: str, p: float = 0.1, max_prefix: int = 4) -> float:
    """
    Similarité de Jaro-Winkler optimisée pour les noms propres et raisons sociales.
    Accorde un bonus pour les préfixes communs.
    """
    dj = jaro_distance(s1, s2)
    if dj < 0.7:
        return dj

    prefix = 0
    for c1, c2 in zip(s1[:max_prefix], s2[:max_prefix]):
        if c1 == c2:
            prefix += 1
        else:
            break

    return dj + prefix * p * (1.0 - dj)


def normalize_entity_name(name: str) -> str:
    """
    Nettoie et normalise une raison sociale pour le rapprochement d'entités (Record Linkage).
    Supprime la ponctuation, les formes juridiques courantes et les espaces superflus.
    """
    s = name.upper()
    # Remplacement des caractères spéciaux
    s = re.sub(r"[.,\-&/()\"']", " ", s)
    # Suppression des formes juridiques et stopwords corporatifs
    noise_tokens = {
        "LTD",
        "LIMITED",
        "INC",
        "INCORPORATED",
        "CORP",
        "CORPORATION",
        "SA",
        "S A",
        "LLC",
        "LLP",
        "PARTNERS",
        "HOLDINGS",
        "GROUP",
        "CO",
        "COMPANY",
        "BVI",
        "B V I",
    }
    tokens = [t for t in s.split() if t not in noise_tokens]
    return " ".join(tokens)


def _numeric_tokens(norm_name: str) -> frozenset[str]:
    return frozenset(t for t in norm_name.split() if any(c.isdigit() for c in t))


class EntityResolver:
    """
    Moteur déterministe de résolution d'entités (Record Linkage).
    Fusionne les prête-noms et sociétés écrans fractionnés par variations orthographiques.
    """

    def __init__(
        self,
        threshold: float = 0.85,
        never_merge: list[tuple[str, str]] | None = None,
    ):
        self.threshold = threshold
        # Paires d'identifiants à ne jamais fusionner (ex : agences bancaires distinctes)
        self.never_merge: set[frozenset[str]] = {frozenset(p) for p in (never_merge or [])}
        self.id_to_canonical: dict[str, str] = {}
        self.name_to_canonical: dict[str, str] = {}
        self.merge_history: list[MergeResult] = []

    def fit_resolve(self, entities: list[dict[str, str]]) -> dict[str, str]:
        """
        Analyse une liste de dictionnaires d'entités {'id', 'name', 'country', 'type'}
        et construit une cartographie vers l'identifiant canonique.
        """
        # Pré-regroupement (blocking) : seules les entités de même type et de même préfixe
        # normalisé sont comparées ; la normalisation est calculée une seule fois par entité.
        blocks: dict[tuple[str, str], list[tuple[dict[str, str], str]]] = {}

        for ent in entities:
            ent_id = ent["id"]
            ent_name = ent["name"]
            norm_name = normalize_entity_name(ent_name)
            block_key = (ent.get("type", ""), norm_name[:3])

            best_match = None
            best_score = 0.0

            for canon, canon_norm in blocks.get(block_key, []):
                if frozenset((canon["id"], ent_id)) in self.never_merge:
                    continue
                # Numéros différents (« Holding 1 » / « Holding 2 ») : entités distinctes
                if _numeric_tokens(norm_name) != _numeric_tokens(canon_norm):
                    continue
                score = jaro_winkler_similarity(norm_name, canon_norm)

                # Priorité si même type d'entité et score au-dessus du seuil
                if score >= self.threshold and score > best_score:
                    best_match = canon
                    best_score = score

            if best_match:
                # Alias identifié -> on fusionne avec le canonique existant
                canon_id = best_match["id"]
                canon_name = best_match["name"]
                self.id_to_canonical[ent_id] = canon_id
                self.name_to_canonical[ent_name] = canon_name
                self.merge_history.append(
                    MergeResult(
                        original_id=ent_id,
                        original_name=ent_name,
                        canonical_id=canon_id,
                        canonical_name=canon_name,
                        score=round(best_score, 3),
                    )
                )
            else:
                # Nouvelle entité canonique
                blocks.setdefault(block_key, []).append((ent, norm_name))
                self.id_to_canonical[ent_id] = ent_id
                self.name_to_canonical[ent_name] = ent_name

        return self.id_to_canonical

    def resolve_id(self, entity_id: str) -> str:
        """Retourne l'ID canonique d'une entité après résolution."""
        return self.id_to_canonical.get(entity_id, entity_id)

    def resolve_name(self, entity_name: str) -> str:
        """Retourne le nom canonique d'une entité après résolution."""
        return self.name_to_canonical.get(entity_name, entity_name)
