import csv
import hashlib
from pathlib import Path

import pytest

from fin_enclave.graph.structural import (
    detect_address_hubs,
    detect_intermediary_pivots,
    detect_nominee_hubs,
)
from fin_enclave.ingestion.icij_loader import (
    load_offshore_leaks,
    proof_for_edge,
    proof_for_node,
)

SRC = "Panama Papers"


def _write(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


@pytest.fixture()
def oldb(tmp_path: Path) -> Path:
    """Mini base au format ICIJ : 1 prête-nom (40 sociétés), 1 intermédiaire, 1 adresse-hub."""
    ent_h = ["node_id", "name", "jurisdiction_description", "country_codes", "sourceID", "status"]
    off_h = ["node_id", "name", "country_codes", "sourceID"]
    int_h = ["node_id", "name", "status", "country_codes", "sourceID"]
    adr_h = ["node_id", "address", "name", "country_codes", "sourceID"]
    rel_h = ["node_id_start", "node_id_end", "rel_type", "link", "status", "sourceID"]

    entities = [[f"E{i}", f"SHELL {i} LTD", "Panama", "PAN", SRC, "Active"] for i in range(40)]
    entities.append(["EX", "AUTRE SOURCE", "X", "XXX", "Bahamas Leaks", ""])
    _write(tmp_path / "nodes-entities.csv", ent_h, entities)
    _write(
        tmp_path / "nodes-officers.csv",
        off_h,
        [["O1", "NOMINEE DIRECTORS LTD", "PAN", SRC], ["O2", "JEAN DUPONT", "FRA", SRC]],
    )
    _write(tmp_path / "nodes-intermediaries.csv", int_h, [["I1", "AGENT SA", "ACTIVE", "PAN", SRC]])
    _write(tmp_path / "nodes-addresses.csv", adr_h, [["A1", "1 MAIN ST", "", "PAN", SRC]])

    rels = []
    for i in range(40):
        rels.append(["O1", f"E{i}", "officer_of", "director of", "", SRC])
        rels.append(["I1", f"E{i}", "intermediary_of", "intermediary of", "", SRC])
        rels.append([f"E{i}", "A1", "registered_address", "registered address", "", SRC])
    rels.append(["O2", "E0", "officer_of", "shareholder of", "", SRC])
    rels.append(["O2", "EX", "officer_of", "shareholder of", "", SRC])  # cible hors source
    _write(tmp_path / "relationships.csv", rel_h, rels)
    return tmp_path


def test_loader_filters_source_and_layers(oldb):
    G = load_offshore_leaks(oldb, SRC)
    assert "EX" not in G
    assert G.number_of_nodes() == 40 + 2 + 1 + 1
    assert G["O2"]["E0"]["layers"] == ["ownership"]
    assert G["O1"]["E0"]["layers"] == ["control"]
    assert all(d["amount_usd"] == 0.0 for _, _, d in G.edges(data=True))


def test_nominee_hub_detected_with_threshold(oldb):
    G = load_offshore_leaks(oldb, SRC)
    hubs = detect_nominee_hubs(G, min_entities=30)
    assert [h["name"] for h in hubs] == ["NOMINEE DIRECTORS LTD"]
    assert hubs[0]["k_out"] == 40
    assert detect_nominee_hubs(G, min_entities=41) == []


def test_address_hub_and_intermediary_pivot(oldb):
    G = load_offshore_leaks(oldb, SRC)
    assert detect_address_hubs(G, min_entities=30)[0]["k_in"] == 40
    assert detect_intermediary_pivots(G)[0]["k_out"] == 40


def test_proofs_anchor_on_real_source_files(oldb):
    G = load_offshore_leaks(oldb, SRC)
    node_proof = proof_for_node(G, "O1")
    assert (
        node_proof.document_sha256
        == hashlib.sha256((oldb / "nodes-officers.csv").read_bytes()).hexdigest()
    )
    assert node_proof.source_row == 1 and node_proof.cote_judiciaire == f"ICIJ/{SRC}/O1"
    edge_proof = proof_for_edge(G, "O1", "E3")
    assert edge_proof.document_sha256 == G.graph["source_files"]["relationships.csv"]
    assert edge_proof.row_sha256 != node_proof.row_sha256
