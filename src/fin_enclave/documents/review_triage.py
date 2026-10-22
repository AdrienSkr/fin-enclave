"""
Triage « à relire » : motifs de relecture par ligne (pipeline) et erreurs silencieuses (mesure).

`line_date_flags`, `line_side_flags` et `line_amount_flags` sont appelés par
`extractor.extract_piece` après la lecture : ils posent les motifs `GroundedTransfer.review_flags`
sans relancer le modèle. Le reste du module mesure.

Chaque virement (émetteur, bénéficiaire, montant, date) et chaque lien de gouvernance d'une pièce
est classé juste, faux ou manquant, et signalé ou non. Une erreur silencieuse est un fait faux ou
manquant que rien ne signale (pièce « à relire » ou en erreur, ligne réparée, suspecte ou portant
un motif de relecture).

Les contrôles candidats (`candidate_controls`) ne regardent que les lectures, jamais la vérité :
la vérité sert seulement à compter les erreurs silencieuses que chacun fermerait.
"""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from .evaluation import _same

AMOUNT_TOLERANCE = 0.005
YEAR_SPAN = 2  # écart toléré (en années) à l'année médiane des dates lues du dossier
MIN_PLAUSIBLE_YEAR = 1900  # en deçà (ou après l'horloge de la station), la date est impossible
# Écart minimum (lignes OCR datées − virements lus) pour signaler une pièce ; en deçà, bruit OCR.
ROW_COUNT_GAP = 3
FLAG_MISSING_ROWS = "lignes manquantes"
# Plafonds post ticket 04 (`../.scratch/relecture-ciblee/measures-04.md`) : non-régression.
SILENT_ERROR_CEILING_TOTAL = 14
SILENT_ERROR_CEILING: dict[tuple[str, str], int] = {
    ("investigation", "8B"): 14,
    ("investigation", "72B"): 0,
    ("investigation", "235B"): 0,
}


def check_silent_ceilings(rows: list[dict]) -> list[str]:
    """Messages d'écart si une ligne dépasse son plafond ou si le total dépasse 245."""
    msgs: list[str] = []
    total = 0
    for r in rows:
        key = (r["set"], r["station"])
        silent = int(r["all"]["silent"])
        total += silent
        ceiling = SILENT_ERROR_CEILING.get(key)
        if ceiling is not None and silent > ceiling:
            msgs.append(f"{key[0]} / {key[1]} : {silent} > plafond {ceiling}")
    if total > SILENT_ERROR_CEILING_TOTAL:
        msgs.append(f"total : {total} > plafond {SILENT_ERROR_CEILING_TOTAL}")
    return msgs


_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_DATE_FORMATS = (
    "%d/%m/%Y",
    "%d.%m.%Y",
    "%d-%m-%Y",
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
)


@dataclass(frozen=True)
class Transfer:
    payer: str
    payee: str
    amount: float
    date: str = ""  # ISO AAAA-MM-JJ ; '' si illisible
    flagged: bool = False  # ligne signalée par le pipeline (réparation, solde suspect)

    def label(self) -> str:
        return f"{self.payer} -> {self.payee} {self.amount:.2f} {self.date or '?'}"


@dataclass(frozen=True)
class Link:
    source: str
    target: str
    role: str

    def label(self) -> str:
        return f"{self.source} -{self.role}-> {self.target}"


@dataclass(frozen=True)
class Outcome:
    piece_id: str
    kind: str  # "virement" | "lien"
    status: str  # "juste" | "faux" | "manquant"
    flagged: bool
    cause: str = ""
    read: str = ""
    true: str = ""
    index: int = -1  # rang du fait lu dans la pièce (-1 : fait manquant)
    expected: Transfer | None = None  # virement vrai (manquant ou faux apparié)

    @property
    def silent(self) -> bool:
        return self.status != "juste" and not self.flagged

    @property
    def category(self) -> str:
        return f"{self.status} {'signalé' if self.flagged else 'non signalé'}"


def _same_amount(a: float, b: float) -> bool:
    return abs(a - b) < AMOUNT_TOLERANCE


def wrong_fields(read: Transfer, true: Transfer) -> list[str]:
    """Champs faux d'un virement lu : contrepartie, sens (parties inversées), montant, date."""
    out: list[str] = []
    payer, payee = _same(read.payer, true.payer), _same(read.payee, true.payee)
    if not (payer and payee):
        swapped = _same(read.payer, true.payee) and _same(read.payee, true.payer)
        out += ["sens"] if swapped else ["contrepartie"] * (2 - payer - payee)
    if not _same_amount(read.amount, true.amount):
        out.append("montant")
    if read.date != true.date:
        out.append("date")
    return out


