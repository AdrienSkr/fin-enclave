"""
Couche OCR déterministe (Tesseract) : texte, mots et boîtes englobantes.

Sert (1) de moteur de secours hors ligne et (2) de témoin INDÉPENDANT pour vérifier que chaque
entité proposée par le modèle de vision figure réellement sur la pièce (anti-hallucination).
"""

import csv
import hashlib
import io
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from ..config import settings
from ..graph.resolver import jaro_winkler_similarity, normalize_entity_name
from ..schemas import BoundingBox

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".pdf"}
_WINDOWS_DEFAULT = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_PDF_LOCK = threading.Lock()


def load_page_image(path: Path, dpi: int = 150) -> Image.Image:
    """Première page d'une pièce sous forme d'image (PDF rendus via pdfium)."""
    if path.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium

        with _PDF_LOCK:
            pdf = pdfium.PdfDocument(str(path))
            try:
                return pdf[0].render(scale=dpi / 72).to_pil().convert("L")
            finally:
                pdf.close()
    return Image.open(path).convert("L")


def tesseract_path() -> str | None:
    if settings.tesseract_cmd:
        return settings.tesseract_cmd
    found = shutil.which("tesseract")
    if found:
        return found
    return str(_WINDOWS_DEFAULT) if _WINDOWS_DEFAULT.exists() else None


@dataclass
class OcrWord:
    text: str
    conf: float
    box: tuple[int, int, int, int]  # x0, y0, x1, y1 en pixels
    line_key: tuple[int, int, int]


@dataclass
class OcrPage:
    width: int
    height: int
    words: list[OcrWord]

    @property
    def lines(self) -> list[str]:
        grouped: dict[tuple[int, int, int], list[str]] = {}
        for w in self.words:
            grouped.setdefault(w.line_key, []).append(w.text)
        return [" ".join(ws) for _, ws in sorted(grouped.items())]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def ground(self, name: str, threshold: float = 0.88) -> tuple[float, BoundingBox | None]:
        """
        Part des mots du nom retrouvés (similarité >= threshold) parmi les mots OCR,
        et boîte englobante normalisée des mots retrouvés.
        """
        tokens = [t for t in normalize_entity_name(name).split() if len(t) >= 2]
        normalize = normalize_entity_name
        if not tokens:  # nom composé uniquement de formes juridiques / mots-outils
            tokens = [t for t in re.sub(r"[^\w\s]", " ", name.upper()).split() if len(t) >= 2]

            def _normalize_fallback(s: str) -> str:
                return re.sub(r"[^\w]", "", s.upper())

            normalize = _normalize_fallback
        if not tokens:
            return 0.0, None
        norm_words = [(normalize(w.text), w) for w in self.words]
        hits: list[OcrWord] = []
        for t in tokens:
            best = max(
                ((jaro_winkler_similarity(t, nw), w) for nw, w in norm_words if nw),
                key=lambda x: x[0],
                default=(0.0, None),
            )
            if best[0] >= threshold and best[1] is not None:
                hits.append(best[1])
        score = len(hits) / len(tokens)
        if not hits:
            return score, None
        box = BoundingBox(
            xmin=round(min(w.box[0] for w in hits) / self.width, 5),
            ymin=round(min(w.box[1] for w in hits) / self.height, 5),
            xmax=round(max(w.box[2] for w in hits) / self.width, 5),
            ymax=round(max(w.box[3] for w in hits) / self.height, 5),
        )
        return score, box


def run_tesseract(img: Image.Image, psm: int = 4) -> OcrPage | None:
    """OCR Tesseract (sortie TSV). None si Tesseract n'est pas installé."""
    exe = tesseract_path()
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "page.png"
        img.save(png)
        proc = subprocess.run(
            [exe, str(png), "stdout", "--psm", str(psm), "-l", "eng", "tsv"],
            capture_output=True,
            check=False,
        )
    if proc.returncode != 0:
        return None
    words: list[OcrWord] = []
    reader = csv.DictReader(
        io.StringIO(proc.stdout.decode("utf-8", errors="replace")),
        delimiter="\t",
        quoting=csv.QUOTE_NONE,
    )
    for r in reader:
        text = (r.get("text") or "").strip()
        if r.get("level") != "5" or not text:
            continue
        conf = float(r.get("conf") or -1)
        if conf < 0:
            continue
        x, y, w, h = (int(r[k]) for k in ("left", "top", "width", "height"))
        words.append(
            OcrWord(
                text,
                conf,
                (x, y, x + w, y + h),
                (int(r["block_num"]), int(r["par_num"]), int(r["line_num"])),
            )
        )
    return OcrPage(img.width, img.height, words)
