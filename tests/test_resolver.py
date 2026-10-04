from fin_enclave.graph.resolver import (
    EntityResolver,
    jaro_winkler_similarity,
    normalize_entity_name,
)


def test_normalize_entity_name():
    assert normalize_entity_name("Mossack Fonseca & Co. (BVI) Ltd.") == "MOSSACK FONSECA"
    assert normalize_entity_name("Horizon Advisory Ltd") == "HORIZON ADVISORY"


def test_jaro_winkler_similarity():
    sim = jaro_winkler_similarity("MOSSACK FONSECA", "MOSSACK FONSECA PARTNERS")
    assert sim > 0.85
    assert jaro_winkler_similarity("APPLE", "BANANA") < 0.5


def test_resolver_never_merges_different_types():
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
    assert mapping["S1"] == "S1"
    assert resolver.merge_history == []


def test_resolver_keeps_numbered_entities_distinct():
    resolver = EntityResolver(threshold=0.85)
    mapping = resolver.fit_resolve(
        [
            {"id": "H1", "name": "SCI Les Pins 1", "type": "Societe", "country": "FRA"},
            {"id": "H2", "name": "SCI Les Pins 2", "type": "Societe", "country": "FRA"},
        ]
    )
    assert mapping["H1"] == "H1" and mapping["H2"] == "H2"


def test_resolver_respects_never_merge_list():
    resolver = EntityResolver(threshold=0.85, never_merge=[("MF_01", "MF_02")])
    mapping = resolver.fit_resolve(
        [
            {
                "id": "MF_01",
                "name": "Mossack Fonseca & Co.",
                "type": "Intermediaire",
                "country": "PAN",
            },
            {
                "id": "MF_02",
                "name": "Mossack Fonseca & Partners",
                "type": "Intermediaire",
                "country": "VGB",
            },
        ]
    )
    assert mapping["MF_02"] == "MF_02"


def test_entity_resolver_merging():
    resolver = EntityResolver(threshold=0.85)
    candidates = [
        {"id": "MF_01", "name": "Mossack Fonseca & Co.", "type": "Intermediaire", "country": "PAN"},
        {
            "id": "MF_02",
            "name": "Mossack Fonseca & Partners Ltd.",
            "type": "Intermediaire",
            "country": "VGB",
        },
        {"id": "SH_01", "name": "Albatross Maritime Corp.", "type": "Societe", "country": "VGB"},
    ]
    mapping = resolver.fit_resolve(candidates)

    # MF_02 doit être résolu vers MF_01
    assert mapping["MF_02"] == "MF_01"
    assert mapping["MF_01"] == "MF_01"
    assert mapping["SH_01"] == "SH_01"
    assert len(resolver.merge_history) == 1
