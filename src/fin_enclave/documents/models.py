"""Schémas Pydantic de l'extraction documentaire (sortie contrainte du modèle de vision)."""

import re
from datetime import UTC, datetime
from datetime import date as date_type
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

EntityKind = Literal["Societe", "PersonnePhysique", "Intermediaire", "Adresse"]
Role = Literal[
    "director",
    "shareholder",
    "beneficial_owner",
    "secretary",
    "attorney",
    "intermediary",
    "registered_address",
    "other",
]
DocType = Literal[
    "certificate_of_incorporation",
    "register_of_directors",
    "register_of_shareholders",
    "power_of_attorney",
    "wire_transfer",
    "bank_statement",
    "invoice",
    "correspondence",
    "other",
]

OWNERSHIP_ROLES = {"shareholder", "beneficial_owner"}

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d %B %Y", "%d %b %Y", "%B %d, %Y")


def parse_amount(value: object) -> object:
    """'USD 2,431,500.00' -> 2431500.0 ; gère les formats anglo-saxon et européen."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            # Format européen : 1.250.000,00 -> 1250000.00
            text = text.replace(".", "").replace(",", ".")
        else:
            # Format anglo-saxon : 1,250,000.00 -> 1250000.00
            text = text.replace(",", "")
    elif "," in text and re.search(r",\d{1,2}$", text):
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    cleaned = re.sub(r"[^\d.\-]", "", text)
    try:
        return float(cleaned) if cleaned not in ("", "-", ".") else value
    except ValueError:
        return value


def parse_date(value: object) -> object:
    """Normalise les écritures usuelles d'une date ; une date illisible devient None (inconnue)."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC).date()
        except ValueError:
            continue
    return None


class ExtractedEntity(BaseModel):
    name: str = Field(..., min_length=2, description="Nom exact tel qu'écrit dans le document")
    kind: EntityKind


class ExtractedRelation(BaseModel):
    source: str = Field(..., description="Nom de l'entité qui détient / dirige / enregistre")
    target: str = Field(..., description="Nom de la société concernée, ou de l'adresse")
    role: Role


class ExtractedTransfer(BaseModel):
    """Un mouvement d'argent écrit sur la pièce (ordre de virement, ligne de relevé)."""

    payer: str = Field(..., description="Nom du donneur d'ordre (compte débité)")
    payee: str = Field(..., description="Nom du bénéficiaire (compte crédité)")
    amount: float = Field(..., gt=0, description="Montant positif tel qu'écrit")
    currency: str = Field("USD", description="Code ISO 4217 de la devise")
    date: date_type | None = Field(None, description="Date de valeur au format AAAA-MM-JJ")

    _amount = field_validator("amount", mode="before")(parse_amount)
    _date = field_validator("date", mode="before")(parse_date)

    @field_validator("currency", mode="before")
    @classmethod
    def _currency(cls, v: object) -> object:
        return v.strip().upper()[:3] if isinstance(v, str) and v.strip() else "USD"


_BALANCE_WORDS = ("opening", "closing", "balance", "solde", "report", "saldo")
_PARTY_PREFIXES = (
    "transfer from ",
    "transfer to ",
    "from ",
    "to ",
    "virement de ",
    "virement à ",
    "virement a ",
    "transferencia de ",
    "transferencia a ",
)


def clean_counterparty(label: str) -> str:
    """Contrepartie d'un libellé de relevé ('' pour un solde ou un report recopié comme ligne)."""
    party = label.strip()
    low = party.lower()
    if any(k in low for k in _BALANCE_WORDS):
        return ""
    for prefix in _PARTY_PREFIXES:
        if low.startswith(prefix):
            party = party[len(prefix) :].strip()
            break
    # Forme « Libellé - Nom » : on garde la partie qui suit le dernier « - »
    if "-" in party:
        party = party.rsplit("-", 1)[-1].strip()
    # Préfixes bancaires réalistes (SEPA, CT, CR, VIR, TRANSF, REF)
    party = re.sub(
        r"^(?:(?:SEPA|VIR(?:EMENT)?|TRANSF(?:ERENCIA)?)\s+)+(?:(?:CT|CR|INST|DD|REF|\d+)\s+)*",
        "",
        party,
        flags=re.IGNORECASE,
    ).strip()
    # « REF 12345 » restants en début ou fin de chaîne
    party = re.sub(r"^(?:REF\s*\d+|REF\s+[A-Z0-9-]+)\s+", "", party, flags=re.IGNORECASE).strip()
    party = re.sub(r"\s*\((?:REF\s*)?[A-Z0-9-]+\)$", "", party, flags=re.IGNORECASE).strip()
    return re.sub(r"\s+\bREF\s*[A-Z0-9-]+\b$", "", party, flags=re.IGNORECASE).strip()


class StatementLine(BaseModel):
    """Ligne de relevé transcrite telle qu'imprimée ; le sens est déduit par le code du signe."""

    date: date_type | None = Field(None, description="Date de la ligne au format AAAA-MM-JJ")
    counterparty: str = Field(..., description="Contrepartie écrite sur la ligne")
    amount: float = Field(..., description="Montant signé tel qu'imprimé (débit négatif)")
    currency: str = Field("USD", description="Code ISO 4217 de la devise du compte")
    balance: float | None = Field(None, description="Solde imprimé après la ligne, s'il y en a un")
    # Champs posés par l'analyseur de tableau (jamais demandés au modèle de vision)
    description: str = Field("", description="Libellé complet de la ligne")
    repair: str = Field("", description="Trace de la réparation du montant par les soldes")
    suspect: str = Field("", description="Soldes non réconciliés à cette ligne (non réparée)")

    _amount = field_validator("amount", mode="before")(parse_amount)
    _date = field_validator("date", mode="before")(parse_date)
    _balance = field_validator("balance", mode="before")(
        lambda v: None if v in ("", None) else parse_amount(v)
    )


