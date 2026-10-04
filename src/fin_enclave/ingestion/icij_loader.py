"""
Connecteur ICIJ Offshore Leaks Database (Panama Papers, Paradise Papers, Bahamas Leaks...).

Format : 5 tables de noeuds (entities, officers, intermediaries, addresses, others) + relationships.
La base ne contient AUCUN montant : elle alimente les couches 'ownership' et 'control' du graphe
(détention, mandat, intermédiaire, adresse), pas la couche 'flow'.

Traçabilité : chaque sommet et chaque arc portent l'empreinte de la ligne CSV source, la cote
(`ICIJ/<sourceID>/<node_id>`) et le numéro de ligne ; l'empreinte SHA-256 de chaque fichier source
est stockée dans `G.graph["source_files"]`. Aucun objet ProofPoint n'est matérialisé pour les
~10^6 éléments : `proof_for_node` / `proof_for_edge` le reconstruisent à la demande.
"""

import csv
import hashlib
from pathlib import Path

import networkx as nx

from ..schemas import ProofPoint

NODE_FILES = {
    "nodes-entities.csv": "Societe",
    "nodes-officers.csv": "PersonnePhysique",
    "nodes-intermediaries.csv": "Intermediaire",
    "nodes-addresses.csv": "Adresse",
    "nodes-others.csv": "Societe",
}
KEPT_RELATIONS = {"officer_of", "intermediary_of", "registered_address"}
OWNERSHIP_LINKS = ("shareholder", "beneficial owner", "beneficiary", "owner")


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _row_sha(values: list[str]) -> str:
    return hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()


def _read(path: Path):
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {name: i for i, name in enumerate(header)}
        for row_no, row in enumerate(reader, start=1):
            yield row_no, idx, row


def load_offshore_leaks(
    directory: Path | str,
    source: str = "Panama Papers",
    max_relationships: int | None = None,
) -> nx.DiGraph:
    """
    Charge le sous-graphe d'une source ICIJ. Les sommets ne sont créés que s'ils appartiennent
    à la source demandée ; les arcs sont orientés : dirigeant/intermédiaire -> entité,
    entité -> adresse.
    """
    d = Path(directory)
    G = nx.DiGraph()
    G.graph["source"] = source
    G.graph["source_files"] = {}

    for fname, etype in NODE_FILES.items():
        path = d / fname
        if not path.exists():
            continue
        G.graph["source_files"][fname] = _file_sha256(path)
        for row_no, idx, row in _read(path):
            if row[idx["sourceID"]] != source:
                continue
            node_id = row[idx["node_id"]]
            name = row[idx["name"]] if "name" in idx else ""
            if etype == "Adresse" and not name:
                name = row[idx["address"]] if "address" in idx else ""
            G.add_node(
                node_id,
                name=name,
                entity_type=etype,
                country=row[idx["country_codes"]] if "country_codes" in idx else "",
                jurisdiction=row[idx["jurisdiction_description"]]
                if "jurisdiction_description" in idx
                else "",
                status=row[idx["status"]] if "status" in idx else "",
                incorporation_date=row[idx["incorporation_date"]]
                if "incorporation_date" in idx
                else "",
                proof_sha256=_row_sha(row),
                doc_reference=f"ICIJ/{source}/{node_id}",
                source_file=fname,
                source_row=row_no,
            )

    rel_path = d / "relationships.csv"
    G.graph["source_files"]["relationships.csv"] = _file_sha256(rel_path)
    kept = 0
    for row_no, idx, row in _read(rel_path):
        if row[idx["sourceID"]] != source or row[idx["rel_type"]] not in KEPT_RELATIONS:
            continue
        u, v = row[idx["node_id_start"]], row[idx["node_id_end"]]
        if u not in G or v not in G:
            continue
        rel = row[idx["rel_type"]]
        link = row[idx["link"]].lower()
        layer = "ownership" if any(k in link for k in OWNERSHIP_LINKS) else "control"
        if G.has_edge(u, v):
            e = G[u][v]
            if layer not in e["layers"]:
                e["layers"].append(layer)
            e["links"].append(link)
        else:
            G.add_edge(
                u,
                v,
                rel_type=rel,
                layers=[layer],
                links=[link],
                amount_usd=0.0,
                date="",
                proof_sha256=_row_sha(row),
                doc_reference=f"ICIJ/{source}/rel/{row_no}",
                source_file="relationships.csv",
                source_row=row_no,
            )
        kept += 1
        if max_relationships and kept >= max_relationships:
            break
    return G


def _proof(G: nx.DiGraph, data: dict, value: str) -> ProofPoint:
    fname = data["source_file"]
    return ProofPoint(
        document_sha256=G.graph["source_files"][fname],
        page_sha256=data["proof_sha256"],
        cote_judiciaire=data["doc_reference"],
        extracted_value=value,
        source_file=fname,
        source_row=data["source_row"],
        row_sha256=data["proof_sha256"],
    )


def proof_for_node(G: nx.DiGraph, node_id: str) -> ProofPoint:
    return _proof(G, G.nodes[node_id], G.nodes[node_id].get("name", node_id))


def proof_for_edge(G: nx.DiGraph, u: str, v: str) -> ProofPoint:
    data = G[u][v]
    return _proof(G, data, f"{data['rel_type']} ({', '.join(data['links'])})")