def _cause(fields: list[str]) -> str:
    return "+".join(dict.fromkeys(fields))


def classify_transfers(
    piece_id: str, read: list[Transfer], truth: list[Transfer], piece_flagged: bool
) -> list[Outcome]:
    """Apparie lectures et vérité d'une pièce : exact, puis au plus 2 champs faux, puis le reste."""
    pairs: dict[int, int] = {}
    free = list(range(len(truth)))
    for i, r in enumerate(read):
        j = next((j for j in free if not wrong_fields(r, truth[j])), None)
        if j is not None:
            pairs[i] = j
            free.remove(j)
    candidates = sorted(
        (len(wrong_fields(r, truth[j])), i, j)
        for i, r in enumerate(read)
        if i not in pairs
        for j in free
    )
    for n_wrong, i, j in candidates:
        if n_wrong <= 2 and i not in pairs and j in free:
            pairs[i] = j
            free.remove(j)
    out: list[Outcome] = []
    for i, r in enumerate(read):
        flagged = piece_flagged or r.flagged
        if i in pairs:
            t = truth[pairs[i]]
            fields = wrong_fields(r, t)
            out.append(
                Outcome(
                    piece_id,
                    "virement",
                    "faux" if fields else "juste",
                    flagged,
                    _cause(fields),
                    r.label(),
                    t.label(),
                    i,
                    t,
                )
            )
            continue
        twin = next((t for t in truth if len(wrong_fields(r, t)) <= 1), None)
        cause = "doublon" if twin is not None else "inventé"
        out.append(
            Outcome(
                piece_id,
                "virement",
                "faux",
                flagged,
                cause,
                r.label(),
                twin.label() if twin else "",
                i,
                twin,
            )
        )
    out += [
        Outcome(
            piece_id,
            "virement",
            "manquant",
            piece_flagged,
            "ligne manquante",
            "",
            t.label(),
            expected=t,
        )
        for j, t in enumerate(truth)
        if j in free
    ]
    return out


def _link_eq(a: Link, b: Link) -> bool:
    return a.role == b.role and _same(a.source, b.source) and _same(a.target, b.target)


def classify_links(
    piece_id: str, read: list[Link], truth: list[Link], piece_flagged: bool
) -> list[Outcome]:
    """Liens de détention / contrôle : exact, puis rôle faux, puis contrepartie fausse."""
    pairs: dict[int, tuple[int, str]] = {}
    free = list(range(len(truth)))
    rules = (
        ("", _link_eq),
        ("rôle", lambda a, b: _same(a.source, b.source) and _same(a.target, b.target)),
        (
            "contrepartie",
            lambda a, b: (
                a.role == b.role and (_same(a.source, b.source) or _same(a.target, b.target))
            ),
        ),
    )
    for cause, eq in rules:
        for i, r in enumerate(read):
            if i in pairs:
                continue
            j = next((j for j in free if eq(r, truth[j])), None)
            if j is not None:
                pairs[i] = (j, cause)
                free.remove(j)
    out: list[Outcome] = []
    for i, r in enumerate(read):
        if i in pairs:
            j, cause = pairs[i]
            status = "faux" if cause else "juste"
            out.append(
                Outcome(
                    piece_id, "lien", status, piece_flagged, cause, r.label(), truth[j].label(), i
                )
            )
        else:
            out.append(
                Outcome(piece_id, "lien", "faux", piece_flagged, "lien inventé", r.label(), "", i)
            )
    out += [
        Outcome(piece_id, "lien", "manquant", piece_flagged, "lien manquant", "", truth[j].label())
        for j in free
    ]
    return out


def summarize(outcomes: list[Outcome]) -> dict:
    """Comptes par catégorie, erreurs silencieuses et exactitude du non-signalé."""
    cats = Counter(o.category for o in outcomes)
    errors = sum(o.status != "juste" for o in outcomes)
    silent = sum(o.silent for o in outcomes)
    ok_quiet = cats["juste non signalé"]
    quiet_read = ok_quiet + cats["faux non signalé"]
    return {
        "categories": dict(sorted(cats.items())),
        "errors": errors,
        "silent": silent,
        "silent_share_of_errors": round(silent / errors, 4) if errors else 0.0,
        "facts": len(outcomes),
        "silent_per_fact": round(silent / len(outcomes), 4) if outcomes else 0.0,
        "unflagged_precision": round(ok_quiet / quiet_read, 4) if quiet_read else 1.0,
        "unflagged_read": quiet_read,
    }


