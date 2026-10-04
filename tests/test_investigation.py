import json
from pathlib import Path

import pytest
from test_documents import _icij_like, _oracle

from fin_enclave.documents.evaluation import evaluate_graph, evaluate_scenario
from fin_enclave.documents.forge import (
    anonymize_case,
    forge_dossier,
    scenario_path,
    select_case,
    truth_path,
)
from fin_enclave.documents.linker import build_document_graph
from fin_enclave.documents.models import (
    DocumentExtraction,
    ExtractedRelation,
    GroundedEntity,
    GroundedTransfer,
    PieceExtraction,
    StatementLine,
)
from fin_enclave.investigation import Investigation, analyse
from fin_enclave.reasoning.qualifier import _narration_is_faithful, qualify_findings
from fin_enclave.reporting import write_outputs


@pytest.fixture()
def money_dossier(tmp_path):
    out = tmp_path / "pieces"
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
    G, resolver, ledger, detection, findings = analyse(pieces)
    return Investigation(out, "oracle", pieces, G, resolver, ledger, detection, findings)


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
    # Même hub actionnaire : même alias
    assert anon[0]["officers"][0]["name"] == anon[0]["name"]
    assert anon[0]["officers"][1]["role"] == "director"
    assert anonymize_case(case, seed=7)[0]["name"] == anon[0]["name"]


def test_hidden_scenario_is_recovered_from_perfect_reading(money_dossier):
    out, truth, scenario = money_dossier
    inv = _investigation(out, _oracle(truth, out))
    ev = evaluate_scenario(inv.findings, scenario)
    assert ev["cycle_found"] and ev["spurious_cycles"] == 0
    assert ev["smurfing_found"] and ev["mules_found"] == 6
    assert ev["hidden_beneficiary_found"] and ev["top_money_is_beneficiary"]
    assert evaluate_graph(inv.graph, truth)["flows"]["recall"] == 1.0


def test_reports_are_built_from_facts_only(money_dossier, tmp_path):
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
    assert all(p.cote_judiciaire.startswith("PIECE-") for p in cycle.chain_of_custody)
    paths = write_outputs(inv, tmp_path / "out")
    md = paths["markdown"].read_text(encoding="utf-8")
    assert scenario["beneficiary"] in md and "PIECE-" in md
    assert paths["json"].with_suffix(".sha256").exists()


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


def test_statement_direction_comes_from_the_sign_not_the_model():
    ext = DocumentExtraction(
        doc_type="bank_statement",
        account_holder="HOLDER LTD",
        statement_lines=[
            StatementLine(date="25/04/2014", counterparty="MULE ONE", amount="9,317.00"),
            StatementLine(date="2014-04-29", counterparty="BOSS", amount="-50,225.00"),
            StatementLine(date="2014-04-01", counterparty="Opening balance", amount="80,000.00"),
            StatementLine(
                date="2014-04-25", counterparty="Transfer from Nadia Petrova", amount="9,317.00"
            ),
        ],
    )
    transfers = ext.resolved_transfers()
    assert len(transfers) == 3
    a, b, c = transfers
    assert (a.payer, a.payee, a.amount, a.date.isoformat()) == (
        "MULE ONE",
        "HOLDER LTD",
        9317.0,
        "2014-04-25",
    )
    assert (b.payer, b.payee, b.amount) == ("HOLDER LTD", "BOSS", 50225.0)
    assert (c.payer, c.payee) == ("Nadia Petrova", "HOLDER LTD")


def test_same_transfer_on_two_pieces_is_counted_once():
    t = {"payer": "ALPHA LTD", "payee": "BETA LTD", "amount": 1000.0, "date": "2014-01-02"}
    ents = [("ALPHA LTD", True), ("BETA LTD", True)]
    G, _, _ = build_document_graph(
        [_piece("PIECE-0001", ents, [t]), _piece("PIECE-0002", ents, [t], "bank_statement")]
    )
    ((_, _, e),) = [(u, v, d) for u, v, d in G.edges(data=True)]
    assert e["amount_usd"] == 1000.0
    assert e["transfers"][0]["corroborated_by"] == ["PIECE-0001", "PIECE-0002"]


def test_payment_pieces_never_create_governance_links():
    p = _piece("PIECE-0001", [("ALPHA LTD", True), ("BETA LTD", True)], [])
    p = p.model_copy(
        update={
            "relations": [ExtractedRelation(source="ALPHA LTD", target="BETA LTD", role="attorney")]
        }
    )
    G, _, _ = build_document_graph([p])
    assert G.number_of_edges() == 0


def test_unread_name_is_kept_only_if_attested_on_another_piece():
    photo = _piece("PIECE-0001", [("ALPHA LTD", False), ("GHOST LTD", False)], [])
    register = _piece("PIECE-0002", [("ALPHA LTD", True)], [], "register_of_directors")
    G, _, _ = build_document_graph([photo, register])
    names = {d["name"] for _, d in G.nodes(data=True)}
    assert "ALPHA LTD" in names and "GHOST LTD" not in names


def test_llm_note_citing_unknown_amount_is_rejected():
    allowed = {"2002500", "2014", "03", "26"}
    assert _narration_is_faithful("2,002,500 USD le 2014-03-26.", allowed)
    assert not _narration_is_faithful("2,500,000 USD ont transité.", allowed)
