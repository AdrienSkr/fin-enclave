"""Ticket 04 : lecteur de tableaux de relevés, routage par type de pièce, backends par tâche."""

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest
from openai import OpenAIError
from PIL import Image

from fin_enclave.config import Settings
from fin_enclave.documents.extractor import (
    RoutedEngine,
    extract_piece,
    statement_problem,
    vlm_schema,
)
from fin_enclave.documents.models import DocumentExtraction, StatementLine
from fin_enclave.documents.routing import route_piece, task_for
from fin_enclave.documents.statement_table import parse_statement
from fin_enclave.documents.table_engine import (
    OCR_PROMPT,
    TABLE_PROMPT,
    TableEngine,
)


@dataclass
class OcrWord:
    text: str
    confidence: float = 90.0
    box: tuple[int, int, int, int] = (0, 0, 0, 0)
    line_key: tuple[int, int, int] = (0, 0, 0)


@dataclass
class OcrPage:
    width: int
    height: int
    words: list[OcrWord] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines) if self.lines else " ".join(w.text for w in self.words)


FIXTURES = Path(__file__).parent / "fixtures" / "paddle"
DEPLOY = Path(__file__).parents[1] / "deploy" / "vllm_service.sh"


def raw_output(piece_id: str) -> str:
    """Section « Raw output » d'une fixture réelle PaddleOCR-VL-1.6."""
    text = (FIXTURES / f"{piece_id}.md").read_text(encoding="utf-8")
    match = re.search(r"## Raw output\s+```text\n(.*?)\n```", text, re.DOTALL)
    assert match, piece_id
    return match[1]


FIXTURE_IDS = sorted(p.stem for p in FIXTURES.glob("PIECE-*.md"))


# --- analyseur : validation groupée en-tête et mouvements par fixture ----------------------------


def test_statement_fixtures_parsing_and_reconciliation():
    """Vérifie l'extraction d'en-tête et des transactions réconciliées sur l'ensemble des fixtures."""
    for piece_id in FIXTURE_IDS:
        ext = parse_statement(raw_output(piece_id))
        assert ext.doc_type == "bank_statement", piece_id
        assert len(ext.account_holder) > 5, piece_id
        assert re.match(r"^[A-Z]{2}\d{2} ", ext.account_iban), piece_id
        assert ext.period_start and ext.period_end and ext.period_start < ext.period_end, piece_id
        assert ext.opening_balance is not None and ext.closing_balance is not None, piece_id
        assert len(ext.statement_lines) > 0, piece_id
        assert all(line.amount != 0 for line in ext.statement_lines), piece_id


def test_piece_0024_header_and_lines():
    ext = parse_statement(raw_output("PIECE-0024"))
    assert ext.account_holder == "Ironwood Ventures S.A."
    assert ext.account_iban == "GB29 MIDL 802866 8066C70E"
    assert (ext.period_start, ext.period_end) == (date(2022, 8, 24), date(2022, 11, 4))
    assert (ext.opening_balance, ext.closing_balance) == (944721.0, 944279.12)
    assert len(ext.statement_lines) == 10
    first = ext.statement_lines[0]
    assert (first.date, first.amount, first.counterparty) == (
        date(2022, 8, 24),
        -1850.0,
        "Bluefin Couriers Ltd",
    )
    assert first.balance == 942871.0 and first.repair == ""
    credit = ext.statement_lines[2]
    assert credit.amount == 17620.22 and credit.counterparty == "Willowmere Management Limited"
    assert ext.balance_reconciled is True and ext.balance_note == ""


def test_masked_amounts_are_repaired_by_the_balance_and_traced():
    ext = parse_statement(raw_output("PIECE-0024"))
    by_party = {line.counterparty: line for line in ext.statement_lines}
    truncated = by_party["Redwood Cleaning Ltd"]  # lu « 0,075.00 », vrai montant 8 075,00
    assert truncated.amount == -8075.0
    assert "0,075.00" in truncated.repair and "8075.00" in truncated.repair
    assert by_party["Pinewood Telecom Ltd"].amount == -9125.0  # lu « 125.00 »
    empty = by_party["Summit Cleaning Ltd"]  # cellule vide
    assert empty.amount == -9450.0 and "(vide)" in empty.repair
    assert sum(bool(line.repair) for line in ext.statement_lines) == 3