# --- Contrôles déterministes candidats (lectures seules) -------------------------------------


@dataclass
class PieceRead:
    """Ce que la station a lu d'une pièce, et ce que le témoin OCR en dit."""

    piece_id: str
    doc_type: str
    transfers: list[Transfer]
    links: list[Link] = field(default_factory=list)
    period: tuple[date | None, date | None] = (None, None)
    amount_witness: list[bool | None] = field(default_factory=list)
    party_witness: list[bool | None] = field(default_factory=list)
    link_witness: list[bool | None] = field(default_factory=list)
    side_witness: list[str | None] = field(default_factory=list)  # "debit" | "credit" | None
    witness_text: str = ""  # texte OCR témoin (toutes pages), '' si absent
    dated_rows: int = 0  # lignes datées avec montant vues par le témoin


@dataclass
class ControlHits:
    """Ce qu'un contrôle signale : lignes (pièce, nature, rang), pièces entières, lignes attendues."""

    lines: set[tuple[str, str, int]] = field(default_factory=set)
    pieces: set[str] = field(default_factory=set)
    expected: dict[str, list[Transfer]] = field(default_factory=dict)

    def closes(self, o: Outcome) -> bool:
        """Le fait est désigné : sa ligne, sa pièce, ou la ligne vraie attendue dans sa pièce."""
        if (o.piece_id, o.kind, o.index) in self.lines or o.piece_id in self.pieces:
            return True
        return o.expected is not None and any(
            _parties_amount(e, o.expected) for e in self.expected.get(o.piece_id, [])
        )


def _parties_amount(a: Transfer, b: Transfer) -> bool:
    return _same(a.payer, b.payer) and _same(a.payee, b.payee) and _same_amount(a.amount, b.amount)


