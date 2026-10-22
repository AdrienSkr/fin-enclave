"""
Exports interopérables du graphe d'enquête (hors ligne, aucune dépendance réseau).

- `noeuds.csv` / `aretes.csv` : en-têtes d'import `neo4j-admin` (`:ID`, `:LABEL`, `:START_ID`,
  `:END_ID`, `:TYPE`), lisibles aussi par Linkurious ;
- `graphe.graphml` : i2, Gephi, yEd (via networkx) ;
- `import.cypher` : script rejouable dans Neo4j Browser / cypher-shell.

Chaque arête porte la cote des pièces qui la fondent et l'empreinte SHA-256 de leur conteneur.
"""

import csv
import re
from pathlib import Path
from typing import Any

import networkx as nx

from .investigation import Investigation

NODE_LABEL = "Entite"


def _join(values: list[str]) -> str:
    return ";".join(dict.fromkeys(v for v in values if v))


def _edge_pieces(data: dict[str, Any]) -> list[str]:
    cotes = [*data.get("pieces", []), *(t.get("piece", "") for t in data.get("transfers", []))]
    return sorted({c for c in cotes if c}) or [str(data.get("doc_reference", ""))]


def _edge_sha(inv: Investigation, pieces: list[str], fallback: str) -> str:
    sha_of = {p.piece_id: p.file_sha256 for p in inv.pieces}
    shas = [sha_of[c] for c in pieces if c in sha_of]
    return _join(shas) or fallback


def _token(value: str, upper: bool = False) -> str:
    out = re.sub(r"[^A-Za-z0-9_]", "_", value).strip("_") or "LIEN"
    return out.upper() if upper else out


def _cypher_str(value: object) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _rows(inv: Investigation) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        {
            "id": str(n),
            "name": str(d.get("name", n)),
            "type": str(d.get("entity_type", "")),
            "country": str(d.get("country", "")),
            "pieces": _join(list(d.get("mentions", []))),
            "sha256": str(d.get("proof_sha256", "")),
        }
        for n, d in inv.graph.nodes(data=True)
    ]
    edges = []
    for u, v, d in inv.graph.edges(data=True):
        pieces = _edge_pieces(d)
        edges.append(
            {
                "start": str(u),
                "end": str(v),
                "type": _token(str(d.get("rel_type", "lien")), upper=True),
                "amount_usd": float(d.get("amount_usd", 0.0) or 0.0),
                "n_transfers": len(d.get("transfers", [])),
                "pieces": _join(pieces),
                "sha256": _edge_sha(inv, pieces, str(d.get("proof_sha256", ""))),
            }
        )
    return nodes, edges


def _write_csv(out_dir: Path, nodes: list[dict], edges: list[dict]) -> None:
    with (out_dir / "noeuds.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["entityId:ID", ":LABEL", "name", "type", "country", "pieces", "sha256"])
        for n in nodes:
            labels = _join([NODE_LABEL, _token(n["type"]) if n["type"] else ""])
            w.writerow(
                [n["id"], labels, n["name"], n["type"], n["country"], n["pieces"], n["sha256"]]
            )
    with (out_dir / "aretes.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                ":START_ID",
                ":END_ID",
                ":TYPE",
                "amount_usd:float",
                "n_transfers:int",
                "pieces",
                "sha256",
            ]
        )
        for e in edges:
            w.writerow(
                [
                    e["start"],
                    e["end"],
                    e["type"],
                    e["amount_usd"],
                    e["n_transfers"],
                    e["pieces"],
                    e["sha256"],
                ]
            )


def _write_graphml(out_dir: Path, nodes: list[dict], edges: list[dict]) -> None:
    g = nx.DiGraph()
    for n in nodes:
        g.add_node(n["id"], **{k: v for k, v in n.items() if k != "id"})
    for e in edges:
        attrs = {k: v for k, v in e.items() if k not in ("start", "end")}
        g.add_edge(e["start"], e["end"], **attrs)
    nx.write_graphml(g, out_dir / "graphe.graphml", encoding="utf-8")


def _write_cypher(out_dir: Path, nodes: list[dict], edges: list[dict]) -> None:
    lines = [
        "// Import FinEnclave : graphe d'enquête (généré, rejouable)",
        f"CREATE INDEX entite_id IF NOT EXISTS FOR (n:{NODE_LABEL}) ON (n.id);",
    ]
    for n in nodes:
        label = f"{NODE_LABEL}:{_token(n['type'])}" if n["type"] else NODE_LABEL
        props = ", ".join(f"{k}: {_cypher_str(v)}" for k, v in n.items())
        lines.append(f"CREATE (:{label} {{{props}}});")
    for e in edges:
        props = (
            f"amount_usd: {e['amount_usd']}, n_transfers: {e['n_transfers']}, "
            f"pieces: {_cypher_str(e['pieces'])}, sha256: {_cypher_str(e['sha256'])}"
        )
        lines.append(
            f"MATCH (a:{NODE_LABEL} {{id: {_cypher_str(e['start'])}}}), "
            f"(b:{NODE_LABEL} {{id: {_cypher_str(e['end'])}}}) "
            f"CREATE (a)-[:{e['type']} {{{props}}}]->(b);"
        )
    (out_dir / "import.cypher").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_exports(inv: Investigation, out_dir: Path) -> dict[str, Path]:
    """Écrit les quatre exports à côté du rapport ; renvoie leurs chemins."""
    out_dir.mkdir(parents=True, exist_ok=True)
    nodes, edges = _rows(inv)
    _write_csv(out_dir, nodes, edges)
    _write_graphml(out_dir, nodes, edges)
    _write_cypher(out_dir, nodes, edges)
    return {
        "noeuds": out_dir / "noeuds.csv",
        "aretes": out_dir / "aretes.csv",
        "graphml": out_dir / "graphe.graphml",
        "cypher": out_dir / "import.cypher",
    }
