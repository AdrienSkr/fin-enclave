import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class Settings(BaseSettings):
    """
    Configuration globale de FinEnclave.
    Supporte le basculement transparent entre OpenRouter (dev/test)
    et le serveur vLLM local déployé sur la puce NVIDIA GB10 de l'ASUS Ascent GX10.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Backend LLM : 'openrouter', 'openai', 'local_gx10' ou 'mock'
    llm_backend: Literal["openrouter", "openai", "local_gx10", "mock"] = "openrouter"

    # Endpoints et clés d'API
    openrouter_api_key: str = ""
    openai_api_key: str = ""
    llm_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "qwen/qwen3-vl-235b-a22b-instruct"
    local_llm_url: str = "http://localhost:8000/v1"
    # Modèle de vision (lecture des pièces) : ≈ 120 Go en 4 bits, ne tient que sur le GX10
    vlm_model: str = "qwen/qwen3-vl-235b-a22b-instruct"
    tesseract_cmd: str = ""
    extraction_cache_dir: Path = Path("data/cache/extractions")

    output_dir: Path = Path("data/outputs")

    # Options d'investigation
    auto_open_graph: bool = True
    strict_iso_27037: bool = True

    def get_effective_api_key(self) -> str:
        """Détermine la clé d'API active selon le backend sélectionné."""
        if self.llm_backend == "local_gx10":
            return self.llm_api_key or "EMPTY"
        if self.llm_api_key:
            return self.llm_api_key
        if self.llm_backend == "openrouter" and self.openrouter_api_key:
            return self.openrouter_api_key
        if self.openai_api_key:
            return self.openai_api_key
        return os.getenv("OPENROUTER_API_KEY", os.getenv("OPENAI_API_KEY", ""))

    def get_effective_base_url(self) -> str:
        """Détermine l'URL de base active selon le backend (et vérifie l'air-gap)."""
        if self.llm_backend == "local_gx10":
            url = self.local_llm_url
            host = urlparse(url).hostname or ""
            if host not in LOCAL_HOSTS:
                raise ValueError(
                    f"Air-gap violé : en mode local_gx10, l'hôte LLM doit être local "
                    f"(reçu : '{host}')."
                )
            return url
        return self.llm_base_url


settings = Settings()
