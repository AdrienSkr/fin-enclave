"""
Fonctions d'analyste, 100 % déterministes (aucun LLM) : calculées depuis le graphe et les
constats, jamais depuis du texte libre. Une seule entrée : `build_analyst_view`.

- chronologie des flux des constats (date, émetteur, bénéficiaire, montant, cotes) ;
- réquisitions complémentaires : parties de flux sans relevé au dossier, ou hors période
  couverte par le relevé ;
- priorisation des entités et des constats par un score décomposé ;
- chaîne de contrôle de chaque société d'un constat jusqu'à la personne physique (UBO).

La vue est un dictionnaire JSON-sérialisable ; chaque ligne renvoie à ses cotes de pièces.
"""

from collections import Counter
from collections.abc import Iterable
from typing import Any

import networkx as nx

from .documents.models import OWNERSHIP_ROLES, PieceExtraction

# Barème du score de priorité (total 100) : explicite, affiché avec chaque score.
WEIGHTS = {"amount": 40.0, "typologies": 20.0, "centrality": 15.0, "findings": 25.0}
PER_TYPOLOGY = 10.0  # points par typologie distincte (plafonné à WEIGHTS["typologies"])
PER_FINDING = 5.0  # points par constat où l'entité figure (plafonné à WEIGHTS["findings"])
MAX_CHAIN_DEPTH = 8
MAX_CHAINS = 5
NATURAL_PERSON = "PersonnePhysique"


def _name(G: nx.DiGraph, n: str) -> str:
    return G.nodes[n].get("name", n)


def _transfers(G: nx.DiGraph, u: str, v: str) -> list[dict]:
    return G[u][v].get("transfers", []) if G.has_edge(u, v) else []


def _finding_edges(findings) -> list[tuple[str, list[tuple[str, str]], list[str]]]:
    """(libellé, arêtes de flux, sommets) de chaque cycle et de chaque fractionnement."""
    out = []
    for i, c in enumerate(findings["cycles"], 1):
        ids = c["cycle_ids"]
        edges = [(ids[k], ids[(k + 1) % len(ids)]) for k in range(len(ids))]
        out.append((f"Circuit fermé {i}", edges, list(ids)))
    for i, s in enumerate(findings["smurfing"], 1):
        edges = [e for m in s["mules"] for e in ((s["source"], m), (m, s["collector"]))]
        out.append((f"Fractionnement {i}", edges, [s["source"], *s["mules"], s["collector"]]))
    return out


def _timeline(G: nx.DiGraph, fedges) -> list[dict]:
    rows, seen = [], set()
    for label, edges, _ in fedges:
        for u, v in edges:
            for t in _transfers(G, u, v):
                if t["tx_id"] in seen:
                    continue
                seen.add(t["tx_id"])
                rows.append(
                    {
                        "date": t["date"],
                        "from": _name(G, u),
                        "to": _name(G, v),
                        "amount_usd": t["amount_usd"],
                        "pieces": sorted(t.get("corroborated_by", [t["piece"]])),
                        "finding": label,
                        "tx_id": t["tx_id"],
                    }
                )
    rows.sort(key=lambda r: (not r["date"], r["date"], r["tx_id"]))
    return rows


