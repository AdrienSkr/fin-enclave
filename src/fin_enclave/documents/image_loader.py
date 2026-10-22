"""
Utilitaires légers de chargement et de conversion d'images et de PDF.
"""

import base64
import hashlib
import io
import threading
from pathlib import Path

from PIL import Image

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".pdf"}

_PDF_LOCK = threading.Lock()


def file_sha256(path: Path) -> str:
    """Empreinte SHA-256 du fichier, utilisée comme clé de cache interne pour les extractions."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def page_count(path: Path) -> int:
    """Nombre de pages d'une pièce (1 pour une image ; PDF comptés via pypdfium2)."""
    if path.suffix.lower() != ".pdf":
        return 1
    import pypdfium2 as pdfium

    with _PDF_LOCK:
        pdf = pdfium.PdfDocument(str(path))
        try:
            return max(1, len(pdf))
        finally:
            pdf.close()


def load_page_image(path: Path, dpi: int = 150, page: int = 0) -> Image.Image:
    """Rend la page `page` d'une pièce sous forme d'image PIL (en niveaux de gris)."""
    if path.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium

        with _PDF_LOCK:
            pdf = pdfium.PdfDocument(str(path))
            try:
                return pdf[page].render(scale=dpi / 72).to_pil().convert("L")
            finally:
                pdf.close()
    return Image.open(path).convert("L")


def image_data_url(img: Image.Image, max_side: int = 1600, quality: int = 85) -> str:
    """Encode une image en data URL JPEG base64 (format des API de vision)."""
    img_copy = img.copy()
    img_copy.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img_copy.convert("RGB").save(buf, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
