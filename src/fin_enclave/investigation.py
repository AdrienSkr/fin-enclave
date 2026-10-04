"""
Investigation d'un dossier de pièces, de bout en bout et en une seule passe :

pièces (scans, photos, PDF image) -> lecture IA contrôlée par OCR témoin -> mise en relation
inter-pièces -> graphe détention / contrôle / flux -> réponses déterministes :

1. qui détient / dirige quelle société (registres, certificats, procurations) ;
2. qui est au centre (portefeuille de sociétés, profil de prête-nom, centralité de Brandes) ;
3. où va l'argent (circuits fermés, fractionnement, qui encaisse in fine) ;
4. qui contrôle réellement derrière le prête-nom (procurations non enregistrées).

Chaque constat renvoie aux pièces qui le fondent (cote, fichier, SHA-256). Le LLM n'intervient
qu'en aval, pour rédiger, jamais pour trouver.
"""

import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx

from .documents.extractor import extract_dossier, make_engine
from .documents.linker import build_document_graph
from .documents.models import OWNERSHIP_ROLES, PieceExtraction
from .graph.detector import DetectionResult, GraphDetector
from .graph.resolver import EntityResolver
from .schemas import AnomalyReport, ProofPoint

HOLDING_ROLES = OWNERSHIP_ROLES | {"director", "secretary"}


@dataclass
class Investigation:
    dossier: Path
    engine: str
    pieces: list[PieceExtraction]
    graph: nx.DiGraph
    resolver: EntityResolver
    ledger: dict[str, ProofPoint]
    detection: DetectionResult
    findings: dict
    reports: list[AnomalyReport] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def piece_by_id(self) -> dict[str, PieceExtraction]:
        return {p.piece_id: p for p in self.pieces}


def _name(G: nx.DiGraph, n: str) -> str:
    return G.nodes[n].get("name", n)


def _roles(data: dict) -> list[str]:
    return list(data.get("links", []))


def ownership_table(G: nx.DiGraph) -> list[dict]:
    """Pour chaque société : détenteurs, dirigeants, mandataires, intermédiaire, pièces."""
    rows = []
    for c, data in G.nodes(data=True):
        if data["entity_type"] != "Societe":
            continue
        holders, intermediaries, attorneys = [], [], []
        for p in G.predecessors(c):
            e = G[p][c]
            for role in _roles(e):
                item = {"name": _name(G, p), "id": p, "role": role, "pieces": e["pieces"]}
                if role == "intermediary":
                    intermediaries.append(item)
                elif role == "attorney":
                    attorneys.append(item)
                elif role in HOLDING_ROLES:
                    holders.append(item)
        if holders or intermediaries or attorneys:
            rows.append(
                {
                    "company": data["name"],
                    "id": c,
                    "holders": holders,
                    "attorneys": attorneys,
                    "intermediaries": intermediaries,
                    "pieces": data["mentions"],
                }
            )
    return sorted(rows, key=lambda r: r["company"])


def portfolios(G: nx.DiGraph, ownership: list[dict]) -> list[dict]:
    """Portefeuille de chaque acteur : sociétés qu'il détient ou dirige d'après les registres."""
    by_actor: dict[str, dict] = {}
    for row in ownership:
        for h in row["holders"]:
            a = by_actor.setdefault(
                h["id"],
                {"name": h["name"], "id": h["id"], "companies": [], "roles": Counter()},
            )
            if row["company"] not in a["companies"]:
                a["companies"].append(row["company"])
            a["roles"][h["role"]] += 1
    n_companies = max(1, len(ownership))
    threshold = max(4, math.ceil(n_companies / 3))
    out = []
    for a in by_actor.values():
        out.append(
            {
                **a,
                "roles": dict(a["roles"]),
                "n_companies": len(a["companies"]),
                "nominee_profile": len(a["companies"]) >= threshold,
                "nominee_threshold": threshold,
            }
        )
    return sorted(out, key=lambda a: (-a["n_companies"], a["name"]))


def money_ranking(G: nx.DiGraph) -> list[dict]:
    """Solde net des flux attestés par les pièces : qui encaisse in fine."""
    acc: dict[str, dict] = defaultdict(
        lambda: {"received_usd": 0.0, "sent_usd": 0.0, "n_transfers": 0, "pieces": set()}
    )
    for u, v, e in G.edges(data=True):
        for t in e.get("transfers", []):
            acc[u]["sent_usd"] += t["amount_usd"]
            acc[v]["received_usd"] += t["amount_usd"]
            for n in (u, v):
                acc[n]["n_transfers"] += 1
                acc[n]["pieces"].update(t["corroborated_by"])
    rows = [
        {
            "name": _name(G, n),
            "id": n,
            "entity_type": G.nodes[n]["entity_type"],
            "received_usd": round(a["received_usd"], 2),
            "sent_usd": round(a["sent_usd"], 2),
            "net_usd": round(a["received_usd"] - a["sent_usd"], 2),
            "n_transfers": a["n_transfers"],
            "pieces": sorted(a["pieces"]),
        }
        for n, a in acc.items()
    ]
    return sorted(rows, key=lambda r: (-r["net_usd"], r["name"]))


