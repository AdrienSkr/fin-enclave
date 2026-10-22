"""Tests pour la réconciliation et résolution d'entités (EntityResolver)."""

from fin_enclave.graph.resolver import EntityResolver


def test_resolver_merges_similar_corporate_names_and_absorbs_typos():
    """Vérifie la fusion de variantes d'entreprises et l'absorption de typos d'un caractère."""
    resolver = EntityResolver(threshold=0.85)
    candidates = [
        {"id": "MF_01", "name": "Mossack Fonseca & Co.", "type": "Intermediaire", "country": "PAN"},
        {
            "id": "MF_02",
            "name": "Mossack Fonseca & Partners Ltd.",
            "type": "Intermediaire",
            "country": "VGB",
        },
        {"id": "E1", "name": "Horizon Advisory Ltd.", "type": "Societe"},
        {"id": "E2", "name": "Horizon Advisori Ltd.", "type": "Societe"},
        {"id": "P1", "name": "THOMAS DUPONT", "type": "PersonnePhysique"},
        {"id": "P2", "name": "TOMAS DUPONT", "type": "PersonnePhysique"},
        {"id": "SH_01", "name": "Albatross Maritime Corp.", "type": "Societe", "country": "VGB"},
    ]
    mapping = resolver.fit_resolve(candidates)
    assert mapping["MF_02"] == "MF_01"
    assert mapping["MF_01"] == "MF_01"
    assert mapping["E2"] == "E1"
    assert mapping["P2"] == "P1"
    assert mapping["SH_01"] == "SH_01"
    assert len(resolver.merge_history) == 3


def test_resolver_strict_type_isolation():
    """Vérifie l'inviolabilité absolue des types : PersonnePhysique ne fusionne jamais avec Societe."""
    resolver = EntityResolver(threshold=0.85)
    mapping = resolver.fit_resolve(
        [
            {
                "id": "P1",
                "name": "Hernandez Nominees",
                "type": "PersonnePhysique",
                "country": "PAN",
            },
            {"id": "S1", "name": "Hernandez Nominees Ltd.", "type": "Societe", "country": "BLZ"},
        ]
    )
    assert mapping["P1"] == "P1"
    assert mapping["S1"] == "S1"
    assert resolver.merge_history == []


def test_resolver_preserves_numbered_entities():
    """Vérifie que les entités numérotées distinctes (ex: 1 et 2) ne sont jamais fusionnées."""
    resolver = EntityResolver(threshold=0.85)
    mapping = resolver.fit_resolve(
        [
            {"id": "H1", "name": "SCI Les Pins 1", "type": "Societe", "country": "FRA"},
            {"id": "H2", "name": "SCI Les Pins 2", "type": "Societe", "country": "FRA"},
            {"id": "H3", "name": "SCI Les Pns 1", "type": "Societe", "country": "FRA"},
        ]
    )
    assert mapping["H1"] == "H1"
    assert mapping["H2"] == "H2"
    assert mapping["H3"] == "H1"


def test_resolver_handles_blank_none_and_missing_attributes():
    """Vérifie la robustesse aux valeurs vides, None ou attributs manquants."""
    resolver = EntityResolver()
    assert resolver.resolve_id(None) == ""
    assert resolver.resolve_name(None) == ""

    mapping = resolver.fit_resolve(
        [
            {"id": "E1", "name": "", "type": "Societe"},
            {"id": "E2", "name": "   ", "type": "Societe"},
            {"id": "E3", "name": "---", "type": "Societe"},
            {"id": "N1", "name": None, "type": "Societe"},
            {"id": "N2", "name": None, "type": "Societe"},
            {"id": "X1", "name": "Acme Corp", "type": None},
            {"id": "X2", "name": "Acme Corp", "type": None},
        ]
    )
    assert mapping["E1"] == "E1"
    assert mapping["E2"] == "E2"
    assert mapping["E3"] == "E3"
    assert mapping["N1"] == "N1"
    assert mapping["N2"] == "N2"
    assert mapping["X2"] == "X1"
