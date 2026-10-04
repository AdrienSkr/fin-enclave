import json
from pathlib import Path

from fin_enclave.documents.forge import scenario_path, truth_path
from fin_enclave.documents.forge_complex import (
    _build_statement_pages,
    forge_complex_dossier,
)
from fin_enclave.ingestion.ibm_aml import parse_ibm_patterns, select_attempts

MOCK_PATTERNS = """
BEGIN LAUNDERING ATTEMPT - FAN-OUT: Max 3-degree Fan-Out
2022/09/01 00:06,021174,ACC001,012,ACC002,2848.96,Euro,2848.96,Euro,ACH,1
2022/09/01 04:33,021174,ACC001,020,ACC003,8630.40,Euro,8630.40,Euro,ACH,1
2022/09/01 09:14,021174,ACC001,020,ACC004,3564.00,Euro,3564.00,Euro,ACH,1
END LAUNDERING ATTEMPT - FAN-OUT

BEGIN LAUNDERING ATTEMPT - CYCLE: Max 3 hops
2022/09/01 01:00,010,ACC010,020,ACC020,15000.00,US Dollar,15000.00,US Dollar,ACH,1
2022/09/02 02:00,020,ACC020,030,ACC030,14750.00,US Dollar,14750.00,US Dollar,ACH,1
2022/09/03 03:00,030,ACC030,010,ACC010,14500.00,US Dollar,14500.00,US Dollar,ACH,1
END LAUNDERING ATTEMPT - CYCLE
"""

MOCK_CASE = [
    {
        "node": "C1",
        "name": "TEST HOLDINGS LTD",
        "jurisdiction": "British Virgin Islands",
        "incorporated": "2010-01-01",
        "intermediary": "TEST AGENT LTD",
        "officers": [{"name": "JOHN DOE", "role": "director"}],
    },
    {
        "node": "C2",
        "name": "TEST TRADING CORP",
        "jurisdiction": "Panama",
        "incorporated": "2012-05-12",
        "intermediary": "TEST AGENT LTD",
        "officers": [{"name": "JANE SMITH", "role": "shareholder"}],
    },
]


def test_forge_complex_dossier_truth_and_scenario(tmp_path):
    out_dir = tmp_path / "complex_dossier"
    attempts = parse_ibm_patterns(MOCK_PATTERNS)
    selected = select_attempts(attempts, seed=42, typologies=["CYCLE", "FAN-OUT"])

    pieces = forge_complex_dossier(
        case=MOCK_CASE,
        ibm_attempts=selected,
        out_dir=out_dir,
        n_distractors=2,
        seed=42,
        anonymize=False,
        render_images=False,  # Forge rapide sans OCR ni rendu graphique
    )

    assert len(pieces) > 0
    t_file = truth_path(out_dir)
    s_file = scenario_path(out_dir)
    assert t_file.exists()
    assert s_file.exists()

    truth = json.loads(t_file.read_text(encoding="utf-8"))
    scenario = json.loads(s_file.read_text(encoding="utf-8"))

    # Vérification que toutes les transactions IBM sélectionnées sont dans le scénario
    assert "ibm_patterns" in scenario
    assert len(scenario["ibm_patterns"]) == 2

    # Vérification que toutes les transactions IBM sont présentes dans la vérité terrain
    all_truth_txs = [tx for p in truth for tx in p.get("transfers", [])]
    for pattern in scenario["ibm_patterns"]:
        for exp_tx in pattern["tx"]:
            match = any(
                tx["amount"] == exp_tx["amount"]
                and tx["currency"] == exp_tx["currency"]
                and tx["payer"] == exp_tx["payer"]
                and tx["payee"] == exp_tx["payee"]
                for tx in all_truth_txs
            )
            assert match, f"Transaction non retrouvée dans truth.json : {exp_tx}"


def test_multi_page_statement_balance_consistency():
    import random

    rng = random.Random(123)

    holder = {
        "name": "ACME CORP",
        "kind": "Societe",
        "currency": "EUR",
        "lang": "fr",
        "iban": "FR76 1234 5678 9012",
    }
    # Crée 80 mouvements pour forcer au moins 3 pages avec LINES_PER_PAGE=34
    laundering = [
        {
            "date": f"2022-09-{(i % 25) + 1:02d}",
            "description": f"VIR SEPA REF 100{i} FOO CORP",
            "amount": 1000.0 + i * 10,
            "is_debit": (i % 2 == 0),
            "counterparty": "FOO CORP",
            "counterparty_kind": "Societe",
        }
        for i in range(80)
    ]

    pages = _build_statement_pages(holder, laundering, [], rng)
    assert len(pages) >= 3

    # Vérification de la cohérence des soldes d'une page à la suivante
    for p_idx in range(len(pages) - 1):
        curr_page_lines = pages[p_idx][1]
        next_page_lines = pages[p_idx + 1][1]

        # La dernière ligne de la page courante est le solde à reporter
        carried_line = curr_page_lines[-1][0]
        carried_bal = carried_line.split("\t")[-1].strip()

        # La première ligne après l'en-tête de la page suivante est le solde reporté
        # Ligne d'en-tête tableau = index 6, donc ligne de report = index 7
        brought_line = next_page_lines[7][0]
        brought_bal = brought_line.split("\t")[-1].strip()

        assert carried_bal == brought_bal, (
            f"Incohérence entre page {p_idx + 1} et {p_idx + 2}: {carried_bal} != {brought_bal}"
        )