# Champs écrits par le code (analyse de tableau, réconciliation) : absents du schéma du modèle.
CODE_ONLY_FIELDS = {
    "DocumentExtraction": {"raw_output", "balance_reconciled", "balance_note"},
    "StatementLine": {"description", "repair", "suspect"},
}


class DocumentExtraction(BaseModel):
    """Faits extraits d'une pièce. Rien ne doit être déduit hors du document."""

    doc_type: DocType
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
    transfers: list[ExtractedTransfer] = Field(default_factory=list)
    account_holder: str = Field("", description="Titulaire du compte (relevé bancaire)")
    statement_lines: list[StatementLine] = Field(default_factory=list)
    # En-tête du relevé (tout est optionnel : lectures scellées antérieures)
    account_iban: str = Field("", description="IBAN / numéro de compte imprimé en en-tête")
    bank: str = Field("", description="Banque émettrice si elle est imprimée")
    period_start: date_type | None = Field(None, description="Début de période AAAA-MM-JJ")
    period_end: date_type | None = Field(None, description="Fin de période AAAA-MM-JJ")
    header_currency: str = Field("", description="Devise imprimée en en-tête (code ISO 4217)")
    opening_balance: float | None = Field(None, description="Solde d'ouverture imprimé")
    closing_balance: float | None = Field(None, description="Solde de clôture imprimé")
    # Écrits par le code
    balance_reconciled: bool | None = Field(
        None, description="True/False : soldes cohérents avec les lignes ; None : non vérifiable"
    )
    balance_note: str = Field("", description="Motif de non-réconciliation des soldes")
    raw_output: str = Field("", description="Sortie brute du lecteur de tableaux (scellée)")

    _period = field_validator("period_start", "period_end", mode="before")(parse_date)
    _balances = field_validator("opening_balance", "closing_balance", mode="before")(
        lambda v: None if v in ("", None) else parse_amount(v)
    )

    @field_validator("account_iban", "bank", "header_currency", "account_holder", mode="before")
    @classmethod
    def _none_is_empty(cls, v: object) -> object:
        return "" if v is None else v

    def resolved_transfers(self) -> list[ExtractedTransfer]:
        """Virements de la pièce : sur un relevé, le sens vient du signe, pas du modèle."""
        if not self.statement_lines:
            return list(self.transfers)
        holder = (
            self.account_holder
            or (self.entities[0].name if self.entities else "")
            or "Titulaire inconnu"
        )
        out = []
        for line in self.statement_lines:
            if line.amount == 0:
                continue
            party = clean_counterparty(line.counterparty)
            if len(party) < 2:
                continue
            debit = line.amount < 0
            out.append(
                ExtractedTransfer(
                    payer=holder if debit else party,
                    payee=party if debit else holder,
                    amount=abs(line.amount),
                    currency=line.currency,
                    date=line.date,
                )
            )
        return out


class PageRelation(ExtractedRelation):
    """Relation extraite + page de la pièce d'où elle est lue (chaîne de preuve par page)."""

    page: int = Field(1, ge=1)

    @model_validator(mode="before")
    @classmethod
    def _from_plain_relation(cls, v: object) -> object:
        """Accepte une `ExtractedRelation` nue (page 1) : scellés et appelants antérieurs."""
        if isinstance(v, ExtractedRelation) and not isinstance(v, cls):
            return v.model_dump()
        return v


class GroundedEntity(ExtractedEntity):
    """Entité extraite + résultat de la vérification contre la couche OCR indépendante."""

    grounded: bool | None = None  # None = témoin OCR absent ou illisible : non vérifiable
    grounding_score: float = 0.0


class GroundedTransfer(ExtractedTransfer):
    """Virement extrait + présence du montant dans la couche OCR indépendante."""

    amount_grounded: bool | None = None
    page: int = Field(1, ge=1, description="Page de la pièce d'où vient le virement (1 = première)")
    review_flags: list[str] = Field(
        default_factory=list, description="Motifs de relecture de la ligne (contrôles du code)"
    )


class PieceExtraction(BaseModel):
    """Résultat d'extraction d'une pièce, rattaché à son scellé."""

    piece_id: str
    file: str
    file_sha256: str
    # Empreinte de chaque page rasterisée (vide pour les scellés antérieurs : repli sur le fichier)
    page_sha256: list[str] = Field(default_factory=list)
    engine: str
    from_cache: bool = False
    seconds: float = 0.0
    doc_type: DocType = "other"
    entities: list[GroundedEntity] = Field(default_factory=list)
    relations: list[PageRelation] = Field(default_factory=list)
    transfers: list[GroundedTransfer] = Field(default_factory=list)
    error: str = ""
    # Lecture suspecte (relevé vide ou incohérent après relance) : non scellée, à relire
    needs_review: bool = False
    review_reason: str = ""
    balance_reconciled: bool | None = None
    # En-tête du relevé lu (vide si absent ou scellé antérieur) : réquisitions bancaires
    account_iban: str = ""
    bank: str = ""
    period_start: date_type | None = None
    period_end: date_type | None = None