def test_spanish_statement_columns_and_labels():
    ext = parse_statement(raw_output("PIECE-0021"))
    assert ext.account_holder == "Seaglass Group Limited"
    assert ext.account_iban.startswith("ES91")
    assert ext.opening_balance == 676787.0
    # « 8,800.00 » lu pour 3 850,00 : sans rapport de chiffres, donc non réparé et signalé
    assert ext.balance_reconciled is False and "l'ouverture et la ligne 1" in ext.balance_note
    assert ext.statement_lines[0].amount == -8800.0 and ext.statement_lines[0].suspect


def test_unreconcilable_statement_is_flagged_not_forced():
    head, _, tail = raw_output("PIECE-0019").rpartition("1,139,878.72")  # solde de clôture
    raw = head + "1,139,000.00" + tail
    ext = parse_statement(raw)
    assert ext.balance_reconciled is False
    assert "clôture" in ext.balance_note


def test_unreconciled_statement_triage_and_review():
    ext_norepair = parse_statement(raw_output("PIECE-0024"), repair=False)
    assert ext_norepair.balance_reconciled is False
    assert "ligne possiblement manquante" in ext_norepair.balance_note
    assert len(ext_norepair.statement_lines) == 9  # la ligne sans montant est perdue
    assert -75.0 in [line.amount for line in ext_norepair.statement_lines]
    assert "soldes non réconciliés" in statement_problem(ext_norepair, None)
    assert statement_problem(parse_statement(raw_output("PIECE-0024")), None) == ""


def test_empty_or_unmovement_rows_handling():
    # Lignes sans mouvement ignorées
    ext_unmov = parse_statement(raw_output("PIECE-0019"))
    assert all(line.amount != 0 for line in ext_unmov.statement_lines)

    # Absence totale de tableau
    ext_notable = parse_statement("## STATEMENT OF ACCOUNT\n\nAccount holder: Acme Ltd\n")
    assert ext_notable.balance_reconciled is False and ext_notable.account_holder == "Acme Ltd"
    assert ext_notable.statement_lines == []


def test_statement_currency_printed_vs_unprinted():
    # Devise imprimée explicitement
    raw_eur = "Currency: EUR\n\n" + raw_output("PIECE-0024")
    ext_eur = parse_statement(raw_eur)
    assert ext_eur.header_currency == "EUR"
    assert {line.currency for line in ext_eur.statement_lines} == {"EUR"}

    # Règle 5 : Sans devise explicite, header_currency n'est jamais inventée
    ext_none = parse_statement(raw_output("PIECE-0024"))
    assert ext_none.header_currency == ""


def test_resolved_transfers_follow_the_signed_lines():
    ext = parse_statement(raw_output("PIECE-0024"))
    transfers = ext.resolved_transfers()
    assert len(transfers) == 10
    debit = next(t for t in transfers if t.payee == "Redwood Cleaning Ltd")
    assert (debit.payer, debit.amount) == ("Ironwood Ventures S.A.", 8075.0)


def _without_row(raw: str, index: int) -> str:
    """Le tableau sans sa `index`-ième ligne de mouvement (0 = première après l'ouverture)."""
    rows = re.findall(r"<tr>.*?</tr>", raw, re.DOTALL)
    return raw.replace(rows[2 + index], "", 1)  # 0 = en-tête, 1 = ouverture