def _statement_parties(
    G: nx.DiGraph, pieces: list[PieceExtraction]
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Relevé -> titulaire (partie commune de ses flux, si unique) et dates de ses flux."""
    statements = {p.piece_id for p in pieces if p.doc_type == "bank_statement"}
    parties: dict[str, set[str]] = {}
    dates: dict[str, list[str]] = {}
    for u, v, e in G.edges(data=True):
        for t in e.get("transfers", []):
            for sid in statements & set(t.get("corroborated_by", [])):
                parties[sid] = parties.get(sid, {u, v}) & {u, v}
                if t["date"]:
                    dates.setdefault(sid, []).append(t["date"])
    # titulaire indéterminable (plusieurs candidats) : on ne prétend rien couvrir
    return {sid: next(iter(h)) for sid, h in parties.items() if len(h) == 1}, dates


def _statement_coverage(G: nx.DiGraph, pieces: list[PieceExtraction]) -> dict[str, list[str]]:
    """Titulaire -> [début, fin] couverts par ses relevés : période imprimée, sinon dates lues."""
    holders, dates = _statement_parties(G, pieces)
    by_id = {p.piece_id: p for p in pieces}
    coverage: dict[str, list[str]] = {}
    for sid, holder in holders.items():
        piece = by_id[sid]
        printed = [d.isoformat() for d in (piece.period_start, piece.period_end) if d]
        known = [*coverage.get(holder, []), *dates.get(sid, []), *printed]
        if known:
            coverage[holder] = [min(known), max(known)]
    return coverage


def _statement_accounts(G: nx.DiGraph, pieces: list[PieceExtraction]) -> dict[str, dict]:
    """Titulaire -> IBAN et banque lus en en-tête de ses relevés (premier renseigné)."""
    holders, _ = _statement_parties(G, pieces)
    by_id = {p.piece_id: p for p in pieces}
    accounts: dict[str, dict] = {}
    for sid, holder in holders.items():
        info = accounts.setdefault(holder, {"iban": "", "bank": ""})
        info["iban"] = info["iban"] or by_id[sid].account_iban
        info["bank"] = info["bank"] or by_id[sid].bank
    return accounts


def _confirm_reason(pieces: list[PieceExtraction], piece_ids: Iterable[str]) -> str:
    """Motif de confirmation : raisons des pièces à relire, sinon motifs de lignes."""
    by_id = {p.piece_id: p for p in pieces}
    parts: list[str] = []
    for pid in sorted(piece_ids):
        p = by_id.get(pid)
        if p is None:
            continue
        if p.needs_review and p.review_reason:
            parts.append(f"{pid} : {p.review_reason}")
            continue
        flags = sorted({f for t in p.transfers for f in t.review_flags})
        if flags:
            parts.append(f"{pid} : {', '.join(flags)}")
    return " ; ".join(parts)


def _requisitions(
    G: nx.DiGraph, pieces: list[PieceExtraction], in_findings: set[str]
) -> list[dict]:
    """Comptes cités dans des flux sans relevé au dossier, ou hors période couverte."""
    statements = {p.piece_id for p in pieces if p.doc_type == "bank_statement"}
    coverage = _statement_coverage(G, pieces)
    accounts = _statement_accounts(G, pieces)
    # Pièce à relire : on garde la réquisition, marquée « à confirmer » (arbitrage c).
    to_review = {p.piece_id for p in pieces if p.needs_review}
    flagged_lines = {p.piece_id for p in pieces if any(t.review_flags for t in p.transfers)}
    review_ids = to_review | flagged_lines
    seen: dict[str, list[dict]] = {}
    for u, v, e in G.edges(data=True):
        for t in e.get("transfers", []):
            for n in (u, v):
                seen.setdefault(n, []).append(t)
    rows = []
    for n, ts in seen.items():
        if G.nodes[n].get("entity_type") not in {"Societe", NATURAL_PERSON}:
            continue
        if n not in coverage:
            dated = sorted(t["date"] for t in ts if t["date"])
            cited_review = review_ids & set(G.nodes[n].get("mentions", []))
            rows.append(
                _req(
                    G,
                    n,
                    dated,
                    ts,
                    "aucun relevé au dossier",
                    in_findings,
                    accounts,
                    confirm=cited_review,
                    pieces=pieces,
                )
            )
            continue
        lo, hi = coverage[n]
        outside = [t for t in ts if t["date"] and not lo <= t["date"] <= hi]
        outside = [t for t in outside if not statements & set(t.get("corroborated_by", []))]
        if outside:
            dated = sorted(t["date"] for t in outside)
            reason = f"période non couverte (relevé du {lo} au {hi})"
            cited = {p for t in outside for p in t.get("corroborated_by", [t["piece"]])}
            rows.append(
                _req(
                    G,
                    n,
                    dated,
                    outside,
                    reason,
                    in_findings,
                    accounts,
                    confirm=review_ids & cited,
                    pieces=pieces,
                )
            )
    rows.sort(key=lambda r: (not r["in_finding"], r["account"]))
    return rows


def _req(
    G,
    n: str,
    dated: list[str],
    ts: list[dict],
    reason: str,
    in_findings: set[str],
    accounts: dict[str, dict],
    *,
    confirm: set[str] | None = None,
    pieces: list[PieceExtraction] | None = None,
) -> dict:
    cited = sorted({p for t in ts for p in t.get("corroborated_by", [t["piece"]])})
    known = accounts.get(n, {})
    row = {
        "account": _name(G, n),
        "iban": known.get("iban", ""),
        "bank": known.get("bank") or "non précisée dans les pièces",
        "period": [dated[0], dated[-1]] if dated else [],
        "reason": reason,
        "cited_by": cited,
        "in_finding": n in in_findings,
        "to_confirm": bool(confirm),
        "confirm_reason": _confirm_reason(pieces or [], confirm or ()) if confirm else "",
    }
    return row


def _typologies(findings) -> dict[str, set[str]]:
    typ: dict[str, set[str]] = {}
    for c in findings["cycles"]:
        for n in c["cycle_ids"]:
            typ.setdefault(n, set()).add("cycle")
    for s in findings["smurfing"]:
        for n in (s["source"], s["collector"], *s["mules"]):
            typ.setdefault(n, set()).add("fractionnement")
    for h in findings["hidden_controllers"]:
        typ.setdefault(h["id"], set()).add("contrôleur caché")
    for a in findings["portfolios"]:
        if a["nominee_profile"]:
            typ.setdefault(a["id"], set()).add("prête-nom présumé")
    return typ


def _scale(value: float, top: float, weight: float) -> float:
    return round(weight * value / top, 2) if top > 0 else 0.0


def _priorities(G, findings, detection, fedges) -> dict[str, list[dict]]:
    typ = _typologies(findings)
    amount: Counter[str] = Counter()
    n_findings: Counter[str] = Counter()
    for _, edges, nodes in fedges:
        n_findings.update(set(nodes))
        for u, v in edges:
            vol = sum(t["amount_usd"] for t in _transfers(G, u, v))
            amount[u] += vol
            amount[v] += vol
    btw = detection.betweenness_scores
    # Un constat hors flux (contrôleur caché, prête-nom) pèse par les flux attestés de l'entité.
    for m in findings["money_ranking"]:
        if typ.get(m["id"]) and m["id"] not in amount:
            amount[m["id"]] = m["received_usd"] + m["sent_usd"]
    top_amount = max(amount.values(), default=0.0)
    top_btw = max(btw.values(), default=0.0)

    def breakdown(n: str) -> dict[str, float]:
        return {
            "amount": _scale(amount[n], top_amount, WEIGHTS["amount"]),
            "typologies": min(PER_TYPOLOGY * len(typ.get(n, ())), WEIGHTS["typologies"]),
            "centrality": _scale(btw.get(n, 0.0), top_btw, WEIGHTS["centrality"]),
            "findings": min(PER_FINDING * n_findings[n], WEIGHTS["findings"]),
        }

    entities = []
    for n, d in G.nodes(data=True):
        if d.get("entity_type") not in {"Societe", NATURAL_PERSON}:
            continue
        b = breakdown(n)
        if sum(b.values()) <= 0:
            continue
        entities.append(
            {
                "name": _name(G, n),
                "id": n,
                "score": round(sum(b.values()), 2),
                "breakdown": b,
                "typologies": sorted(typ.get(n, ())),
                "n_findings": n_findings[n],
                "amount_usd": round(amount[n], 2),
            }
        )
    entities.sort(key=lambda r: (-r["score"], r["name"]))

    ranked = []
    top_size = max((len(set(nodes)) for _, _, nodes in fedges), default=0)
    volumes = [
        sum(t["amount_usd"] for u, v in e for t in _transfers(G, u, v)) for _, e, _ in fedges
    ]
    for (label, _, nodes), vol in zip(fedges, volumes, strict=True):
        b = {
            "amount": _scale(vol, max(volumes, default=0.0), 60.0),
            "centrality": _scale(max((btw.get(n, 0.0) for n in nodes), default=0.0), top_btw, 20.0),
            "entities": _scale(len(set(nodes)), top_size, 20.0),
        }
        ranked.append(
            {
                "finding": label,
                "score": round(sum(b.values()), 2),
                "breakdown": b,
                "amount_usd": round(vol, 2),
                "entities": [_name(G, n) for n in dict.fromkeys(nodes)],
            }
        )
    ranked.sort(key=lambda r: (-r["score"], r["finding"]))
    for i, r in enumerate(ranked, 1):
        r["rank"] = i
    return {"entities": entities, "findings": ranked}


def _owners(G: nx.DiGraph, n: str, roles: set[str]) -> list[tuple[str, list[str], list[str]]]:
    return [
        (p, [r for r in G[p][n].get("links", []) if r in roles], G[p][n].get("pieces", []))
        for p in G.predecessors(n)
        if set(G[p][n].get("links", [])) & roles
    ]


def _chains_from(G: nx.DiGraph, company: str) -> list[dict]:
    """Remonte les détenteurs (actionnaire / BO) jusqu'aux personnes physiques."""
    out: list[dict] = []

    def walk(n: str, path: list[str], roles: list[str], pieces: set[str]) -> None:
        if len(out) >= MAX_CHAINS:
            return
        owners = _owners(G, n, OWNERSHIP_ROLES)
        if not owners or len(path) > MAX_CHAIN_DEPTH:
            if len(path) > 1:
                out.append(_chain(G, path, roles, pieces, False))
            return
        for p, rs, ps in owners:
            if p in path:  # détention circulaire : on n'itère pas
                continue
            nxt, nroles, npieces = [*path, p], [*roles, rs[0]], pieces | set(ps)
            if G.nodes[p].get("entity_type") == NATURAL_PERSON:
                out.append(_chain(G, nxt, nroles, npieces, True))
            else:
                walk(p, nxt, nroles, npieces)

    walk(company, [company], [], set())
    out.sort(key=lambda c: (not c["complete"], len(c["path"])))
    return out


def _chain(G, path: list[str], roles: list[str], pieces: set[str], complete: bool) -> dict:
    return {
        "path": [_name(G, n) for n in path],
        "roles": roles,
        "ubo": _name(G, path[-1]) if complete else None,
        "complete": complete,
        "pieces": sorted(pieces),
    }


def _control_chains(G: nx.DiGraph, fedges, findings) -> list[dict]:
    companies = list(
        dict.fromkeys(
            [n for _, _, nodes in fedges for n in nodes]
            + [c for h in findings["hidden_controllers"] for c in _hidden_company_ids(G, h)]
        )
    )
    rows = []
    for n in companies:
        if G.nodes[n].get("entity_type") != "Societe":
            continue
        chains = _chains_from(G, n)
        directors = [
            _name(G, p)
            for p, _, _ in _owners(G, n, {"director"})
            if G.nodes[p].get("entity_type") == NATURAL_PERSON
        ]
        note = ""
        if not any(c["complete"] for c in chains):
            note = "aucune personne physique détentrice identifiée dans les pièces"
            if directors:
                note += " ; dirigeants connus : " + ", ".join(sorted(directors))
        rows.append({"company": _name(G, n), "id": n, "chains": chains, "note": note})
    return sorted(rows, key=lambda r: r["company"])


def _hidden_company_ids(G: nx.DiGraph, h: dict) -> Iterable[str]:
    names = set(h["companies"])
    return [n for n, d in G.nodes(data=True) if d.get("name") in names]


def build_analyst_view(
    G: nx.DiGraph, findings, pieces: list[PieceExtraction], detection
) -> dict[str, Any]:
    """Chronologie, réquisitions, priorités et chaînes de contrôle d'un dossier analysé."""
    fedges = _finding_edges(findings)
    in_findings = {n for _, _, nodes in fedges for n in nodes}
    return {
        "timeline": _timeline(G, fedges),
        "requisitions": _requisitions(G, pieces, in_findings),
        "priorities": _priorities(G, findings, detection, fedges),
        "control_chains": _control_chains(G, fedges, findings),
        "weights": WEIGHTS,
        # Sans centralité calculée, le poids de la centralité vaut 0 : à dire, pas à masquer.
        "centrality_available": any(detection.betweenness_scores.values()),
    }
