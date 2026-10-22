"""
Analyseur déterministe d'un relevé lu comme tableau (sortie markdown / HTML de PaddleOCR-VL).

Entrée : le texte brut du lecteur (en-tête en markdown, puis un `<table>` Date / Description /
Débit / Crédit / Solde). Sortie : un `DocumentExtraction` de relevé (titulaire, IBAN, banque,
période, devise d'en-tête, soldes, lignes signées). Aucun modèle, aucun réseau.

Réconciliation des soldes : le solde imprimé après chaque ligne atteste du mouvement
(`solde - solde précédent`). Un montant lu incohérent avec cette différence (préfixe masqué par le
libellé, cellule vide) est réparé par la différence, et la réparation est tracée dans la ligne.
Un relevé dont la chaîne de soldes ne se referme pas sur le solde de clôture est marqué non
réconcilié : la pièce part en relecture au lieu d'être scellée.
"""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from .models import (
    DocumentExtraction,
    ExtractedEntity,
    StatementLine,
    clean_counterparty,
    parse_amount,
    parse_date,
)

PARSER_VERSION = "1"
TOLERANCE = 0.005  # un demi-centime : écart d'arrondi flottant toléré

_CURRENCY_RE = re.compile(r"\b(USD|EUR|GBP|CHF)\b")
_COMPANY_RE = re.compile(
    r"\b(LIMITED|LTD\.?|INC\.?|CORP\.?|CORPORATION|S\.?A\.?|LLC|PTE\.?|PLC|N\.V\.|B\.V\.|"
    r"FOUNDATION|TRUST|HOLDINGS?)\s*$",
    re.IGNORECASE,
)

# Libellés d'en-tête (FR / EN / ES) -> champ
_HEADER_LABELS = {
    "holder": r"Account holder|Titulaire(?: du compte)?|Titular(?: de la cuenta)?",
    "iban": r"Account number|IBAN|Num\w*ro de compte|N\w*mero de cuenta",
    "bank": r"Bank|Banque|Banco",
    "period": r"Period|P[ée]riode|Periodo|Per[íi]odo",
    "currency": r"Currency|Devise|Moneda",
}
_COLUMN_WORDS = {
    "date": ("date", "fecha"),
    "description": ("description", "libelle", "libellé", "descripcion", "concepto", "details"),
    "debit": ("debit", "débit", "debito", "débito", "debe"),
    "credit": ("credit", "crédit", "credito", "crédito", "haber"),
    "amount": ("amount", "montant", "importe", "betrag", "valeur"),
    "balance": ("balance", "solde", "saldo"),
}
_OPENING = ("opening balance", "solde initial", "solde d'ouverture", "saldo inicial")
_CLOSING = ("closing balance", "solde final", "solde de clôture", "saldo final")
_NUMERIC_RE = re.compile(r"^-?\(?\d[\d.,' \u00a0]*\)?$")


class _TableParser(HTMLParser):
    """Collecte les tableaux HTML : liste de tableaux, chacun liste de lignes de cellules."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None and self.tables:
            self.tables[-1].append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def html_tables(raw: str) -> list[list[list[str]]]:
    parser = _TableParser()
    parser.feed(raw)
    parser.close()
    return parser.tables


def _norm(text: str) -> str:
    return re.sub(r"[^a-zàâçéèêëîïôûùüœñáíóú' ]", "", text.lower()).strip()


def _column_map(row: list[str]) -> dict[str, int] | None:
    """Indice de chaque colonne reconnue ; None si ce n'est pas un en-tête de relevé."""
    found: dict[str, int] = {}
    for i, cell in enumerate(row):
        word = _norm(cell)
        for kind, names in _COLUMN_WORDS.items():
            hit = any(n in word for n in names) if kind in ("description", "amount") else word in names
            if hit and kind not in found:
                found[kind] = i
    # Cas 1 : Table classique avec colonnes débit/crédit et solde
    if {"date", "balance"} <= found.keys() and ("debit" in found or "credit" in found):
        return found
    # Cas 2 : Table avec colonne date et montant unique
    if "date" in found and ("amount" in found or "debit" in found or "credit" in found):
        return found
    return None


def _statement_table(
    tables: list[list[list[str]]],
) -> tuple[dict[str, int], list[list[str]]] | None:
    """Le tableau de mouvements : celui dont une ligne d'en-tête est reconnue, le plus long."""
    best = None
    for table in tables:
        for k, row in enumerate(table):
            cols = _column_map(row)
            if cols:
                body = table[k + 1 :]
                if best is None or len(body) > len(best[1]):
                    best = (cols, body)
                break
    return best