def test_a_missing_row_is_never_absorbed_by_the_next_line():
    """Fuzzing ciblé sur 2 fixtures représentatives : une ligne sautée déclenche l'alerte."""
    for piece_id in ["PIECE-0019", "PIECE-0024"]:
        raw = raw_output(piece_id)
        reference = parse_statement(raw)
        n_rows = len(reference.statement_lines)
        for index in range(n_rows):
            following = reference.statement_lines[index + 1 : index + 2]
            if following and "(vide)" in following[0].repair:
                continue
            ext = parse_statement(_without_row(raw, index))
            assert ext.balance_reconciled is False, (piece_id, index)
            assert "ligne possiblement manquante" in ext.balance_note
            assert "soldes non réconciliés" in statement_problem(ext, None)
            already = sum(bool(line.suspect) for line in reference.statement_lines)
            assert sum(bool(line.suspect) for line in ext.statement_lines) <= already + 1
            original = {(line.date, line.amount) for line in reference.statement_lines}
            original_repairs = {(x.date, x.amount) for x in reference.statement_lines if x.repair}
            for line in ext.statement_lines:
                assert (line.date, line.amount) in original or line.suspect, (piece_id, index)
                assert not line.repair or (line.date, line.amount) in original_repairs


def test_missing_row_flagging_and_witness_detection():
    # 1. Montant absent réparé par solde mais capté par le décompte de témoins OCR
    raw = raw_output("PIECE-0024")
    ext_rep = parse_statement(_without_row(raw, 8))
    assert ext_rep.balance_reconciled is True
    rows = "\n".join(
        f"{d:02d}/09/2022 Libelle numero {d} paye 1,000.00 5,000.00" for d in range(1, 11)
    )
    problem = statement_problem(
        ext_rep, _page(f"STATEMENT OF ACCOUNT Date Debit Credit Balance\n{rows}")
    )
    assert "9 lignes" in problem and "10 lignes datées" in problem

    # 2. Ligne manquante signalée entre ses deux voisines
    ext_flag = parse_statement(_without_row(raw, 1))
    assert ext_flag.balance_reconciled is False
    assert "entre la ligne 1 et la ligne 2" in ext_flag.balance_note
    line = next(line for line in ext_flag.statement_lines if line.counterparty.startswith("Willow"))
    assert (
        line.amount == 17620.22
        and line.repair == ""
        and "ligne possiblement manquante" in line.suspect
    )
    assert len(ext_flag.statement_lines) == 9


def test_witness_dated_rows_validation():
    ext = parse_statement(raw_output("PIECE-0024"))
    rows = "\n".join(
        f"{d:02d}/09/2022 Libelle numero {d} paye 1,000.00 5,000.00" for d in range(1, 12)
    )
    problem = statement_problem(
        ext, _page(f"STATEMENT OF ACCOUNT Date Debit Credit Balance\n{rows}")
    )
    assert "11 lignes datées" in problem and "10 lignes" in problem
    ten = "\n".join(rows.splitlines()[:10])
    assert (
        statement_problem(ext, _page(f"STATEMENT OF ACCOUNT Date Debit Credit Balance\n{ten}"))
        == ""
    )

    # Ne s'applique pas aux extractions hors tableau
    old = DocumentExtraction(
        doc_type="bank_statement",
        account_holder="Acme Ltd",
        statement_lines=[StatementLine(counterparty="Beta SA", amount=-10.0)],
    )
    assert statement_problem(old, _page(f"STATEMENT OF ACCOUNT Date Debit\n{rows}")) == ""


# --- schéma rétrocompatible --------------------------------------------------------------------