def test_forge_complex_stress_non_regression_seed_1(tmp_path):
    """Vérifie la non-régression stricte du preset STRESS avec seed=1 (empreintes calculées avant refactor)."""
    import hashlib

    from fin_enclave.documents.forge_complex import STRESS

    cas_file = Path("data/demo/complexe.cas_icij.json")
    patterns_file = Path("data/external/ibm_aml/HI-Small_Patterns.txt")
    if not cas_file.exists() or not patterns_file.exists():
        import pytest

        pytest.skip("Fichiers de données complexes ou IBM AML non disponibles")

    raw = json.loads(cas_file.read_text(encoding="utf-8"))
    all_att = parse_ibm_patterns(patterns_file)
    sel_att = select_attempts(all_att, seed=1)

    out_dir = tmp_path / "complexe"
    pieces = forge_complex_dossier(
        case=raw,
        ibm_attempts=sel_att,
        out_dir=out_dir,
        seed=1,
        anonymize=False,
        render_images=False,
        difficulty=STRESS,
    )
    t_bytes = (tmp_path / "complexe.truth.json").read_bytes()
    s_bytes = (tmp_path / "complexe.scenario.json").read_bytes()

    assert len(pieces) == 54
    assert (
        hashlib.sha256(t_bytes).hexdigest()
        == "cde64bc5ade22ae65c1b52c25f168150452b8e8f73a3c569938e6eea07f855d3"
    )
    assert (
        hashlib.sha256(s_bytes).hexdigest()
        == "549dbfcd9c9ca0d3159d3fdcb37e5af16113e0855e5ceaba2ef6128b0a151acb"
    )


def test_forge_complex_realiste_invariants(tmp_path):
    """
    Vérifie les invariants du preset REALISTE :
    - au plus 20 lignes par page, police 20 pt
    - bruit entre 3 et 12 par compte
    - 3 typologies ciblées (CYCLE, FAN-OUT, SCATTER-GATHER)
    - chaque contrepartie attendue apparaît dans le libellé de sa ligne
    - aucun relevé n'est une photo (clean ou scan seulement)
    """
    import random

    from fin_enclave.documents.forge_complex import REALISTE, _get_noise_debits

    assert REALISTE.lines_per_page == 20
    assert REALISTE.statement_font_size == 20
    assert REALISTE.min_noise == 3
    assert REALISTE.max_noise == 12
    assert REALISTE.statement_qualities == ("clean", "scan")
    assert REALISTE.typologies == ["CYCLE", "FAN-OUT", "SCATTER-GATHER"]

    # Tous les libellés de bruit en réaliste contiennent {vendor}
    for lang in ("en", "fr", "es"):
        debits = _get_noise_debits(lang, fix_noise_labels=True)
        assert all("{vendor}" in d for d in debits)

    cas_file = Path("data/demo/complexe.cas_icij.json")
    patterns_file = Path("data/external/ibm_aml/HI-Small_Patterns.txt")
    if not cas_file.exists() or not patterns_file.exists():
        import pytest

        pytest.skip("Fichiers de données complexes ou IBM AML non disponibles")

    raw = json.loads(cas_file.read_text(encoding="utf-8"))
    all_att = parse_ibm_patterns(patterns_file)
    sel_att = select_attempts(all_att, seed=1, typologies=REALISTE.typologies)

    out_dir = tmp_path / "realiste"
    pieces = forge_complex_dossier(
        case=raw,
        ibm_attempts=sel_att,
        out_dir=out_dir,
        seed=1,
        anonymize=False,
        render_images=False,
        difficulty=REALISTE,
    )

    t_file = truth_path(out_dir)
    s_file = scenario_path(out_dir)
    truth = json.loads(t_file.read_text(encoding="utf-8"))
    scenario = json.loads(s_file.read_text(encoding="utf-8"))

    # 1. 3 typologies ciblées
    found_typos = [p["typology"] for p in scenario["ibm_patterns"]]
    assert found_typos == ["CYCLE", "FAN-OUT", "SCATTER-GATHER"]

    # 2. Aucun relevé n'est une photo et chaque transfert a ses contreparties nommées
    stmts = [p for p in pieces if p.doc_type == "bank_statement"]
    assert len(stmts) > 0
    for s in stmts:
        assert s.quality in ("clean", "scan")
        assert s.quality != "photo"

    truth_stmts = [p for p in truth if p["doc_type"] == "bank_statement"]
    assert len(truth_stmts) > 0
    for p in truth_stmts:
        assert len(p["transfers"]) > 0
        for tx in p["transfers"]:
            assert tx["payer"] and tx["payee"]

    # 3. Pagination : au plus 20 lignes de mouvements par page
    holder = {
        "name": "TEST REAL CORP",
        "kind": "Societe",
        "currency": "EUR",
        "lang": "fr",
        "iban": "FR76 1111 2222 3333",
    }
    sample_moves = [
        {
            "date": f"2022-09-{(i % 20) + 1:02d}",
            "description": f"Virement salaires mensuels REF 100{i} - Employe {i}",
            "amount": 500.0,
            "is_debit": True,
            "counterparty": f"Employe {i}",
            "counterparty_kind": "PersonnePhysique",
        }
        for i in range(45)
    ]
    pages = _build_statement_pages(holder, sample_moves, [], random.Random(42), REALISTE)
    assert len(pages) == 3  # 20 + 20 + 5 lignes
    for p in pages:
        transfers = p[5]
        assert len(transfers) <= 20