def _iso(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


# Motifs de relecture posés après la lecture (jamais scellés, jamais demandés au modèle).
FLAG_DATE_IMPOSSIBLE = "date impossible"
FLAG_DATE_OUT_OF_PERIOD = "date hors période du relevé"
FLAG_DATE_ABSENT = "date absente du témoin OCR"
FLAG_SIDE = "sens contredit par le témoin OCR"
FLAG_AMOUNT_ABSENT = "montant absent du témoin OCR"

# Montants imprimés avec séparateurs de milliers / décimales (FR, EN, espaces OCR).
_MONEY_RE = re.compile(
    r"(?<!\d)(\d{1,3}(?:[ .'’\u00a0]\d{3})+[.,]\d{2}"
    r"|\d{1,3}(?:[.,]\d{3})+[.,]\d{2}"
    r"|\d+[.,]\d{2})(?!\d)"
)


def line_date_flags(
    value: date | None,
    today: date,
    witness_text: str = "",
    period: tuple[date | None, date | None] = (None, None),
) -> list[str]:
    """
    Motifs de relecture de la date d'un virement lu ([] si rien à redire ou date absente).
    `witness_text` : texte du témoin OCR de la page, '' s'il est absent ou trop pauvre ;
    `period` : début et fin imprimés du relevé (None si non imprimés).
    """
    if value is None:
        return []
    out: list[str] = []
    start, end = period
    if value.year < MIN_PLAUSIBLE_YEAR or value > today:
        out.append(FLAG_DATE_IMPOSSIBLE)
    elif (start is not None and value < start) or (end is not None and value > end):
        out.append(FLAG_DATE_OUT_OF_PERIOD)
    # Un témoin qui ne lit aucune année sur la page ne peut pas attester l'absence d'une date.
    if _YEAR_RE.search(witness_text) and not date_on_witness(value.isoformat(), witness_text):
        out.append(FLAG_DATE_ABSENT)
    return out


def line_side_flags(payer: str, payee: str, holder: str, side: str | None) -> list[str]:
    """Motif si la colonne Débit/Crédit du témoin contredit le sens lu ([] sinon)."""
    if not holder or side is None:
        return []
    expected_debit = _same(holder, payer)
    if side == "debit" and not expected_debit:
        return [FLAG_SIDE]
    if side == "credit" and not _same(holder, payee):
        return [FLAG_SIDE]
    return []


def line_amount_flags(amount: float, witness_text: str) -> list[str]:
    """Motif si le montant lu est absent du témoin OCR ([] si présent, pauvre ou absent)."""
    if amount_on_witness(amount, witness_text) is False:
        return [FLAG_AMOUNT_ABSENT]
    return []


def date_on_witness(value: str, text: str) -> bool | None:
    """La date lue figure-t-elle, sous une écriture usuelle, dans le texte du témoin OCR ?"""
    d = _iso(value)
    if not text or d is None:
        return None
    flat = " ".join(text.lower().split())
    return any(d.strftime(fmt).lower() in flat for fmt in _DATE_FORMATS)


def _amount_digit_targets(amount: float) -> set[str]:
    """Écritures numériques attendues : unités seules, ou unités + centimes."""
    units = str(int(amount))
    return {units, units + f"{round(amount * 100) % 100:02d}"}


def amount_on_witness(amount: float, text: str) -> bool | None:
    """
    Le montant figure-t-il dans le témoin OCR ?
    Séparateurs de milliers et décimales (espace, point, virgule, apostrophe) sont normalisés.
    None si le témoin est vide (n'atteste rien) ; ne déduit jamais de devise.
    """
    if not text or not text.strip():
        return None
    targets = _amount_digit_targets(amount)
    for token in _MONEY_RE.findall(text):
        if re.sub(r"\D", "", token) in targets:
            return True
    for word in text.split():
        digits = re.sub(r"\D", "", word)
        if digits in targets:
            return True
    return False


def statement_holder(transfers: list[Transfer]) -> str:
    """Partie présente dans tous les virements d'un relevé (le titulaire), sinon ''."""
    if not transfers:
        return ""
    for name in (transfers[0].payer, transfers[0].payee):
        if all(_same(name, t.payer) or _same(name, t.payee) for t in transfers):
            return name
    return ""


def _chronology_outliers(dates: list[str]) -> set[int]:
    """Rangs dont la date rompt l'ordre chronologique d'un relevé alors que ses voisines le suivent."""
    known = [(i, d) for i, x in enumerate(dates) if (d := _iso(x))]
    out: set[int] = set()
    for k, (i, d) in enumerate(known):
        prev = known[k - 1][1] if k else None
        nxt = known[k + 1][1] if k + 1 < len(known) else None
        if prev and nxt:
            bad = prev <= nxt and not prev <= d <= nxt
        elif nxt and k + 2 < len(known):  # première ligne : ses deux suivantes sont en ordre
            bad = d > nxt <= known[k + 2][1]
        elif prev and k >= 2:  # dernière ligne : ses deux précédentes sont en ordre
            bad = d < prev and known[k - 2][1] <= prev
        else:
            bad = False
        if bad:
            out.add(i)
    return out


def _date_window(reads: list[PieceRead]) -> tuple[int, int] | None:
    years = sorted(d.year for r in reads for t in r.transfers if (d := _iso(t.date)))
    if not years:
        return None
    mid = years[len(years) // 2]
    return mid - YEAR_SPAN, mid + YEAR_SPAN


def control_dates(reads: list[PieceRead]) -> ControlHits:
    """Date illisible, hors période imprimée du relevé ou loin des autres dates du dossier."""
    hits = ControlHits()
    window = _date_window(reads)
    for r in reads:
        start, end = r.period
        for i, t in enumerate(r.transfers):
            d = _iso(t.date)
            bad = (
                d is None
                or (window is not None and not window[0] <= d.year <= window[1])
                or (start is not None and d < start)
                or (end is not None and d > end)
            )
            if bad:
                hits.lines.add((r.piece_id, "virement", i))
    return hits


def control_chronology(reads: list[PieceRead]) -> ControlHits:
    """Relevé : ligne dont la date rompt l'ordre chronologique de ses voisines."""
    hits = ControlHits()
    for r in reads:
        if r.doc_type == "bank_statement" and len(r.transfers) >= 3:
            for i in _chronology_outliers([t.date for t in r.transfers]):
                hits.lines.add((r.piece_id, "virement", i))
    return hits


def control_two_sided(reads: list[PieceRead]) -> ControlHits:
    """
    Désaccord montant/date entre deux relevés du dossier pour le même couple de parties.
    Les deux comptes doivent être titulaires d'un relevé (sinon trop de fausses alertes).
    Candidat de mesure seulement : non branché sur le pipeline (gain marginal trop faible).
    """
    hits = ControlHits()
    holders = {
        r.piece_id: h
        for r in reads
        if r.doc_type == "bank_statement" and (h := statement_holder(r.transfers))
    }
    holder_names = list(holders.values())
    for r in reads:
        if r.doc_type != "bank_statement":
            continue
        for i, t in enumerate(r.transfers):
            if not (
                any(_same(h, t.payer) for h in holder_names)
                and any(_same(h, t.payee) for h in holder_names)
            ):
                continue
            others = [
                o
                for s in reads
                if s.piece_id != r.piece_id and s.doc_type == "bank_statement"
                for o in s.transfers
                if _same(o.payer, t.payer) and _same(o.payee, t.payee)
            ]
            if others and not any(
                _same_amount(o.amount, t.amount) and o.date == t.date for o in others
            ):
                hits.lines.add((r.piece_id, "virement", i))
    return hits


def control_duplicates(reads: list[PieceRead]) -> ControlHits:
    """Même pièce : deux virements de mêmes parties et même montant (doublon probable)."""
    hits = ControlHits()
    for r in reads:
        for i, a in enumerate(r.transfers):
            if any(j != i and _parties_amount(a, b) for j, b in enumerate(r.transfers)):
                hits.lines.add((r.piece_id, "virement", i))
    return hits


def control_witness_amount(reads: list[PieceRead]) -> ControlHits:
    """Montant lu absent du témoin Tesseract (`amount_grounded is False`)."""
    hits = ControlHits()
    for r in reads:
        for i, ok in enumerate(r.amount_witness):
            if ok is False:
                hits.lines.add((r.piece_id, "virement", i))
    return hits


def control_witness_date(reads: list[PieceRead]) -> ControlHits:
    """Date lue absente du témoin Tesseract, sous toutes ses écritures usuelles."""
    hits = ControlHits()
    for r in reads:
        for i, t in enumerate(r.transfers):
            if r.witness_text and date_on_witness(t.date, r.witness_text) is not True:
                hits.lines.add((r.piece_id, "virement", i))
    return hits


def control_witness_party(reads: list[PieceRead]) -> ControlHits:
    """Émetteur, bénéficiaire ou extrémité d'un lien absent du témoin (`grounded is False`)."""
    hits = ControlHits()
    for r in reads:
        for i, ok in enumerate(r.party_witness):
            if ok is False:
                hits.lines.add((r.piece_id, "virement", i))
        for i, ok in enumerate(r.link_witness):
            if ok is False:
                hits.lines.add((r.piece_id, "lien", i))
    return hits


def control_witness_side(reads: list[PieceRead]) -> ControlHits:
    """Relevé : le montant est imprimé dans la colonne Débit (ou Crédit) opposée au sens lu."""
    hits = ControlHits()
    for r in reads:
        holder = statement_holder(r.transfers) if r.doc_type == "bank_statement" else ""
        if not holder:
            continue
        for i, (t, side) in enumerate(zip(r.transfers, r.side_witness, strict=False)):
            if side is not None and (side == "debit") != _same(holder, t.payer):
                hits.lines.add((r.piece_id, "virement", i))
    return hits


def control_row_count(reads: list[PieceRead]) -> ControlHits:
    """Relevé : le témoin voit au moins ROW_COUNT_GAP lignes datées de plus que de virements lus."""
    hits = ControlHits()
    for r in reads:
        if r.doc_type == "bank_statement" and r.dated_rows >= len(r.transfers) + ROW_COUNT_GAP:
            hits.pieces.add(r.piece_id)
    return hits


CONTROLS = {
    "date illisible, hors période ou hors fenêtre du dossier": control_dates,
    "date hors ordre chronologique du relevé": control_chronology,
    "virement vu des deux côtés (comptes au dossier, désaccord montant/date)": control_two_sided,
    "doublon dans la pièce (mêmes parties, même montant)": control_duplicates,
    "montant absent du témoin OCR": control_witness_amount,
    "date absente du témoin OCR": control_witness_date,
    "contrepartie absente du témoin OCR": control_witness_party,
    "sens contredit par la colonne Débit / Crédit du témoin OCR": control_witness_side,
    "lignes datées du témoin ≥ lecture + 3": control_row_count,
}


def evaluate_control(hits: ControlHits, outcomes: list[Outcome], flagged_pieces: set[str]) -> dict:
    """Erreurs silencieuses fermées, et coût : faits justes non signalés et pièces ajoutés."""
    closed = [o for o in outcomes if o.silent and hits.closes(o)]
    quiet_hit = [
        o
        for o in outcomes
        if not o.flagged
        and o.index >= 0
        and ((o.piece_id, o.kind, o.index) in hits.lines or o.piece_id in hits.pieces)
    ]
    touched = {p for p, _, _ in hits.lines} | hits.pieces | set(hits.expected)
    return {
        "closed": len(closed),
        "closed_causes": dict(Counter(o.cause for o in closed).most_common()),
        "false_alarms": sum(o.status == "juste" for o in quiet_hit),
        "new_lines": len(quiet_hit),
        "new_pieces": len(touched - flagged_pieces),
    }