def _header_values(text: str) -> dict[str, str]:
    """Valeurs de l'en-tête : « Label: valeur » sur la ligne, ou valeur sur la ligne suivante."""
    lines = [ln.strip(" #*|") for ln in text.splitlines()]
    out: dict[str, str] = {}
    for i, line in enumerate(lines):
        for key, label in _HEADER_LABELS.items():
            m = re.search(rf"(?:{label})\s*[:;\-\t]\s*(?P<v>.*)$", line, re.IGNORECASE)
            if not m or key in out:
                continue
            value = m["v"].strip(" \t\r\n\"'|*")
            if not value:  # valeur à la ligne suivante non vide (la mise en page l'éloigne)
                nxt = next((ln for ln in lines[i + 1 :] if ln), "")
                if not any(
                    re.search(rf"(?:{lb})\s*[:;\-\t]", nxt, re.IGNORECASE)
                    for lb in _HEADER_LABELS.values()
                ):
                    value = nxt.strip(" \t\r\n\"'|*")
            if value:
                out[key] = value
    return out


def _period(value: str) -> tuple[object, object]:
    dates = re.findall(r"\d{1,2}[/.]\d{1,2}[/.]\d{4}|\d{4}-\d{2}-\d{2}", value)
    if len(dates) >= 2:
        return parse_date(dates[0]), parse_date(dates[1])
    return None, None


def _number(cell: str) -> float | None:
    """Nombre d'une cellule de montant ; None si vide ou illisible."""
    text = cell.strip()
    if not text or not _NUMERIC_RE.match(text.replace(" ", "")):
        return None
    negative = text.startswith(("-", "("))
    value = parse_amount(text.strip("()").lstrip("-").replace("\u00a0", "").replace(" ", ""))
    if not isinstance(value, float):
        return None
    return -value if negative else value


@dataclass
class _Row:
    date: str
    description: str
    debit: str
    credit: str
    balance: float | None
    amount: str = ""


@dataclass
class _Chain:
    """Résultat de la chaîne de soldes : lignes signées et motif d'incohérence éventuel."""

    lines: list[StatementLine] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    last_balance: float | None = None


def _signed_read(row: _Row) -> tuple[float | None, bool]:
    """(montant signé lu dans les colonnes, colonne lisible ?) ; débit négatif."""
    if row.amount:
        amt = _number(row.amount)
        if amt is not None:
            return amt, True
    debit, credit = _number(row.debit), _number(row.credit)
    if debit is not None and credit is None:
        return -abs(debit), True
    if credit is not None and debit is None:
        return abs(credit), True
    if debit is not None and credit is not None:  # deux montants : ambigu
        return abs(credit) - abs(debit), True
    return None, False


def _scrub(party: str) -> str:
    """Retire d'une contrepartie les glyphes non latins et le montant tronqué laissés par l'OCR."""
    party = re.sub(r"[^\x00-\u024f]+", " ", party)
    return re.sub(r"(?:\s+[\d.,]+)+$", "", party).strip()


def _digits(value: float) -> str:
    """Chiffres du montant en centimes, sans zéros de tête : 8 075,00 -> '807500'."""
    return str(round(abs(value) * 100)).lstrip("0") or "0"