def hidden_controllers(G: nx.DiGraph, ownership: list[dict], folios: list[dict]) -> list[dict]:
    """
    Mandataire non inscrit au registre (procuration) sur une société dont le registre ne montre
    qu'un acteur au profil de prête-nom : contrôleur réel présumé, à vérifier par l'enquêteur.
    """
    nominees = {a["id"] for a in folios if a["nominee_profile"]}
    found: dict[str, dict] = {}
    for row in ownership:
        registered = {h["id"] for h in row["holders"]}
        fronts = sorted(registered & nominees)
        for att in row["attorneys"]:
            if att["id"] in registered or not fronts:
                continue
            c = found.setdefault(
                att["id"],
                {
                    "name": att["name"],
                    "id": att["id"],
                    "companies": [],
                    "nominees": set(),
                    "pieces": set(),
                },
            )
            c["companies"].append(row["company"])
            c["nominees"].update(_name(G, f) for f in fronts)
            c["pieces"].update(att["pieces"])
            for h in row["holders"]:
                if h["id"] in fronts:
                    c["pieces"].update(h["pieces"])
    return [
        {**c, "nominees": sorted(c["nominees"]), "pieces": sorted(c["pieces"])}
        for c in sorted(found.values(), key=lambda c: (-len(c["companies"]), c["name"]))
    ]


def _cycle_findings(G: nx.DiGraph, detection: DetectionResult) -> list[dict]:
    out = []
    for d in detection.cycle_details:
        ids = d["cycle_ids"]
        steps = []
        for i, s in enumerate(d["steps"]):
            e = G[ids[i]][ids[(i + 1) % len(ids)]]
            steps.append({**s, "pieces": e["pieces"], "transfers": e.get("transfers", [])})
        out.append({**d, "steps": steps})
    return out


def _smurfing_findings(G: nx.DiGraph, detection: DetectionResult) -> list[dict]:
    out = []
    for s in detection.smurfing_findings:
        pieces = sorted(
            {
                p
                for m in s["mules"]
                for u, v in ((s["source"], m), (m, s["collector"]))
                for p in G[u][v]["pieces"]
            }
        )
        out.append(
            {
                **s,
                "source_name": _name(G, s["source"]),
                "collector_name": _name(G, s["collector"]),
                "mule_names": [_name(G, m) for m in s["mules"]],
                "downstream_names": [_name(G, n) for n in s["downstream"]],
                "pieces": pieces,
            }
        )
    return out


def _vigilance(pieces: list[PieceExtraction], resolver: EntityResolver, G: nx.DiGraph) -> dict:
    """Ce que l'enquêteur doit valider à la main : rien n'est masqué."""
    return {
        "failed_pieces": [{"piece": p.piece_id, "error": p.error[:200]} for p in pieces if p.error],
        "rejected_entities": [
            {"piece": p.piece_id, "name": e.name, "score": e.grounding_score}
            for p in pieces
            for e in p.entities
            if e.grounded is False
        ],
        "unverifiable_entities": sum(e.grounded is None for p in pieces for e in p.entities),
        "uncorroborated_amounts": [
            {"tx_id": t["tx_id"], "amount": t["amount"], "currency": t["currency"]}
            for _, _, e in G.edges(data=True)
            for t in e.get("transfers", [])
            if t["amount_corroborated"] is not True
        ],
        "undated_transfers": [
            t["tx_id"]
            for _, _, e in G.edges(data=True)
            for t in e.get("transfers", [])
            if not t["date"]
        ],
        "name_merges": [
            m._asdict() for m in resolver.merge_history if m.original_name != m.canonical_name
        ],
    }


def analyse(pieces: list[PieceExtraction], require_grounding: bool = True) -> tuple:
    """Graphe + constats déterministes à partir d'extractions (sans appel réseau)."""
    G, resolver, ledger = build_document_graph(pieces, require_grounding=require_grounding)
    detection = GraphDetector(G).run_detection()
    own = ownership_table(G)
    folios = portfolios(G, own)
    flows = [t for _, _, e in G.edges(data=True) for t in e.get("transfers", [])]
    findings = {
        "ownership": own,
        "portfolios": folios,
        "hidden_controllers": hidden_controllers(G, own, folios),
        "money_ranking": money_ranking(G),
        "cycles": _cycle_findings(G, detection),
        "smurfing": _smurfing_findings(G, detection),
        "pivot": {
            "name": detection.pivot_name,
            "id": detection.pivot_node,
            "betweenness": round(detection.betweenness_scores.get(detection.pivot_node, 0.0), 4),
        },
        "flows": {
            "count": len(flows),
            "total_usd": round(sum(t["amount_usd"] for t in flows), 2),
        },
        "vigilance": _vigilance(pieces, resolver, G),
    }
    return G, resolver, ledger, detection, findings


def investigate(
    dossier: Path | str,
    engine=None,
    cache_dir: Path | None = None,
    qualify: bool = True,
    llm_notes: bool = False,
    llm_model: str | None = None,
) -> Investigation:
    from .reasoning.qualifier import qualify_findings

    dossier = Path(dossier)
    engine = engine or make_engine()
    t0 = time.perf_counter()
    pieces = extract_dossier(dossier, engine, cache_dir=cache_dir)
    t1 = time.perf_counter()
    G, resolver, ledger, detection, findings = analyse(pieces)
    t2 = time.perf_counter()
    inv = Investigation(
        dossier=dossier,
        engine=engine.slug,
        pieces=pieces,
        graph=G,
        resolver=resolver,
        ledger=ledger,
        detection=detection,
        findings=findings,
    )
    if qualify:
        inv.reports = qualify_findings(inv, use_llm=llm_notes, model=llm_model, cache_dir=cache_dir)
    inv.timings = {
        "extraction_s": round(t1 - t0, 2),
        "graph_and_detection_s": round(t2 - t1, 3),
        "qualification_s": round(time.perf_counter() - t2, 2),
    }
    return inv
