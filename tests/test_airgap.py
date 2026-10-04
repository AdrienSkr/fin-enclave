import pytest

from fin_enclave.config import Settings


def test_local_gx10_rejects_remote_host():
    s = Settings(llm_backend="local_gx10", local_llm_url="https://api.example.com/v1")
    with pytest.raises(ValueError, match="Air-gap"):
        s.get_effective_base_url()


def test_local_gx10_accepts_localhost():
    s = Settings(llm_backend="local_gx10", local_llm_url="http://127.0.0.1:8000/v1")
    assert s.get_effective_base_url() == "http://127.0.0.1:8000/v1"
