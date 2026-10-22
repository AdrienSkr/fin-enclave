"""Modèles de données du raisonnement financier et des qualifications juridiques."""

from typing import Literal

from pydantic import BaseModel, Field


class AnomalyReport(BaseModel):
    """
    Rapport d'infraction financière qualifié de façon déterministe.
    Chaque fait est adossé à ses pièces sources et aux bases légales applicables.
    """

    infraction_type: Literal[
        "BLANCHIMENT_CYCLE_FERME",
        "DISSIMULATION_UBO_PRETE_NOM",
        "FRACTIONNEMENT_SCHTROUMPFAGE",
    ]
    confidence_score: float = Field(
        ..., ge=0.0, le=1.0, description="Score de certitude [0.0 - 1.0]"
    )
    entities_involved: list[str] = Field(
        default_factory=list, description="IDs ou noms des entités impliquées"
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
        description="Fondements légaux (ex: Art. 324-1 Code Pénal, GAFI Rec 24/25)",
    )
    pieces: list[str] = Field(
        default_factory=list,
        description="Cotes des pièces justificatives (ex: PIECE-0006, PIECE-0018)",
    )
    summary_note: str = Field(
        ..., description="Note de synthèse d'investigation pour le magistrat ou l'analyste"
    )
    recommendations: list[str] = Field(
        default_factory=list, description="Actions judiciaires ou déclarations TRACFIN recommandées"
    )


__all__ = ["AnomalyReport"]
