import re
from typing import NamedTuple


class MergeResult(NamedTuple):
    original_id: str
    original_name: str
    canonical_id: str
    canonical_name: str
    score: float


def jaro_distance(s1: str | None, s2: str | None) -> float:
    """Calcul de la distance de Jaro entre deux chaînes."""
    s1 = s1 or ""
    s2 = s2 or ""
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


def jaro_winkler_similarity(
    s1: str | None, s2: str | None, p: float = 0.1, max_prefix: int = 4
) -> float:
    """
    Similarité de Jaro-Winkler optimisée pour les noms propres et raisons sociales.
    Accorde un bonus pour les préfixes communs.
    """
    s1 = s1 or ""
    s2 = s2 or ""
    dj = jaro_distance(s1, s2)
    if dj < 0.7:
        return dj

    prefix = 0
    for c1, c2 in zip(s1[:max_prefix], s2[:max_prefix], strict=False):
        if c1 == c2:
            prefix += 1
        else:
            break

    return dj + prefix * p * (1.0 - dj)


def normalize_entity_name(name: str | None) -> str:
    """
    Nettoie et normalise une raison sociale pour le rapprochement d'entités (Record Linkage).
    Supprime la ponctuation, les formes juridiques courantes et les espaces superflus.
    """
    if not name:
        return ""
    s = name.upper()
    s = s.replace(".", "")
    s = re.sub(r"[,/\\()\"'–—\-&]", " ", s)
    noise_tokens = {
        "LTD",
        "LIMITED",
        "INC",
        "INCORPORATED",
        "CORP",
        "CORPORATION",
        "SA",
        "SARL",
        "SAS",
        "SASU",
        "EURL",
        "SCI",
        "LLC",
        "LLP",
        "PLC",
        "PTE",
        "PARTNERS",
        "HOLDINGS",
        "GROUP",
        "CO",
        "COMPANY",
        "BVI",
    }
    tokens = [t for t in s.split() if t not in noise_tokens]
    if not tokens:
        tokens = [t for t in s.split() if t]
    return " ".join(tokens)


class EntityResolver:
    """
    Moteur déterministe de résolution d'entités (Record Linkage).
    Résout les fautes de frappe évidentes (seuil strict >= 0.95) tout en préservant
    les entités distinctes (types différents, entités numérotées).
    """

    def __init__(self, threshold: float = 0.95):
        self.threshold = threshold
        self.id_to_canonical: dict[str, str] = {}
        self.name_to_canonical: dict[str, str] = {}
        self.merge_history: list[MergeResult] = []

    def fit_resolve(self, entities: list[dict[str, str]]) -> dict[str, str]:
        """
        Analyse une liste de dictionnaires d'entités {'id', 'name', 'country', 'type'}
        et construit une cartographie vers l'identifiant canonique.
        """
        blocks: dict[str, list[tuple[dict[str, str], str]]] = {}

        for ent in entities:
            ent_id = ent.get("id") or ""
            ent_name = ent.get("name") or ""
            norm_name = normalize_entity_name(ent_name)
            block_key = ent.get("type") or ""

            if not norm_name:
                self.id_to_canonical[ent_id] = ent_id
                self.name_to_canonical[ent_name] = ent_name
                continue

            best_match = None
            best_score = 0.0
            ent_digits = re.findall(r"\d+", norm_name)

            for canon, canon_norm in blocks.get(block_key, []):
                # Entités numérotées distinctes : ne pas fusionner
                canon_digits = re.findall(r"\d+", canon_norm)
                if ent_digits != canon_digits:
                    continue

                score = jaro_winkler_similarity(norm_name, canon_norm)
                if score >= self.threshold and score > best_score:
                    best_match = canon
                    best_score = score

            if best_match:
                canon_id = best_match.get("id") or ""
                canon_name = best_match.get("name") or ""
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
                blocks.setdefault(block_key, []).append((ent, norm_name))
                self.id_to_canonical[ent_id] = ent_id
                self.name_to_canonical[ent_name] = ent_name

        return self.id_to_canonical

    def resolve_id(self, entity_id: str | None) -> str:
        """Retourne l'ID canonique d'une entité après résolution."""
        if not entity_id:
            return ""
        return self.id_to_canonical.get(entity_id, entity_id)

    def resolve_name(self, entity_name: str | None) -> str:
        """Retourne le nom canonique d'une entité après résolution."""
        if not entity_name:
            return ""
        return self.name_to_canonical.get(entity_name, entity_name)
