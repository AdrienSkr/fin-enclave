"""
Lecture des relevés par PaddleOCR-VL servi par vLLM/OpenAI, puis analyse
déterministe du tableau (statement_table.parse_statement).
"""

import hashlib
import re
from typing import Any

from openai import OpenAIError
from PIL import Image

from ..config import settings
from .image_loader import image_data_url
from .models import DocumentExtraction
from .statement_table import PARSER_VERSION, parse_statement

OCR_PROMPT = "OCR:"
TABLE_PROMPT = "Table Recognition:"
MAX_OUTPUT_TOKENS = 4096
IMAGE_MAX_SIDE = 2048
TABLE_PROMPT_VERSION = hashlib.sha256(
    f"{OCR_PROMPT}\n{TABLE_PROMPT}\nparser{PARSER_VERSION}\nside{IMAGE_MAX_SIDE}".encode()
).hexdigest()[:8]


class TableEngine:
    """Lecteur de relevés (T2) : page -> sortie brute PaddleOCR-VL -> `DocumentExtraction`."""

    name = "table"
    supports_retry_hint = False

    def __init__(self, model: str | None = None, client=None):
        self.model = model or settings.table_model
        if client is None:
            from openai import OpenAI

            client = OpenAI(
                base_url=settings.table_base_url,
                api_key=settings.get_effective_api_key() or "EMPTY",
                timeout=300,
            )
        self.client = client

    @property
    def slug(self) -> str:
        return f"table-{re.sub(r'[^a-z0-9]+', '-', self.model.lower())}-p{TABLE_PROMPT_VERSION}"

    def _ask(self, image: dict, prompt: str) -> str:
        messages = [
            {"role": "user", "content": [image, {"type": "text", "text": prompt}]},
        ]
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.0,
                max_tokens=MAX_OUTPUT_TOKENS,
            )
        except OpenAIError as exc:
            raise RuntimeError(f"Lecteur de tableaux indisponible : {exc}") from exc
        return resp.choices[0].message.content or ""

    def read_raw(self, img: Image.Image) -> str:
        """Sortie brute : texte de la page (en-tête) puis tableau, séparés par une ligne vide."""
        image = {"type": "image_url", "image_url": {"url": image_data_url(img, IMAGE_MAX_SIDE, 92)}}
        return f"{self._ask(image, OCR_PROMPT)}\n\n{self._ask(image, TABLE_PROMPT)}"

    def extract(self, img: Image.Image, *args: Any, **kwargs: Any) -> DocumentExtraction:
        raw = self.read_raw(img)
        if not raw.strip():
            raise RuntimeError("Lecteur de tableaux : sortie vide")
        return parse_statement(raw)
