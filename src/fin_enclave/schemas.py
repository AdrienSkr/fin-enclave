from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """Localisation spatiale normalisée sur document scanné."""

    xmin: float = 0.0
    ymin: float = 0.0
    xmax: float = 1.0
    ymax: float = 1.0


class ProofPoint(BaseModel):
    """
    Chaîne de Preuve Judiciaire Numérique (ISO/IEC 27037).
    Chaque fait et relation financière est ancré à un hachage cryptographique
    et une cote de procédure formelle vérifiable au contradictoire.
    """

    document_sha256: str = Field(..., description="Empreinte SHA-256 du conteneur brut de la pièce")
    page_sha256: str = Field(..., description="Empreinte SHA-256 de la page/relevé")
    cote_judiciaire: str = Field(..., description="Cote de procédure (ex: Cote D.ICIJ-PAN/102)")
    page_number: int = Field(1, ge=1)
    bounding_box: BoundingBox | None = None
    extracted_value: str = Field(..., description="Valeur littérale ou montant extrait du document")
    source_file: str = Field("", description="Nom du fichier source réel ingéré")
    source_row: int = Field(0, ge=0, description="Numéro de ligne (1 = 1re donnée) dans la source")
    row_sha256: str = Field("", description="Empreinte SHA-256 de la ligne source brute")
    sealed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Horodatage local de scellement (jeton RFC 3161 via TSA locale : roadmap)",
    )


class AnomalyReport(BaseModel):
    """
    Rapport d'infraction judiciaire qualifié par le moteur de raisonnement (LLM).
    Sortie structurée inviolable générée sous contrainte de schéma.
    """

    infraction_type: Literal[
        "BLANCHIMENT_CYCLE_FERME",
        "CARROUSEL_TVA",
        "DISSIMULATION_UBO_PRETE_NOM",
        "FRACTIONNEMENT_SCHTROUMPFAGE",
        "BACK_TO_BACK_LOAN",
        "SURFACTURATION_OFFSHORE",
        "AUCUNE_INFRACTION_NOTABLE",
    ]
    confidence_score: float = Field(
        ..., ge=0.0, le=1.0, description="Score de certitude [0.0 - 1.0]"
    )
    entities_involved: list[str] = Field(
        default_factory=list, description="IDs ou noms des entités compromises"
    )
    total_amount_usd: float = Field(0.0, description="Montant cumulé des flux suspects en USD")
    cycle_detected: list[str] = Field(
        default_factory=list, description="Cycle orienté fermé identifié par Tarjan"
    )
    pivot_intermediary: str = Field(
        "", description="Nœud intermédiaire identifié par la centralité de Brandes"
    )
    legal_basis: list[str] = Field(
        default_factory=list,
        description="Fondements légaux (ex: Art. 324-1 Code Pénal, Art. 1741 CGI, GAFI Rec 24/25)",
    )
    chain_of_custody: list[ProofPoint] = Field(
        default_factory=list, description="Piste d'audit cryptographique des pièces à conviction"
    )
    summary_note: str = Field(
        ..., description="Note de synthèse d'investigation pour le magistrat ou l'analyste"
    )
    recommendations: list[str] = Field(
        default_factory=list, description="Actions judiciaires ou déclarations TRACFIN recommandées"
    )
