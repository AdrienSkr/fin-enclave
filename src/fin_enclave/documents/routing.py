"""
Routage documentaire : distinction entre relevés tabulaires et actes/gouvernance.
"""

import re
from typing import Any, Literal

PieceKind = Literal["statement", "deed"]
Task = Literal["T1", "T2", "T3"]

_TITLE_RE = re.compile(
    r"STATEMENT OF ACCOUNT|ACCOUNT STATEMENT|RELEV\w* DE COMPTE|EXTRACTO DE CUENTA|"
    r"KONTOAUSZUG",
    re.IGNORECASE,
)
_COLUMN_KINDS = {
    "debit": ("debit", "debito", "debe"),
    "credit": ("credit", "credito", "haber"),
    "balance": ("balance", "solde", "saldo"),
}
_DATE_RE = re.compile(r"^\d{1,2}[/.]\d{1,2}[/.]\d{2,4}$")
_AMOUNT_RE = re.compile(r"^-?\d[\d.,']*[.,]\d{2}$")
MIN_WORDS = 15
MIN_DATED_ROWS = 3


def _letters(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower().replace("é", "e").replace("è", "e"))


def dated_rows(text_or_lines: Any) -> int:
    """Lignes qui commencent par une date et portent un montant."""
    lines: list[str] = []
    if isinstance(text_or_lines, str):
        lines = text_or_lines.splitlines()
    elif isinstance(text_or_lines, (list, tuple)):
        lines = list(text_or_lines)
    elif hasattr(text_or_lines, "lines"):
        lines = list(text_or_lines.lines)
    elif hasattr(text_or_lines, "text"):
        lines = str(text_or_lines.text).splitlines()

    return sum(
        bool(_DATE_RE.match(ln.split()[0])) and any(_AMOUNT_RE.match(t) for t in ln.split())
        for ln in lines
        if ln.split()
    )


def route_piece(doc: Any) -> PieceKind:
    """
    Détermine si une pièce est un relevé tabulaire ('statement') ou un acte ('deed').
    Supporte les objets DocumentExtraction, les chaînes de caractères ou les pages textuelles.
    """
    if doc is None:
        return "deed"

    # Si c'est déjà un DocumentExtraction (VLM principal)
    if hasattr(doc, "doc_type"):
        return "statement" if doc.doc_type == "bank_statement" else "deed"

    # Si c'est du texte ou un conteneur de texte
    text = ""
    lines = []
    words = []
    if isinstance(doc, str):
        text = doc
        lines = doc.splitlines()
        words = doc.split()
    elif hasattr(doc, "text"):
        text = str(doc.text)
        lines = list(getattr(doc, "lines", text.splitlines()))
        words = list(getattr(doc, "words", text.split()))

    if len(words) < MIN_WORDS and not _TITLE_RE.search(text):
        return "deed"

    if _TITLE_RE.search(text):
        return "statement"

    tokens = {_letters(getattr(w, "text", str(w))) for w in words}
    columns = sum(any(name in tokens for name in names) for names in _COLUMN_KINDS.values())
    dated = dated_rows(lines)
    if columns >= 2 and dated >= 1:
        return "statement"
    return "statement" if dated >= MIN_DATED_ROWS and columns >= 1 else "deed"


def task_for(kind: PieceKind) -> Task:
    """Tâche qui lit ce type de pièce : relevés -> T2, actes et autres -> T1."""
    return "T2" if kind == "statement" else "T1"
