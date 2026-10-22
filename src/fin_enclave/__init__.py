"""
FinEnclave : Station Locale d'Investigation Financière sur Graphes & Détection Anti-Blanchiment.
Conçu pour ASUS Ascent GX10 (NVIDIA Grace Blackwell GB10).
"""

from .investigation import (
    Investigation,
    InvestigationFindings,
    analyse,
    investigate,
)

__version__ = "0.1.0"
__all__ = [
    "Investigation",
    "InvestigationFindings",
    "analyse",
    "investigate",
]
