import csv
import json
from datetime import date
from pathlib import Path

import pytest
from PIL import Image
from test_documents import _icij_like, _oracle

from fin_enclave.analyst import build_analyst_view
from fin_enclave.documents.evaluation import evaluate_graph, evaluate_scenario
from fin_enclave.documents.forge import (
    anonymize_case,
    forge_dossier,
    scenario_path,
    select_case,
    truth_path,
)
from fin_enclave.documents.models import (
    DocumentExtraction,
    ExtractedRelation,
    ExtractedTransfer,
    GroundedEntity,
    GroundedTransfer,
    PieceExtraction,
)
from fin_enclave.exports import write_exports
from fin_enclave.graph.structural import build_portfolios
from fin_enclave.investigation import Investigation, analyse, investigate
from fin_enclave.reasoning.qualifier import (
    compute_piece_confidence,
    qualify_findings,
)
from fin_enclave.reporting import render_markdown, write_outputs

ALPHA = "ALPHA TRADING LTD"
BETA = "BETA HOLDINGS SA"
GAMMA = "GAMMA CONSULTING LLC"
DELTA = "DELTA HOLDING CORP"
EPSILON = "EPSILON SERVICES LTD"
ZETA = "ZETA RETAIL LTD"
MARIE = "MARIE LEROY"


@pytest.fixture(scope="module")
def money_dossier(tmp_path_factory):
    out = tmp_path_factory.mktemp("money_inv") / "pieces"
    forge_dossier(
        select_case(_icij_like(), "H", n_companies=6, seed=1),
        out,
        3,
        seed=1,
        anonymize=False,
    )
    truth = json.loads(truth_path(out).read_text(encoding="utf-8"))
    scenario = json.loads(scenario_path(out).read_text(encoding="utf-8"))
    return out, truth, scenario


def _investigation(out: Path, pieces) -> Investigation:
    G, resolver, detection, findings = analyse(pieces)
    return Investigation(out, "oracle", pieces, G, resolver, detection, findings)


def _piece(pid: str, entities, transfers, doc_type="wire_transfer") -> PieceExtraction:
    return PieceExtraction(
        piece_id=pid,
        file=f"{pid}.png",
        file_sha256=pid[-1] * 64,
        engine="t",
        doc_type=doc_type,
        entities=[GroundedEntity(name=n, kind="Societe", grounded=g) for n, g in entities],
        transfers=[GroundedTransfer(**t) for t in transfers],
    )


# --- Seam 4: Investigation, Constats, Base Légale & Livrables ---


def test_anonymize_case_keeps_topology_and_drops_real_names():
    case = [
        {
            "node": "c1",
            "name": "MAYTREE OVERSEAS S.A.",
            "jurisdiction": "BVI",
            "incorporated": "2001",
            "intermediary": "LARSSEN CORPORATE SERVICES S.A.",
            "officers": [
                {"name": "MAYTREE OVERSEAS S.A.", "role": "shareholder"},
                {"name": "John Realperson", "role": "director"},
            ],
        }
    ]
    anon = anonymize_case(case, seed=7)
    assert anon[0]["name"] != "MAYTREE OVERSEAS S.A."
    assert "MAYTREE" not in anon[0]["name"].upper()
    assert anon[0]["intermediary"] != "LARSSEN CORPORATE SERVICES S.A."
    assert anon[0]["officers"][0]["name"] == anon[0]["name"]
    assert anon[0]["officers"][1]["role"] == "director"


def test_hidden_scenario_is_recovered_from_perfect_reading(money_dossier):
    out, truth, scenario = money_dossier
    inv = _investigation(out, _oracle(truth, out))
    ev = evaluate_scenario(inv.findings, scenario)
    assert ev["cycle_found"] and ev["spurious_cycles"] == 0
    assert ev["smurfing_found"] and ev["mules_found"] == 6
    assert ev["hidden_beneficiary_found"] and ev["top_money_is_beneficiary"]
    assert evaluate_graph(inv.graph, truth)["flows"]["recall"] == 1.0


