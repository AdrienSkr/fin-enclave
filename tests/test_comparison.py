from types import SimpleNamespace

from fin_enclave.comparison import TIERS
from fin_enclave.reasoning.qualifier import _llm_note


def test_small_and_large_models_share_one_family():
    cpu, small, large = TIERS
    assert cpu.model is None
    assert small.model.startswith("qwen/qwen3-vl-") and large.model.startswith("qwen/qwen3-vl-")


def test_llm_note_replays_from_cache_without_client(tmp_path):
    payload = {"constat_deterministe": "Circuit fermé. Pièces : PIECE-0001."}
    message = SimpleNamespace(content='{"summary_note": "N"}')
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    completions = SimpleNamespace(create=lambda **_: response)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    assert _llm_note(client, "m", payload, tmp_path) == "N"
    assert _llm_note(None, "m", payload, tmp_path) == "N"
    assert _llm_note(None, "autre-modele", payload, tmp_path) is None
