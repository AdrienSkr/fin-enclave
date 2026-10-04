"""Mesure de l'extraction et du graphe reconstruit contre la vérité terrain (graphe ICIJ réel)."""

from collections import defaultdict

import networkx as nx

from ..graph.resolver import jaro_winkler_similarity, normalize_entity_name
from .models import PieceExtraction


def _same(a: str, b: str, threshold: float = 0.9) -> bool:
    na, nb = normalize_entity_name(a), normalize_entity_name(b)
    return bool(na) and jaro_winkler_similarity(na, nb) >= threshold


def _pr(tp: int, n_pred: int, n_true: int) -> dict:
    p = tp / n_pred if n_pred else 1.0
    r = tp / n_true if n_true else 1.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4)}


def _match_count(pred: list, truth: list, eq) -> int:
    used: set[int] = set()
    tp = 0
    for x in pred:
        for j, y in enumerate(truth):
            if j not in used and eq(x, y):
                used.add(j)
                tp += 1
                break
    return tp


def _same_transfer(pred: tuple, true: dict) -> bool:
    payer, payee, amount, currency = pred[:4]
    return (
        _same(payer, true["payer"])
        and _same(payee, true["payee"])
        and currency == true["currency"]
        and abs(amount - true["amount"]) <= 0.005 * true["amount"]
    )


def evaluate_pieces(pieces: list[PieceExtraction], truth: list[dict]) -> dict:
    """P/R des entités, relations et virements par pièce (micro-moyenne), par qualité de pièce."""
    by_id = {t["piece_id"]: t for t in truth}
    agg: dict[str, list[int]] = defaultdict(lambda: [0] * 9)
    dates_ok = dates_total = 0
    ungrounded = total_entities = 0
    for p in pieces:
        t = by_id[p.piece_id]
        pe = [e.name for e in p.entities]
        te = [e["name"] for e in t["entities"]]
        # Seules les relations de détention / contrôle sont évaluées (rôle 'other' = commercial)
        pr = [(r.source, r.target, r.role) for r in p.relations if r.role != "other"]
        tr = [(r["source"], r["target"], r["role"]) for r in t["relations"]]
        ent_tp = _match_count(pe, te, _same)
        rel_tp = _match_count(
            pr, tr, lambda a, b: _same(a[0], b[0]) and _same(a[1], b[1]) and a[2] == b[2]
        )
        pt = [(x.payer, x.payee, x.amount, x.currency, x.date) for x in p.transfers]
        tt = t.get("transfers", [])
        tx_tp = _match_count(pt, tt, _same_transfer)
        for x in pt:
            match = next((y for y in tt if _same_transfer(x, y)), None)
            if match is not None:
                dates_total += 1
                dates_ok += bool(x[4]) and x[4].isoformat() == match["date"]
        for key in ("all", t["quality"]):
            a = agg[key]
            for i, v in enumerate(
                (ent_tp, len(pe), len(te), rel_tp, len(pr), len(tr), tx_tp, len(pt), len(tt))
            ):
                a[i] += v
        total_entities += len(p.entities)
        ungrounded += sum(1 for e in p.entities if e.grounded is False)

    out = {
        k: {
            "entities": _pr(a[0], a[1], a[2]),
            "relations": _pr(a[3], a[4], a[5]),
            "transfers": _pr(a[6], a[7], a[8]),
        }
        for k, a in agg.items()
    }
    out["transfer_dates_exact_rate"] = round(dates_ok / dates_total, 4) if dates_total else 0.0
    out["ungrounded_entity_rate"] = round(ungrounded / total_entities, 4) if total_entities else 0
    out["failed_pieces"] = sum(1 for p in pieces if p.error)
    return out


