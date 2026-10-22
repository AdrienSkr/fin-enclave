import json

import networkx as nx
import pytest

from fin_enclave.config import settings
from fin_enclave.documents.evaluation import evaluate_graph, evaluate_pieces
from fin_enclave.documents.extractor import extract_piece
from fin_enclave.documents.forge import forge_dossier, select_case, truth_path
from fin_enclave.documents.linker import build_document_graph
from fin_enclave.documents.models import (
    DocumentExtraction,
    ExtractedEntity,
    ExtractedRelation,
    GroundedEntity,
    GroundedTransfer,
    PieceExtraction,
    StatementLine,
)
from fin_enclave.graph.structural import detect_nominee_hubs


def _icij_like() -> nx.DiGraph:
    """Mini graphe au format du connecteur ICIJ : 1 prête-nom actionnaire de 6 sociétés."""
    G = nx.DiGraph()
    G.add_node("H", name="ALPHA NOMINEES LIMITED", entity_type="PersonnePhysique")
    G.add_node("I", name="AGENT SERVICES LIMITED", entity_type="Intermediaire")
    for i in range(6):
        c = f"C{i}"
        G.add_node(
            c,
            name=f"COMPANY {chr(65 + i)} HOLDINGS LIMITED",
            entity_type="Societe",
            jurisdiction="British Virgin Islands",
            incorporation_date="01-JAN-2005",
        )
        G.add_edge("H", c, links=["shareholder of"])
        G.add_edge("I", c, links=["intermediary of"])
        G.add_node(f"D{i}", name=f"DIRECTOR NUMBER {i}", entity_type="PersonnePhysique")
        G.add_edge(f"D{i}", c, links=["director of"])
    return G


def _oracle(truth: list[dict], out_dir) -> list[PieceExtraction]:
    """Extraction parfaite simulée (vérité terrain) : isole le linker et l'évaluation."""
    return [
        PieceExtraction(
            piece_id=t["piece_id"],
            file=t["file"],
            file_sha256="0" * 64,
            engine="oracle",
            doc_type=t["doc_type"],
            entities=[
                GroundedEntity(**e, grounded=True, grounding_score=1.0) for e in t["entities"]
            ],
            relations=[ExtractedRelation(**r) for r in t["relations"]],
            transfers=[GroundedTransfer(**x, amount_grounded=True) for x in t["transfers"]],
        )
        for t in truth
    ]


@pytest.fixture(scope="module")
def dossier(tmp_path_factory):
    out = tmp_path_factory.mktemp("pieces_doc") / "pieces"
    case = select_case(_icij_like(), "H", n_companies=6, seed=1)
    forge_dossier(case, out, n_distractors=3, seed=1, anonymize=False)
    return out, json.loads(truth_path(out).read_text(encoding="utf-8"))


def test_forge_keeps_ground_truth_out_of_the_dossier(dossier):
    out, truth = dossier
    assert not any("truth" in p.name or p.suffix == ".json" for p in out.iterdir())
    registry = [
        t
        for t in truth
        if t["doc_type"] in ("certificate_of_incorporation", "register_of_directors")
    ]
    assert len(registry) == 6 * 2
    assert sum(t["doc_type"] == "invoice" for t in truth) == 3
    assert {"wire_transfer", "bank_statement", "power_of_attorney"} <= {
        t["doc_type"] for t in truth
    }
    assert {t["quality"] for t in truth} <= {"clean", "scan", "photo"}
    files = {p.name for p in out.iterdir()}
    assert all(t["file"] in files for t in truth)