def test_qualify_findings_produces_fact_based_legal_reports(money_dossier, tmp_path):
    out, truth, scenario = money_dossier
    inv = _investigation(out, _oracle(truth, out))
    inv.reports = qualify_findings(inv)
    kinds = {r.infraction_type for r in inv.reports}
    assert kinds == {
        "BLANCHIMENT_CYCLE_FERME",
        "FRACTIONNEMENT_SCHTROUMPFAGE",
        "DISSIMULATION_UBO_PRETE_NOM",
    }
    cycle = next(r for r in inv.reports if r.infraction_type == "BLANCHIMENT_CYCLE_FERME")
    entry = scenario["cycle_transfers"][0]["amount"]
    assert cycle.total_amount_usd == pytest.approx(entry)
    assert f"{entry:,.0f}" in cycle.summary_note

    for r in inv.reports:
        assert "```json" not in r.summary_note
        assert "{" not in r.summary_note
        assert len(r.legal_basis) >= 1
        assert any("Code" in b or "GAFI" in b for b in r.legal_basis)

    paths = write_outputs(inv, tmp_path / "out")
    md = paths["markdown"].read_text(encoding="utf-8")
    assert scenario["beneficiary"] in md and "PIECE-" in md


def test_piece_confidence_for_statement_and_deed():
    clean_statement = PieceExtraction(
        piece_id="PIECE-0001",
        file="s.png",
        file_sha256="0" * 64,
        engine="table",
        doc_type="bank_statement",
        balance_reconciled=True,
        transfers=[GroundedTransfer(payer="A", payee="B", amount=100.0, date="2022-01-01")],
    )
    assert compute_piece_confidence(clean_statement) == 1.0

    bad_statement = PieceExtraction(
        piece_id="PIECE-0002",
        file="s2.png",
        file_sha256="0" * 64,
        engine="table",
        doc_type="bank_statement",
        balance_reconciled=False,
        needs_review=True,
        review_reason="soldes non réconciliés: écart 500",
        transfers=[GroundedTransfer(payer="A", payee="B", amount=100.0, date="2022-01-01")],
    )
    assert compute_piece_confidence(bad_statement) == 0.0

    clean_deed = PieceExtraction(
        piece_id="PIECE-0003",
        file="d.png",
        file_sha256="0" * 64,
        engine="vlm",
        doc_type="register_of_directors",
        entities=[GroundedEntity(name="ACME LTD", kind="Societe", grounded=True)],
    )
    assert compute_piece_confidence(clean_deed) == 1.0


def test_exports_neo4j_csv_and_graphml(tmp_path):
    class FixedEngine:
        name = "fake"
        slug = "fake-export"

        def extract(self, img, ocr, retry=False):
            return DocumentExtraction(
                doc_type="wire_transfer",
                entities=[
                    GroundedEntity(name="Alpha Holdings Ltd", kind="Societe"),
                    GroundedEntity(name="Beta Trading SA", kind="Societe"),
                ],
                transfers=[
                    ExtractedTransfer(
                        payer="Alpha Holdings Ltd",
                        payee="Beta Trading SA",
                        amount=1500,
                        currency="USD",
                    )
                ],
            )

    dossier = tmp_path / "dossier"
    dossier.mkdir()
    Image.new("L", (100, 100), 255).save(dossier / "PIECE-0001.png")

    inv = investigate(dossier, FixedEngine(), cache_dir=tmp_path / "cache")
    out = tmp_path / "out"
    write_outputs(inv, out)
    write_exports(inv, out)

    with (out / "noeuds.csv").open(encoding="utf-8", newline="") as f:
        nodes = list(csv.DictReader(f))
    with (out / "aretes.csv").open(encoding="utf-8", newline="") as f:
        edges = list(csv.DictReader(f))

    assert len(nodes) == 2
    assert len(edges) == 1
    assert (out / "graphe.graphml").exists()
    assert (out / "graphe.html").exists()
    assert (out / "rapport.md").exists()


# --- Analyst View & Investigations ---


