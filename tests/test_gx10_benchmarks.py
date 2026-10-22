import json
import sys
from pathlib import Path

from fin_enclave.documents.forge import forge_charge_500, forge_dossier

# Ajouter scripts au path pour tester audit_memory_sizing
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from audit_memory_sizing import (
    SPECS,
    compute_kv_token_bytes,
    evaluate_memory_verdict,
)


def _mock_forge_graphics(monkeypatch):
    """Court-circuite le rendu d'image et le filtre de dégradation Pillow pour les tests."""

    def mock_save(img, out_dir, piece_id, quality):
        fname = f"{piece_id}.png"
        (out_dir / fname).write_bytes(b"")
        return fname

    monkeypatch.setattr("fin_enclave.documents.forge._render", lambda *args, **kwargs: None)
    monkeypatch.setattr("fin_enclave.documents.forge._degrade", lambda *args, **kwargs: None)
    monkeypatch.setattr("fin_enclave.documents.forge._save", mock_save)


def test_forge_dossier_default_50_pieces(tmp_path, monkeypatch):
    _mock_forge_graphics(monkeypatch)
    case_path = Path("data/demo/pieces.cas_icij.json")
    assert case_path.exists(), "Fichier de cas ICIJ de référence manquant"
    case = json.loads(case_path.read_text(encoding="utf-8"))

    # Test avec la valeur par défaut de n_distractors (12)
    out_dir = tmp_path / "pieces_50"
    pieces = forge_dossier(case, out_dir, seed=101, with_money=True, anonymize=True)
    assert len(pieces) == 50
    assert len(list(out_dir.glob("PIECE-*"))) == 50

    truth = json.loads((tmp_path / "pieces_50.truth.json").read_text(encoding="utf-8"))
    assert len(truth) == 50
    assert sum(p["doc_type"] == "invoice" for p in truth) == 12


def test_forge_charge_500_generates_distinct_cases(tmp_path, monkeypatch):
    _mock_forge_graphics(monkeypatch)
    base_dir = tmp_path / "charge_test"
    # Génère 2 affaires pour valider la génération sans surcharger la machine
    cases = forge_charge_500(base_dir, n_cases=2, seed_start=101)
    assert len(cases) == 2
    assert cases[0].name == "affaire_01"
    assert cases[1].name == "affaire_02"

    for c in cases:
        assert len(list(c.glob("PIECE-*"))) == 50
        truth_file = base_dir / f"{c.name}.truth.json"
        scenario_file = base_dir / f"{c.name}.scenario.json"
        assert truth_file.exists()
        assert scenario_file.exists()

        truth = json.loads(truth_file.read_text(encoding="utf-8"))
        scenario = json.loads(scenario_file.read_text(encoding="utf-8"))
        assert len(truth) == 50
        assert scenario.get("simulated") is True


def test_audit_memory_sizing_kv_bytes():
    # 72B : 80 couches, 8 têtes KV, dim 128
    # FP8 (1 octet) : 2 * 80 * 8 * 128 * 1 = 163,840 octets (160 KiB)
    spec_72b = SPECS["72b"]
    assert compute_kv_token_bytes(spec_72b, "fp8") == 163_840
    assert compute_kv_token_bytes(spec_72b, "fp16") == 327_680

    # 124B : 88 couches, 8 têtes KV, dim 128
    # FP8 : 2 * 88 * 8 * 128 * 1 = 180,224 octets (176 KiB)
    spec_124b = SPECS["124b"]
    assert compute_kv_token_bytes(spec_124b, "fp8") == 180_224

    # 8B : 36 couches, 8 têtes KV, dim 128
    # FP8 : 2 * 36 * 8 * 128 * 1 = 73,728 octets (72 KiB)
    spec_8b = SPECS["8b"]
    assert compute_kv_token_bytes(spec_8b, "fp8") == 73_728

    # 235B : 96 couches, 8 têtes KV, dim 128
    # FP8 : 2 * 96 * 8 * 128 * 1 = 196,608 octets (192 KiB)
    spec_235b = SPECS["235b"]
    assert compute_kv_token_bytes(spec_235b, "fp8") == 196_608


def test_audit_memory_sizing_budget_verdicts():
    # Vérification que 72b FP8 rentre sous le cap 119.2 GiB (verdict VALIDE avec pool KV suffisant)
    v_72b = evaluate_memory_verdict(SPECS["72b"], quant="fp8")
    assert v_72b.verdict == "VALIDE"
    assert v_72b.remaining_kv_pool_gib > 30.0

    # Vérification que 235b FP8 dépasse le cap (verdict ECHEC OOM physique)
    v_235b = evaluate_memory_verdict(SPECS["235b"], quant="fp8")
    assert v_235b.verdict == "ECHEC"
    assert v_235b.remaining_kv_pool_gib < 0.0
