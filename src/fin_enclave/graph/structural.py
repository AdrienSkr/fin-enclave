"""
Détecteurs structurels sur les couches détention / contrôle (sans montants).

- Prête-noms : un même dirigeant rattaché à un nombre anormal de sociétés (k_out élevé).
Tout est déterministe (degrés), en O(V+E).
"""

import math
from collections import Counter

import networkx as nx

# Rôle de bénéficiaire effectif déclaré : une personne inscrite à ce titre n'est jamais un
# prête-nom présumé, et ce rôle ne compte pas dans le seuil de portefeuille de mandats.
UBO_ROLE = "beneficial_owner"
MIN_NOMINEE_COMPANIES = 4


def build_portfolios(ownership: list[dict]) -> list[dict]:
    """
    Portefeuille de chaque acteur : sociétés qu'il détient ou dirige d'après les registres.

    Profil de prête-nom présumé : au moins `max(4, ⌈N/3⌉)` sociétés distinctes au titre de
    mandats (administrateur, secrétaire, actionnaire), N étant le nombre de sociétés du dossier.
    Les rôles de bénéficiaire effectif déclaré ne comptent pas, et un acteur inscrit comme
    bénéficiaire effectif n'est jamais présumé prête-nom.
    """
    by_actor: dict[str, dict] = {}
    mandates: dict[str, set[str]] = {}
    for row in ownership:
        for h in row["holders"]:
            a = by_actor.setdefault(
                h["id"],
                {"name": h["name"], "id": h["id"], "companies": [], "roles": Counter()},
            )
            if row["company"] not in a["companies"]:
                a["companies"].append(row["company"])
            a["roles"][h["role"]] += 1
            if h["role"] != UBO_ROLE:
                mandates.setdefault(h["id"], set()).add(row["company"])
    threshold = max(MIN_NOMINEE_COMPANIES, math.ceil(max(1, len(ownership)) / 3))
    out = []
    for actor_id, a in by_actor.items():
        declared_ubo = a["roles"].get(UBO_ROLE, 0) > 0
        out.append(
            {
                **a,
                "roles": dict(a["roles"]),
                "n_companies": len(a["companies"]),
                "n_mandates": len(mandates.get(actor_id, ())),
                "declared_ubo": declared_ubo,
                "nominee_profile": not declared_ubo
                and len(mandates.get(actor_id, ())) >= threshold,
                "nominee_threshold": threshold,
            }
        )
    return sorted(out, key=lambda a: (-a["n_companies"], a["name"]))


def _roles(edge: dict) -> list[str]:
    return list(edge.get("links") or [edge.get("rel_type", "")])


def _targets_of_type(G: nx.DiGraph, n: str, etype: str) -> list[str]:
    return [v for v in G.successors(n) if G.nodes[v].get("entity_type") == etype]


def detect_nominee_hubs(G: nx.DiGraph, min_entities: int = 30) -> list[dict]:
    """Dirigeants (personnes ou sociétés-prête-noms) liés à >= min_entities sociétés distinctes."""
    out = []
    for n, data in G.nodes(data=True):
        if data.get("entity_type") in ("Intermediaire", "Adresse"):
            continue
        companies = _targets_of_type(G, n, "Societe")
        # Même règle que `build_portfolios` : le rôle UBO ne compte pas, et son titulaire n'est
        # jamais présumé prête-nom.
        if any(UBO_ROLE in _roles(G[n][c]) for c in companies):
            continue
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