def test_statement_model_and_schema_compatibility():
    # Relecture d'un scellé ancien format
    sealed = {
        "doc_type": "bank_statement",
        "account_holder": "Acme Ltd",
        "statement_lines": [{"date": "2022-01-05", "counterparty": "Beta SA", "amount": -10.0}],
    }
    ext = DocumentExtraction.model_validate_json(json.dumps(sealed))
    assert ext.statement_lines[0].balance is None and ext.statement_lines[0].repair == ""
    assert ext.account_iban == "" and ext.period_start is None and ext.balance_reconciled is None
    assert statement_problem(ext, None) == ""

    # Schéma VLM masquant les champs internes
    schema = vlm_schema()
    assert "raw_output" not in schema["properties"]
    assert "balance_reconciled" not in schema["properties"]
    assert "account_iban" in schema["properties"]
    line_props = schema["$defs"]["StatementLine"]["properties"]
    assert (
        "repair" not in line_props and "description" not in line_props and "balance" in line_props
    )

    # Ligne avec solde textuel
    line = StatementLine(counterparty="Beta SA", amount="-1,250.00", balance="10,000.00")
    assert (line.amount, line.balance) == (-1250.0, 10000.0)


# --- routage -----------------------------------------------------------------------------------


def _page(text: str) -> OcrPage:
    words = []
    lines = text.strip().splitlines()
    for row, line in enumerate(lines):
        for col, token in enumerate(line.split()):
            words.append(
                OcrWord(
                    token, 90.0, (col * 50, row * 20, col * 50 + 40, row * 20 + 15), (1, 1, row)
                )
            )
    return OcrPage(1000, 1000, words, lines=lines)


STATEMENT_PAGE = """
STATEMENT OF ACCOUNT
Account holder: Ironwood Ventures S.A.
Account number: GB29 MIDL 802866 8066C70E
Date Description Debit Credit Balance
24/08/2022 Office supplies Bluefin Couriers Ltd 1,850.00 942,871.00
"""
UNTITLED_PAGE = """
Ironwood Ventures account activity for the quarter under review in the file
Date Description Debit Credit Balance
24/08/2022 Office supplies 1,850.00 942,871.00
30/08/2022 Logistics 4,225.00 938,646.00
"""
SPANISH_PAGE = """
EXTRACTO DE CUENTA
Titular de la cuenta: Seaglass Group Limited Periodo 27/08/2022 20/09/2022 pagina uno
"""
DEED_PAGE = """
CERTIFICATE OF INCORPORATION
We hereby certify that Amberfield Partners Ltd. was incorporated on 12/03/2014
Registered agent: Coral Fiduciary Services Ltd. Shareholder: Oakridge Enterprises Limited
"""
INVOICE_PAGE = """
INVOICE No 4471 dated 12/03/2014 issued by Harbour Printing Ltd to Bill to: Acme Ltd
Item one printing services amount 1,200.00 Total due 1,200.00 Balance due 1,200.00 thanks
"""


def test_routing_by_witness_and_defaults():
    cases = [
        (STATEMENT_PAGE, "statement"),
        (UNTITLED_PAGE, "statement"),
        (SPANISH_PAGE, "statement"),
        (DEED_PAGE, "deed"),
        (INVOICE_PAGE, "deed"),
    ]
    for page, kind in cases:
        assert route_piece(_page(page)) == kind

    assert route_piece(None) == "deed"
    assert route_piece(_page("illisible")) == "deed"
    assert (task_for("statement"), task_for("deed")) == ("T2", "T1")


# --- configuration -----------------------------------------------------------------------------


def test_settings_custom_base_url_and_api_key():
    s = Settings(_env_file=None, llm_base_url="http://custom:1234/v1", llm_api_key="secret")
    assert s.get_effective_base_url() == "http://custom:1234/v1"
    assert s.get_effective_api_key() == "secret"


# --- adaptateur T2 -----------------------------------------------------------------------------


class _Message:
    def __init__(self, content: str):
        self.content = content


class _Completion:
    def __init__(self, content: str):
        self.choices = [type("C", (), {"message": _Message(content)})()]


class FakeClient:
    """Client OpenAI factice : répond selon l'invite, sans réseau."""

    def __init__(self, raw: str, fail: bool = False):
        self.calls: list[dict] = []
        self.raw, self.fail = raw, fail
        self.chat = type("Chat", (), {"completions": self})()

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise OpenAIError("serveur indisponible")
        prompt = kwargs["messages"][0]["content"][1]["text"]
        head, _, table = self.raw.partition("<table")
        return _Completion(head if prompt == OCR_PROMPT else "<table" + table)


