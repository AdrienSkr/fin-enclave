import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Source unique des identifiants de modèles (comparison.py, bancs, etc.).
MODEL_SMALL = "Qwen/Qwen3-VL-8B-Instruct"  # taille RTX
MODEL_LARGE = "Qwen/Qwen3-VL-235B-A22B-Instruct"  # référence hors GX10
MODEL_GX10 = "Qwen/Qwen2.5-VL-72B-Instruct"
MODEL_T1 = "RedHatAI/Qwen2.5-VL-72B-Instruct-FP8-dynamic"  # actes et gouvernance
MODEL_T2 = "PaddlePaddle/PaddleOCR-VL-1.6"  # tableaux de relevés

# Seuil réglementaire de déclaration : une seule valeur pour config, détecteur et rapport
DEFAULT_SMURF_THRESHOLD_USD = 10_000.0
# Devise absente de la pièce (ISO 4217 « aucune devise ») : jamais devinée, jamais convertie.
UNPRINTED_CURRENCY = "XXX"


class Settings(BaseSettings):
    """
    Configuration globale de FinEnclave.
    Client standard OpenAI pour le VLM principal et le modèle tabulaire.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_base_url: str = "http://localhost:8000/v1"
    table_base_url: str = "http://localhost:8001/v1"
    llm_api_key: str = ""
    vlm_model: str = MODEL_T1
    table_model: str = MODEL_T2

    # Requêtes d'extraction en vol
    extraction_workers: int = 8
    extraction_cache_dir: Path = Path("data/cache/extractions")

    output_dir: Path = Path("data/outputs")

    # Seuil de fractionnement (USD) sous lequel un virement est jugé « sous le seuil déclaratif »
    smurf_threshold_usd: float = DEFAULT_SMURF_THRESHOLD_USD

    def get_effective_api_key(self) -> str:
        """Détermine la clé d'API active."""
        if self.llm_api_key:
            return self.llm_api_key
        return os.getenv("OPENROUTER_API_KEY", os.getenv("OPENAI_API_KEY", ""))

    def get_effective_base_url(self) -> str:
        """Détermine l'URL de base active."""
        return self.llm_base_url

    @property
    def llm_model(self) -> str:
        return self.vlm_model

    @property
    def t1_model(self) -> str:
        return self.vlm_model

    @property
    def t2_model(self) -> str:
        return self.table_model


settings = Settings()