def _distance_at_most_one(a: str, b: str) -> bool:
    """Distance d'édition (substitution, insertion ou suppression d'un chiffre) <= 1."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b, strict=True)) <= 1
    short, long = sorted((a, b), key=len)
    return any(long[:i] + long[i + 1 :] == short for i in range(len(long)))


def _compatible(read: float, repaired: float) -> bool:
    """Le montant lu peut-il être une lecture tronquée ou fautive du montant `repaired` ?"""
    lu, vrai = _digits(read), _digits(repaired)
    return vrai.endswith(lu) or _distance_at_most_one(lu, vrai)


def _walk(rows: list[_Row], opening: float | None, currency: str, repair: bool) -> _Chain:
    """Parcourt les lignes en suivant la chaîne des soldes imprimés (resynchronisée à chaque ligne)."""
    chain = _Chain()
    previous = opening
    for n, row in enumerate(rows, 1):
        read, _ = _signed_read(row)
        amount, note, suspect = read, "", ""
        if row.balance is None:
            if opening is not None and row.amount:
                pass
            else:
                chain.problems.append(f"ligne {n} : solde illisible, montant non contrôlé")
            previous = None if previous is None or read is None else previous + read
        elif previous is None:
            previous = row.balance  # pas d'ouverture : première ligne non contrôlable
        else:
            delta = round(row.balance - previous, 2)
            if abs(delta) < TOLERANCE and read is None:
                previous = row.balance  # ligne sans mouvement (report, mention)
                continue
            if read is None or abs(read - delta) >= TOLERANCE:
                if repair and (read is None or _compatible(read, delta)):
                    shown = row.debit or row.credit or "(vide)"
                    amount = delta
                    note = (
                        f"montant lu {shown!r} remplacé par {abs(delta):.2f} "
                        f"({'crédit' if delta > 0 else 'débit'}) : "
                        f"|{previous:.2f} - {row.balance:.2f}|"
                    )
                else:
                    # Écart sans rapport avec une erreur de lecture du montant : on ne répare pas
                    before = f"la ligne {n - 1}" if n > 1 else "l'ouverture"
                    suspect = (
                        f"solde non réconcilié entre {before} et la ligne {n} "
                        f"({previous:.2f} -> {row.balance:.2f}), ligne possiblement manquante"
                    )
                    chain.problems.append(suspect)
            previous = row.balance
        if amount is None or abs(amount) < TOLERANCE:
            continue
        label = row.description.strip()
        chain.lines.append(
            StatementLine(
                date=parse_date(row.date),  # type: ignore[arg-type]
                counterparty=_scrub(clean_counterparty(label)) or label,
                amount=round(amount, 2),
                currency=currency,
                balance=row.balance,
                description=label,
                repair=note,
                suspect=suspect,
            )
        )
    chain.last_balance = previous
    return chain


def parse_statement(raw: str, repair: bool = True) -> DocumentExtraction:
    """
    Relevé bancaire depuis la sortie brute du lecteur de tableaux.

    `repair=False` garde les montants tels que lus (mesure de l'apport de la réparation) ; la
    réconciliation est alors évaluée sur les montants lus.
    """
    tables = html_tables(raw)
    found = _statement_table(tables)
    header_text = re.sub(r"<table.*?</table>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    header_text = re.sub(r"<[^>]+>", " ", header_text)
    head = _header_values(header_text)
    holder = head.get("holder", "").strip()
    iban = head.get("iban", "").strip()
    start, end = _period(head.get("period", ""))
    explicit = _CURRENCY_RE.search(head.get("currency", "")) or _CURRENCY_RE.search(header_text)
    header_currency = explicit[1] if explicit else ""
    entities = (
        [
            ExtractedEntity(
                name=holder, kind="Societe" if _COMPANY_RE.search(holder) else "PersonnePhysique"
            )
        ]
        if len(holder) >= 2
        else []
    )
    base = DocumentExtraction(
        doc_type="bank_statement",
        entities=entities,
        account_holder=holder,
        account_iban=iban,
        bank=head.get("bank", "").strip(),
        period_start=start,  # type: ignore[arg-type]
        period_end=end,  # type: ignore[arg-type]
        header_currency=header_currency,
        raw_output=raw,
    )
    if found is None:
        return base.model_copy(
            update={"balance_reconciled": False, "balance_note": "aucun tableau de relevé lu"}
        )
    cols, body = found

    def cell(row: list[str], kind: str) -> str:
        i = cols.get(kind)
        return row[i] if i is not None and i < len(row) else ""

    opening = closing = None
    movements: list[_Row] = []
    has_bal_col = "balance" in cols
    for row in body:
        label = cell(row, "description")
        low = label.lower()
        bal = _number(cell(row, "balance")) if has_bal_col else None
        amt_cell = cell(row, "amount")
        if not cell(row, "date") and any(k in low for k in _OPENING):
            opening = bal if bal is not None else _number(amt_cell)
        elif not cell(row, "date") and any(k in low for k in _CLOSING):
            closing = bal if bal is not None else _number(amt_cell)
        elif cell(row, "date") or label:
            movements.append(
                _Row(cell(row, "date"), label, cell(row, "debit"), cell(row, "credit"), bal, amount=amt_cell)
            )
    comma = sum(bool(re.search(r",\d{2}\b", c)) for r in body for c in r)
    point = sum(bool(re.search(r"\.\d{2}\b", c)) for r in body for c in r)
    currency = header_currency or ("EUR" if comma > point else "USD")
    chain = _walk(movements, opening, currency, repair)
    problems = list(chain.problems)
    if opening is None or closing is None:
        reconciled = None
        problems.append("solde d'ouverture ou de clôture absent")
    else:
        expected = chain.last_balance
        reconciled = (
            not chain.problems and expected is not None and abs(expected - closing) < TOLERANCE
        )
        if expected is not None and abs(expected - closing) >= TOLERANCE:
            problems.append(
                f"solde non réconcilié entre la ligne {len(movements)} et la clôture "
                f"({expected:.2f} ≠ solde de clôture {closing:.2f}), ligne possiblement manquante"
            )
    update = {
        "statement_lines": chain.lines,
        "opening_balance": opening,
        "closing_balance": closing,
        "balance_reconciled": reconciled,
        "balance_note": "; ".join(problems) if reconciled is not True else "",
    }
    return base.model_copy(update=update)