def test_table_engine_prompts_slug_and_error_handling():
    # Requêtes Paddle prompts
    client = FakeClient(raw_output("PIECE-0024"))
    engine = TableEngine("PaddlePaddle/PaddleOCR-VL-1.6", client=client)
    ext = engine.extract(Image.new("RGB", (800, 1100), "white"), None)
    assert [c["messages"][0]["content"][1]["text"] for c in client.calls] == [
        OCR_PROMPT,
        TABLE_PROMPT,
    ]
    assert all(
        c["model"] == "PaddlePaddle/PaddleOCR-VL-1.6" and c["temperature"] == 0.0
        for c in client.calls
    )
    assert client.calls[0]["messages"][0]["content"][0]["image_url"]["url"].startswith(
        "data:image/jpeg;base64,"
    )
    assert ext.account_holder == "Ironwood Ventures S.A." and len(ext.statement_lines) == 10
    assert "<table" in ext.raw_output and "Table Recognition" not in ext.raw_output

    # Slug selon version et modèle
    b = TableEngine("autre/modele", client=FakeClient(""))
    assert engine.slug.startswith("table-paddlepaddle-paddleocr-vl-1-6-p") and engine.slug != b.slug

    # Erreur d'indisponibilité
    err_engine = TableEngine("m", client=FakeClient("", fail=True))
    with pytest.raises(RuntimeError, match="indisponible"):
        err_engine.extract(Image.new("RGB", (10, 10)), None)


# --- intégration : routage + scellé ------------------------------------------------------------


class _DeedEngine:
    name = "vlm"
    slug = "vlm-deed-test"

    def extract(self, img, *args, **kwargs):
        return DocumentExtraction(doc_type="bank_statement")


@pytest.fixture
def statement_png(tmp_path):
    path = tmp_path / "PIECE-0024.png"
    Image.new("RGB", (400, 500), "white").save(path)
    return path


def test_routed_engine_reads_statements_with_t2_and_seals_the_raw_output(statement_png, tmp_path):
    cache = tmp_path / "cache"
    table = TableEngine("m", client=FakeClient(raw_output("PIECE-0024")))
    engine = RoutedEngine(_DeedEngine(), table)
    piece = extract_piece(statement_png, engine, cache_dir=cache)
    assert piece.doc_type == "bank_statement" and not piece.needs_review
    assert len(piece.transfers) == 10
    assert piece.account_iban == "GB29 MIDL 802866 8066C70E"
    assert (piece.period_start, piece.period_end) == (date(2022, 8, 24), date(2022, 11, 4))
    sealed = list(cache.glob("*.json"))
    assert len(sealed) == 1 and table.slug in sealed[0].name
    assert "Table Recognition" not in sealed[0].read_text(encoding="utf-8")
    assert "<table" in json.loads(sealed[0].read_text(encoding="utf-8"))["raw_output"]
    # rejeu : aucun appel au lecteur
    replay = RoutedEngine(_DeedEngine(), TableEngine("m", client=FakeClient("", fail=True)))
    again = extract_piece(statement_png, replay, cache_dir=cache)
    assert again.from_cache and len(again.transfers) == 10


def test_unreconciled_page_is_flagged_and_not_sealed(statement_png, tmp_path):
    cache = tmp_path / "cache"
    broken = raw_output("PIECE-0024").replace(
        "944,279.12</td></tr></table>", "900,000.00</td></tr></table>"
    )
    client = FakeClient(broken)
    piece = extract_piece(
        statement_png, RoutedEngine(_DeedEngine(), TableEngine("m", client=client)), cache_dir=cache
    )
    assert piece.needs_review and "soldes non réconciliés" in piece.review_reason
    assert not list(cache.glob("*.json"))
    assert len(client.calls) == 2  # pas de relance d'une lecture déterministe