def test_oracle_extraction_rebuilds_graph_and_nominee(dossier):
    out, truth = dossier
    pieces = _oracle(truth, out)
    G, _ = build_document_graph(pieces)
    assert evaluate_pieces(pieces, truth)["all"]["relations"]["recall"] == 1.0
    assert evaluate_graph(G, truth)["edges"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    hubs = detect_nominee_hubs(G, min_entities=6)
    assert [h["name"] for h in hubs] == ["ALPHA NOMINEES LIMITED"]


def test_ungrounded_entities_are_dropped_from_graph():
    piece = PieceExtraction(
        piece_id="PIECE-0001",
        file="PIECE-0001.png",
        file_sha256="a" * 64,
        engine="t",
        entities=[
            GroundedEntity(name="REAL CO LIMITED", kind="Societe", grounded=True),
            GroundedEntity(name="INVENTED PERSON", kind="PersonnePhysique", grounded=False),
        ],
        relations=[
            ExtractedRelation(source="INVENTED PERSON", target="REAL CO LIMITED", role="director")
        ],
    )
    G, _ = build_document_graph([piece])
    assert G.number_of_nodes() == 1 and G.number_of_edges() == 0


class _FakeVLM:
    slug = "fake-vlm"

    def __init__(self, result: DocumentExtraction | None):
        self.result, self.calls = result, 0

    def extract(self, img, ocr):
        self.calls += 1
        if self.result is None:
            raise RuntimeError("Extraction VLM invalide")
        return self.result


def test_extraction_is_cached_and_failures_are_not_repaired(dossier, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "extraction_cache_dir", tmp_path / "cache")
    out, truth = dossier
    path = out / truth[0]["file"]
    ok = _FakeVLM(
        DocumentExtraction(
            doc_type="other",
            entities=[ExtractedEntity(name="NOWHERE ON PAGE LIMITED", kind="Societe")],
        )
    )
    first = extract_piece(path, ok)
    second = extract_piece(path, ok)
    assert ok.calls == 1 and not first.from_cache and second.from_cache

    bad = _FakeVLM(None)
    bad.slug = "bad-vlm"
    failed = extract_piece(path, bad)
    assert failed.error and failed.entities == [] and failed.relations == []


@pytest.mark.parametrize(
    (
        "typology",
        "transfers_graph",
        "scenario_tx",
        "expected_found",
        "expected_total",
        "expected_recall",
    ),
    [
        (
            "CYCLE",
            [{"amount": 1000.0, "currency": "USD", "date": "2022-09-01"}],
            [
                {
                    "payer": "ALICE CORP",
                    "payee": "BOB CORP",
                    "amount": 1000.0,
                    "currency": "USD",
                    "date": "2022-09-01",
                },
                {
                    "payer": "BOB CORP",
                    "payee": "ALICE CORP",
                    "amount": 950.0,
                    "currency": "USD",
                    "date": "2022-09-02",
                },
            ],
            1,
            2,
            0.5,
        ),
        (
            "FAN-OUT",
            [{"amount": 500.0, "currency": "EUR", "date": "2022-09-03"}],
            [
                {
                    "payer": "ALICE CORP",
                    "payee": "BOB CORP",
                    "amount": 500.0,
                    "currency": "EUR",
                    "date": "2022-09-03",
                },
            ],
            1,
            1,
            1.0,
        ),
    ],
)
def test_evaluate_typologies(
    typology, transfers_graph, scenario_tx, expected_found, expected_total, expected_recall
):
    from fin_enclave.documents.evaluation import evaluate_typologies

    G = nx.DiGraph()
    G.add_node("A", name="ALICE CORP")
    G.add_node("B", name="BOB CORP")
    G.add_edge("A", "B", transfers=transfers_graph)
    scenario = {"ibm_patterns": [{"typology": typology, "tx": scenario_tx}]}
    res = evaluate_typologies(G, scenario)
    assert typology in res
    assert res[typology]["found"] == expected_found
    assert res[typology]["total"] == expected_total
    assert res[typology]["recall"] == expected_recall


def test_resolved_transfers_cleans_hyphenated_description_and_ref():
    """Vérifie le nettoyage déterministe de la forme 'Libellé - Nom' et des 'REF' résiduels."""
    doc = DocumentExtraction(
        doc_type="bank_statement",
        account_holder="ALPHA CORP",
        statement_lines=[
            StatementLine(
                date="2022-09-01",
                counterparty="Honoraires de conseil - Redwood Printing Ltd",
                amount=-1500.0,
                currency="EUR",
            ),
            StatementLine(
                date="2022-09-02",
                counterparty="VIR SEPA REF 12345 Amber Trading Ltd",
                amount=2500.0,
                currency="EUR",
            ),
            StatementLine(
                date="2022-09-03",
                counterparty="Monthly staff payroll REF 99123 - Pine Couriers Ltd",
                amount=-3000.0,
                currency="EUR",
            ),
            StatementLine(
                date="2022-09-04",
                counterparty="REF 55443 Summit Supplies Ltd",
                amount=-500.0,
                currency="EUR",
            ),
        ],
    )
    txs = doc.resolved_transfers()
    assert len(txs) == 4
    assert txs[0].payee == "Redwood Printing Ltd"
    assert txs[0].payer == "ALPHA CORP"
    assert txs[1].payer == "Amber Trading Ltd"
    assert txs[1].payee == "ALPHA CORP"
    assert txs[2].payee == "Pine Couriers Ltd"
    assert txs[3].payee == "Summit Supplies Ltd"


def test_wrong_currency_counts_in_main_score_not_in_currency_score():
    truth = [
        {
            "piece_id": "P1",
            "quality": "clean",
            "entities": [],
            "relations": [],
            "transfers": [
                {
                    "payer": "ALPHA CORP",
                    "payee": "BETA CORP",
                    "amount": 1000.0,
                    "currency": "EUR",
                },
                {"payer": "BETA CORP", "payee": "GAMMA CORP", "amount": 500.0, "currency": "USD"},
            ],
        }
    ]
    piece = PieceExtraction(
        piece_id="P1",
        file="P1.png",
        file_sha256="0" * 64,
        engine="test",
        doc_type="bank_statement",
        entities=[],
        relations=[],
        transfers=[
            GroundedTransfer(payer="ALPHA CORP", payee="BETA CORP", amount=1000.0, currency="GBP"),
            GroundedTransfer(payer="BETA CORP", payee="GAMMA CORP", amount=500.0, currency="USD"),
        ],
    )
    ev = evaluate_pieces([piece], truth)["all"]
    assert ev["transfers"]["recall"] == 1.0
    assert ev["transfers"]["precision"] == 1.0
    assert ev["transfers_currency"]["recall"] == 0.5


def test_build_document_graph_never_merges_person_and_company():
    piece1 = PieceExtraction(
        piece_id="PIECE-0001",
        file="PIECE-0001.png",
        file_sha256="1" * 64,
        engine="test",
        entities=[
            GroundedEntity(name="HERNANDEZ NOMINEES", kind="PersonnePhysique", grounded=True),
        ],
    )
    piece2 = PieceExtraction(
        piece_id="PIECE-0002",
        file="PIECE-0002.png",
        file_sha256="2" * 64,
        engine="test",
        entities=[
            GroundedEntity(name="HERNANDEZ NOMINEES", kind="Societe", grounded=True),
        ],
    )
    G, resolver = build_document_graph([piece1, piece2])
    assert G.number_of_nodes() == 2
    assert len(resolver.merge_history) == 0
