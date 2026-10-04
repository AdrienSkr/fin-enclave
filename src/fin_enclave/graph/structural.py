"""
Détecteurs structurels sur les couches détention / contrôle (sans montants).

- Prête-noms : un même dirigeant rattaché à un nombre anormal de sociétés (k_out élevé).
- Adresses-hubs : une même adresse d'enregistrement partagée par un nombre anormal de sociétés.
- Intermédiaires pivots : cabinets/agents enregistrés par degré sortant.
Tout est déterministe (degrés), en O(V+E).
"""

from collections import Counter

import networkx as nx


def _targets_of_type(G: nx.DiGraph, n: str, etype: str) -> list[str]:
    return [v for v in G.successors(n) if G.nodes[v].get("entity_type") == etype]


def detect_nominee_hubs(G: nx.DiGraph, min_entities: int = 30) -> list[dict]:
    """Dirigeants (personnes ou sociétés-prête-noms) liés à >= min_entities sociétés distinctes."""
    out = []
    for n, data in G.nodes(data=True):
        if data.get("entity_type") in ("Intermediaire", "Adresse"):
            continue
        companies = _targets_of_type(G, n, "Societe")
        if len(companies) < min_entities:
            continue
        countries = Counter(G.nodes[c].get("country", "") for c in companies)
        out.append(
            {
                "node": n,
                "name": data.get("name", n),
                "k_out": len(companies),
                "n_jurisdictions": len([c for c in countries if c]),
                "top_countries": countries.most_common(3),
                "intermediaries": len(
                    {
                        i
                        for c in companies
                        for i in G.predecessors(c)
                        if G.nodes[i].get("entity_type") == "Intermediaire"
                    }
                ),
                "entities_sample": companies[:5],
            }
        )
    return sorted(out, key=lambda d: -d["k_out"])


def detect_address_hubs(G: nx.DiGraph, min_entities: int = 50) -> list[dict]:
    """Adresses partagées par >= min_entities entités (sociétés ou dirigeants)."""
    out = []
    for n, data in G.nodes(data=True):
        if data.get("entity_type") != "Adresse":
            continue
        k = G.in_degree(n)
        if k >= min_entities:
            companies = sum(
                1 for p in G.predecessors(n) if G.nodes[p].get("entity_type") == "Societe"
            )
            out.append({"node": n, "name": data.get("name", n), "k_in": k, "companies": companies})
    return sorted(out, key=lambda d: -d["k_in"])


def detect_intermediary_pivots(G: nx.DiGraph, top: int = 10) -> list[dict]:
    """Intermédiaires classés par nombre de sociétés enregistrées."""
    out = []
    for n, data in G.nodes(data=True):
        if data.get("entity_type") != "Intermediaire":
            continue
        k = len(_targets_of_type(G, n, "Societe"))
        out.append({"node": n, "name": data.get("name", n), "k_out": k})
    return sorted(out, key=lambda d: -d["k_out"])[:top]