def evaluate_graph(G: nx.DiGraph, truth: list[dict]) -> dict:
    """P/R des liens du graphe reconstruit (dédoublonnés) contre les liens ICIJ du dossier."""
    true_edges = {(r["source"], r["target"], r["role"]) for t in truth for r in t["relations"]}
    pred_edges = [
        (G.nodes[u]["name"], G.nodes[v]["name"], role)
        for u, v, d in G.edges(data=True)
        for role in d["links"]
    ]
    tp = _match_count(
        pred_edges,
        sorted(true_edges),
        lambda a, b: _same(a[0], b[0]) and _same(a[1], b[1]) and a[2] == b[2],
    )
    true_names = {e["name"] for t in truth for e in t["entities"]}

    true_tx = [x for t in truth for x in t.get("transfers", [])]
    pred_tx = [
        (G.nodes[u]["name"], G.nodes[v]["name"], d["amount"], d["currency"])
        for u, v, e in G.edges(data=True)
        for d in e.get("transfers", [])
    ]
    flow_tp = _match_count(pred_tx, true_tx, _same_transfer)
    return {
        "edges": _pr(tp, len(pred_edges), len(true_edges)),
        "flows": _pr(flow_tp, len(pred_tx), len(true_tx)),
        "nodes_reconstructed": G.number_of_nodes(),
        "distinct_true_entities": len(true_names),
    }


def evaluate_scenario(findings: dict, scenario: dict) -> dict:
    """Le scénario simulé caché (circuit, fractionnement, bénéficiaire) est-il retrouvé ?"""

    def found(names: list[str], expected: list[str]) -> bool:
        return len(names) == len(expected) and all(
            any(_same(n, e) for n in names) for e in expected
        )

    cycles = [c["cycle_nodes"] for c in findings.get("cycles", [])]
    smurf = findings.get("smurfing", [])
    sm = scenario.get("smurfing")
    controllers = [c["name"] for c in findings.get("hidden_controllers", [])]
    top_list = findings.get("money_ranking") or [{}]
    top_money = top_list[0].get("name", "")
    has_cycle = "cycle" in scenario
    return {
        "cycle_found": any(found(c, scenario["cycle"]) for c in cycles) if has_cycle else False,
        "spurious_cycles": (
            sum(not found(c, scenario["cycle"]) for c in cycles) if has_cycle else len(cycles)
        ),
        "smurfing_found": (
            any(
                _same(s["source_name"], sm["source"])
                and _same(s["collector_name"], sm["collector"])
                for s in smurf
            )
            if sm
            else False
        ),
        "mules_found": (
            max(
                (
                    sum(any(_same(m, x) for m in s["mule_names"]) for x in sm.get("mules", []))
                    for s in smurf
                ),
                default=0,
            )
            if sm
            else 0
        ),
        "mules_expected": len(sm.get("mules", [])) if sm else 0,
        "hidden_beneficiary_found": (
            any(_same(c, scenario["beneficiary"]) for c in controllers)
            if "beneficiary" in scenario
            else False
        ),
        "top_money_is_beneficiary": (
            _same(top_money, scenario["beneficiary"]) if "beneficiary" in scenario else False
        ),
    }


def evaluate_typologies(G: nx.DiGraph, scenario: dict) -> dict[str, dict]:
    """
    Calcule, pour chaque typologie IBM dans scenario['ibm_patterns'], la part de ses
    transactions retrouvées dans le graphe (rappel).
    """
    patterns = scenario.get("ibm_patterns", [])
    if not patterns:
        return {}

    pred_tx = [
        (G.nodes[u]["name"], G.nodes[v]["name"], d["amount"], d["currency"])
        for u, v, e in G.edges(data=True)
        if "name" in G.nodes[u] and "name" in G.nodes[v]
        for d in e.get("transfers", [])
    ]

    out: dict[str, dict] = {}
    for entry in patterns:
        typo = entry.get("typology", "")
        txs = entry.get("tx", [])
        if not txs:
            continue
        tp = _match_count(pred_tx, txs, _same_transfer)
        recall = round(tp / len(txs), 4) if txs else 1.0
        out[typo] = {
            "found": tp,
            "total": len(txs),
            "recall": recall,
        }
    return out