def _analyst_pieces() -> list[PieceExtraction]:
    return [
        PieceExtraction(
            piece_id="PIECE-0003",
            file="PIECE-0003.png",
            file_sha256="3" * 64,
            engine="t",
            doc_type="wire_transfer",
            entities=[
                GroundedEntity(name=GAMMA, kind="Societe", grounded=True),
                GroundedEntity(name=ALPHA, kind="Societe", grounded=True),
            ],
            transfers=[
                GroundedTransfer(
                    payer=GAMMA, payee=ALPHA, amount=49000, date="2014-01-15", amount_grounded=True
                )
            ],
        ),
        PieceExtraction(
            piece_id="PIECE-0001",
            file="PIECE-0001.png",
            file_sha256="1" * 64,
            engine="t",
            doc_type="wire_transfer",
            entities=[
                GroundedEntity(name=ALPHA, kind="Societe", grounded=True),
                GroundedEntity(name=BETA, kind="Societe", grounded=True),
            ],
            transfers=[
                GroundedTransfer(
                    payer=ALPHA, payee=BETA, amount=50000, date="2014-01-05", amount_grounded=True
                )
            ],
        ),
        PieceExtraction(
            piece_id="PIECE-0002",
            file="PIECE-0002.png",
            file_sha256="2" * 64,
            engine="t",
            doc_type="wire_transfer",
            entities=[
                GroundedEntity(name=BETA, kind="Societe", grounded=True),
                GroundedEntity(name=GAMMA, kind="Societe", grounded=True),
            ],
            transfers=[
                GroundedTransfer(
                    payer=BETA, payee=GAMMA, amount=49500, date="2014-01-10", amount_grounded=True
                )
            ],
        ),
        PieceExtraction(
            piece_id="PIECE-0004",
            file="PIECE-0004.png",
            file_sha256="4" * 64,
            engine="t",
            doc_type="bank_statement",
            account_holder=ALPHA,
            account_iban="GB29 MIDL 802866 8066C70E",
            bank="Midland Bank",
            period_start=date(2014, 1, 1),
            period_end=date(2014, 1, 31),
            entities=[
                GroundedEntity(name=ALPHA, kind="Societe", grounded=True),
                GroundedEntity(name=BETA, kind="Societe", grounded=True),
                GroundedEntity(name=GAMMA, kind="Societe", grounded=True),
            ],
            transfers=[
                GroundedTransfer(
                    payer=ALPHA, payee=BETA, amount=50000, date="2014-01-05", amount_grounded=True
                ),
                GroundedTransfer(
                    payer=GAMMA, payee=ALPHA, amount=49000, date="2014-01-15", amount_grounded=True
                ),
            ],
        ),
        PieceExtraction(
            piece_id="PIECE-0005",
            file="PIECE-0005.png",
            file_sha256="5" * 64,
            engine="t",
            doc_type="wire_transfer",
            entities=[
                GroundedEntity(name=ALPHA, kind="Societe", grounded=True),
                GroundedEntity(name=EPSILON, kind="Societe", grounded=True),
            ],
            transfers=[
                GroundedTransfer(
                    payer=ALPHA, payee=EPSILON, amount=1200, date="2014-06-01", amount_grounded=True
                )
            ],
        ),
        PieceExtraction(
            piece_id="PIECE-0006",
            file="PIECE-0006.png",
            file_sha256="6" * 64,
            engine="t",
            doc_type="wire_transfer",
            entities=[
                GroundedEntity(name=ZETA, kind="Societe", grounded=True),
                GroundedEntity(name=EPSILON, kind="Societe", grounded=True),
            ],
            transfers=[
                GroundedTransfer(
                    payer=ZETA,
                    payee=EPSILON,
                    amount=900000,
                    date="2014-02-01",
                    amount_grounded=True,
                )
            ],
        ),
        PieceExtraction(
            piece_id="PIECE-0007",
            file="PIECE-0007.png",
            file_sha256="7" * 64,
            engine="t",
            doc_type="register_of_shareholders",
            entities=[
                GroundedEntity(name=ALPHA, kind="Societe", grounded=True),
                GroundedEntity(name=DELTA, kind="Societe", grounded=True),
                GroundedEntity(name=MARIE, kind="PersonnePhysique", grounded=True),
            ],
            relations=[
                ExtractedRelation(source=DELTA, target=ALPHA, role="shareholder"),
                ExtractedRelation(source=MARIE, target=DELTA, role="beneficial_owner"),
            ],
        ),
    ]


