"""Schémas Pydantic de l'extraction documentaire (sortie contrainte du modèle de vision)."""

import re
from datetime import UTC, datetime
from datetime import date as date_type
from typing import Literal

from pydantic import BaseModel, Field, field_validator

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


class StatementLine(BaseModel):
    """Ligne de relevé transcrite telle qu'imprimée ; le sens est déduit par le code du signe."""

    date: date_type | None = Field(None, description="Date de la ligne au format AAAA-MM-JJ")
    counterparty: str = Field(..., description="Contrepartie écrite sur la ligne")
    amount: float = Field(..., description="Montant signé tel qu'imprimé (débit négatif)")
    currency: str = Field("USD", description="Code ISO 4217 de la devise du compte")

    _amount = field_validator("amount", mode="before")(parse_amount)
    _date = field_validator("date", mode="before")(parse_date)


class DocumentExtraction(BaseModel):
    """Faits extraits d'une pièce. Rien ne doit être déduit hors du document."""

    doc_type: DocType
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
    transfers: list[ExtractedTransfer] = Field(default_factory=list)
    account_holder: str = Field("", description="Titulaire du compte (relevé bancaire)")
    statement_lines: list[StatementLine] = Field(default_factory=list)

    def resolved_transfers(self) -> list[ExtractedTransfer]:
        """Virements de la pièce : sur un relevé, le sens vient du signe, pas du modèle."""
        if not (self.account_holder and self.statement_lines):
            return list(self.transfers)
        out = []
        for line in self.statement_lines:
            if line.amount == 0:
                continue
            party = line.counterparty.strip()
            # Nettoyage des en-têtes / libellés recopiés tels quels par le modèle
            low = party.lower()
            if any(k in low for k in ("opening", "closing", "balance", "solde", "report", "saldo")):
                continue
            prefixes = (
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
            for prefix in prefixes:
                if low.startswith(prefix):
                    party = party[len(prefix) :].strip()
                    low = party.lower()
                    break
            # Nettoyage de la forme « Libellé - Nom » (on garde la partie qui suit le dernier « - »)
            if "-" in party:
                party = party.rsplit("-", 1)[-1].strip()
                low = party.lower()
            # Nettoyage des préfixes bancaires réalistes (SEPA, CT, CR, VIR, TRANSF, REF)
            party = re.sub(
                r"^(?:(?:SEPA|VIR(?:EMENT)?|TRANSF(?:ERENCIA)?)\s+)+(?:(?:CT|CR|INST|DD|REF|\d+)\s+)*",
                "",
                party,
                flags=re.IGNORECASE,
            ).strip()
            # Nettoyage des « REF 12345 » restants en début ou fin de chaîne
            party = re.sub(
                r"^(?:REF\s*\d+|REF\s+[A-Z0-9-]+)\s+",
                "",
                party,
                flags=re.IGNORECASE,
            ).strip()
            party = re.sub(r"\s*\((?:REF\s*)?[A-Z0-9-]+\)$", "", party, flags=re.IGNORECASE).strip()
            party = re.sub(r"\s+\bREF\s*[A-Z0-9-]+\b$", "", party, flags=re.IGNORECASE).strip()
            if len(party) < 2:
                continue
            debit = line.amount < 0
            out.append(
                ExtractedTransfer(
                    payer=self.account_holder if debit else party,
                    payee=party if debit else self.account_holder,
                    amount=abs(line.amount),
                    currency=line.currency,
                    date=line.date,
                )
            )
        return out


class GroundedEntity(ExtractedEntity):
    """Entité extraite + résultat de la vérification contre la couche OCR indépendante."""

    grounded: bool | None = None  # None = témoin OCR absent ou illisible : non vérifiable
    grounding_score: float = 0.0


class GroundedTransfer(ExtractedTransfer):
    """Virement extrait + présence du montant dans la couche OCR indépendante."""

    amount_grounded: bool | None = None


class PieceExtraction(BaseModel):
    """Résultat d'extraction d'une pièce, rattaché à son scellé."""

    piece_id: str
    file: str
    file_sha256: str
    engine: str
    from_cache: bool = False
    seconds: float = 0.0
    doc_type: DocType = "other"
    entities: list[GroundedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
    transfers: list[GroundedTransfer] = Field(default_factory=list)
    error: str = ""
