"""
Shim de compatibilité pour la construction du graphe.
Le coeur du constructeur a été déplacé dans fin_enclave.graph.builder.
"""

from ..graph.builder import (
    _RESOLUTION_CLASS,
    FX_TO_USD,
    PAYMENT_DOC_TYPES,
    _match_in_piece,
    build_document_graph,
)

__all__ = [
    "FX_TO_USD",
    "PAYMENT_DOC_TYPES",
    "_RESOLUTION_CLASS",
    "_match_in_piece",
    "build_document_graph",
]