def test_timeline_is_sorted_and_cited():
    pieces = _analyst_pieces()
    G, _resolver, detection, findings = analyse(pieces)
    view = build_analyst_view(G, findings, pieces, detection)
    rows = view["timeline"]
    assert [r["date"] for r in rows] == sorted(r["date"] for r in rows)
    assert [r["date"] for r in rows] == ["2014-01-05", "2014-01-10", "2014-01-15"]
    assert (rows[0]["from"], rows[0]["to"], rows[0]["amount_usd"]) == (ALPHA, BETA, 50000.0)
    assert "PIECE-0001" in rows[0]["pieces"]


def test_requisition_checks():
    pieces = _analyst_pieces()
    G, _resolver, detection, findings = analyse(pieces)
    view = build_analyst_view(G, findings, pieces, detection)
    parties = {r["account"]: r for r in view["requisitions"]}
    assert BETA in parties and "aucun relevé" in parties[BETA]["reason"]
    assert "PIECE-0002" in parties[BETA]["cited_by"]
    alpha = [r for r in view["requisitions"] if r["account"] == ALPHA]
    assert len(alpha) == 1
    assert "période non couverte" in alpha[0]["reason"]
    assert alpha[0]["iban"] == "GB29 MIDL 802866 8066C70E"
    assert alpha[0]["bank"] == "Midland Bank"


def test_control_chain_and_priorities():
    pieces = _analyst_pieces()
    G, _resolver, detection, findings = analyse(pieces)
    view = build_analyst_view(G, findings, pieces, detection)
    chains = {c["company"]: c for c in view["control_chains"]}
    alpha_chain = chains[ALPHA]["chains"][0]
    assert alpha_chain["path"] == [ALPHA, DELTA, MARIE]
    assert alpha_chain["ubo"] == MARIE and alpha_chain["complete"] is True
    ranking = view["priorities"]["entities"]
    for row in ranking:
        assert row["score"] == pytest.approx(sum(row["breakdown"].values()), abs=0.01)


# --- Portfolio Nominee Legal Tests ---


def _holder(actor, role, company):
    return {"name": actor, "id": actor, "role": role, "pieces": ["PIECE-0001"], "company": company}


def _ownership(role: str, n: int, actor: str = "ALICE MARTIN") -> list[dict]:
    return [
        {"company": f"CO {i} LTD", "id": f"c{i}", "holders": [_holder(actor, role, f"c{i}")]}
        for i in range(n)
    ]


@pytest.mark.parametrize(
    ("role", "expected_nominee"),
    [
        ("beneficial_owner", False),
        ("director", True),
    ],
)
def test_build_portfolios_nominee_profile_by_role(role, expected_nominee):
    folios = build_portfolios(_ownership(role, 4))
    alice = next(a for a in folios if a["name"] == "ALICE MARTIN")
    assert alice["n_companies"] == 4
    assert alice["nominee_profile"] is expected_nominee


def test_report_structure_order(tmp_path):
    pieces = _piece(
        "PIECE-0001",
        [(ALPHA, True), (BETA, True)],
        [{"payer": ALPHA, "payee": BETA, "amount": 1000.0, "date": "2020-01-01"}],
    )
    inv = _investigation(tmp_path, [pieces])
    md = render_markdown(inv, tmp_path / "out", None)
    order = [
        md.index("## 1. Synthèse"),
        md.index("## 2. Constats"),
        md.index("## 3. Entités"),
        md.index("## 4. À valider"),
        md.index("## 5. Annexes"),
    ]
    assert order == sorted(order)