def test_routed_engine_routing_and_fallbacks(tmp_path):
    deed, table = _DeedEngine(), TableEngine("m", client=FakeClient(""))
    assert RoutedEngine(deed, table).engine_for(_page(DEED_PAGE)) is deed
    assert RoutedEngine(deed, table).engine_for(_page(STATEMENT_PAGE)) is table
    assert RoutedEngine(deed).engine_for(_page(STATEMENT_PAGE)) is deed
    assert table.slug in RoutedEngine(deed, table).slug

    # Image brute sans aucun texte OCR témoin
    path = tmp_path / "raw_statement.png"
    Image.new("RGB", (200, 200), "white").save(path)
    table_raw = TableEngine("m", client=FakeClient(raw_output("PIECE-0024")))
    engine = RoutedEngine(_DeedEngine(), table_raw)
    piece = extract_piece(path, engine, use_cache=False)
    assert piece.doc_type == "bank_statement"
    assert len(piece.transfers) == 10
    assert piece.account_iban == "GB29 MIDL 802866 8066C70E"


def test_single_column_statement_parsing():
    raw = '''
Account holder: Northwind Group S.A.
Account number: PA12 3456 ****
Period: 01/04/2022 - 30/04/2022

<table border=1>
<tr><td>Date</td><td>Description</td><td>Amount (USD)</td></tr>
<tr><td></td><td>Opening balance</td><td>50,000.00</td></tr>
<tr><td>05/04/2022</td><td>Transfer to Alice Corp</td><td>-9,400.00</td></tr>
<tr><td>12/04/2022</td><td>Transfer from Bob Ltd</td><td>4,500.00</td></tr>
<tr><td></td><td>Closing balance</td><td>45,100.00</td></tr>
</table>
'''
    ext = parse_statement(raw)
    assert ext.doc_type == "bank_statement"
    assert ext.account_holder == "Northwind Group S.A."
    assert ext.opening_balance == 50000.0
    assert ext.closing_balance == 45100.0
    assert len(ext.statement_lines) == 2
    assert ext.balance_reconciled is True
    tx = ext.resolved_transfers()
    assert len(tx) == 2
    assert tx[0].payer == "Northwind Group S.A." and tx[0].payee == "Alice Corp" and tx[0].amount == 9400.0
    assert tx[1].payer == "Bob Ltd" and tx[1].payee == "Northwind Group S.A." and tx[1].amount == 4500.0


def test_resolved_transfers_with_fallback_holder():
    from fin_enclave.documents.models import ExtractedEntity
    ext = DocumentExtraction(
        doc_type="bank_statement",
        statement_lines=[
            StatementLine(date=date(2022, 4, 5), counterparty="Alice Corp", amount=-9400.0, currency="USD"),
        ],
        entities=[ExtractedEntity(name="Fallback Corp", kind="Societe")],
    )
    tx = ext.resolved_transfers()
    assert len(tx) == 1
    assert tx[0].payer == "Fallback Corp"
    assert tx[0].payee == "Alice Corp"
    assert tx[0].amount == 9400.0


def test_routed_engine_falls_back_to_vlm_when_table_empty():
    from fin_enclave.documents.models import ExtractedTransfer
    class _EmptyTableEngine:
        name = "table"
        slug = "table-empty"
        def extract(self, img, *args, **kwargs):
            return DocumentExtraction(doc_type="bank_statement", statement_lines=[])

    class _VlmWithTransfers:
        name = "vlm"
        slug = "vlm-transfers"
        def extract(self, img, *args, **kwargs):
            return DocumentExtraction(
                doc_type="bank_statement",
                transfers=[ExtractedTransfer(payer="A", payee="B", amount=100.0, currency="USD")],
            )

    engine = RoutedEngine(_VlmWithTransfers(), _EmptyTableEngine())
    result = engine.extract(Image.new("RGB", (100, 100), "white"))
    assert len(result.transfers) == 1
    assert result.transfers[0].amount == 100.0
