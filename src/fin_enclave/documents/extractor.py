"""
Extraction d'entités et de relations depuis des pièces hétérogènes (scans, photos, PDF image).

Moteurs :
- `vlm`   : modèle de vision (Qwen3-VL) via API compatible OpenAI ; OpenRouter en développement,
            vLLM local (localhost) sur le GX10. Sortie validée par le schéma `DocumentExtraction`.
- `rules` : secours hors ligne, Tesseract + règles lexicales (formes juridiques, mots-clés de rôle).

Garde-fous :
- toute entité proposée est confrontée à la couche OCR Tesseract indépendante (`grounded`) ;
- les réponses sont mises en cache par empreinte de pièce + moteur (reproductibilité, rejouable
  hors ligne) ; une réponse invalide n'est jamais « réparée » avec des valeurs par défaut.
"""

import base64
import hashlib
import io
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openai import OpenAIError
from PIL import Image
from pydantic import ValidationError

from ..config import settings
from .models import (
    DocumentExtraction,
    ExtractedEntity,
    ExtractedRelation,
    ExtractedTransfer,
    GroundedEntity,
    GroundedTransfer,
    PieceExtraction,
)
from .ocr import IMAGE_SUFFIXES, OcrPage, file_sha256, load_page_image, run_tesseract

logger = logging.getLogger("fin_enclave.documents")

SYSTEM_PROMPT = """Tu es l'étage d'extraction d'une station d'investigation financière.
On te montre UNE pièce (scan, photo ou PDF image) issue d'un dossier saisi.
Extrais uniquement ce qui est écrit sur la pièce :
- doc_type : nature de la pièce ; une pièce avec des colonnes Date / Débit / Crédit / Solde et
  un titulaire est un bank_statement, quelle que soit la langue (« Relevé de compte »,
  « Extracto de cuenta ») ;
- entities : chaque société, personne, intermédiaire (registered agent, cabinet) ou adresse,
  avec le nom EXACTEMENT tel qu'écrit (orthographe, casse, ponctuation) ;
- relations : qui est director / shareholder / beneficial_owner / secretary de quelle société,
  qui reçoit une procuration sur une société (attorney), quel intermédiaire (intermediary)
  enregistre quelle société, quelle adresse (registered_address).
  Sens : source = la personne ou l'entité qui détient / dirige / reçoit la procuration,
  target = la société. Sur une procuration, la personne nommée mandataire ('appoint ... as
  attorney') est la source du rôle attorney ; le signataire garde son rôle propre.
  Une société mentionnée comme 'Shareholder' ou 'Director' est une entité à part entière.
  Un paiement n'est jamais une relation : sur un ordre de virement, un relevé bancaire ou une
  facture, relations est vide.
- transfers : chaque ordre de virement écrit : payer = donneur d'ordre, payee = bénéficiaire,
  amount = montant positif, currency = code ISO, date = date de valeur au format AAAA-MM-JJ.
- relevé bancaire : NE remplis PAS transfers. Recopie account_holder (titulaire du compte) et,
  dans statement_lines, chaque ligne de mouvement : date, counterparty (le nom de la contrepartie
  seul, sans le libellé de l'opération ni la référence), amount = montant SIGNÉ exactement comme
  imprimé (un débit imprimé '-9,400.00' donne -9400.0), currency du compte. En cas de colonnes
  Débit / Crédit séparées : un débit devient un montant négatif ; un solde reporté n'est pas un
  mouvement. Les soldes (opening / closing balance) ne sont pas des lignes de mouvement.
  Les montants d'une facture non payée ne sont pas des mouvements.
  Les parties des virements et des relevés figurent aussi dans entities.
Ne sont PAS des entités : les titres, en-têtes de colonnes, tampons et mentions de fonction
('Shareholder', 'Registrar', 'Certified'), les montants, les références et numéros de compte,
et les pays ou juridictions seuls (une adresse comporte une rue, un bâtiment ou une boîte postale).
Une relation commerciale (facture, client, fournisseur) n'est ni une détention ni un mandat :
utilise le rôle 'other'.
N'invente rien, ne complète rien, ne déduis aucun lien qui n'est pas écrit.
Réponds uniquement par un objet JSON conforme au schéma fourni."""
USER_PROMPT = "Extrais cette pièce."
MIN_WITNESS_WORDS = 15
PROMPT_VERSION = hashlib.sha256(
    f"{SYSTEM_PROMPT}\n{USER_PROMPT}\nimage-first".encode()
).hexdigest()[:8]

_COMPANY_RE = re.compile(
    r"\b(LIMITED|LTD\.?|INC\.?|CORP\.?|CORPORATION|S\.?A\.?|LLC|PTE\.?|PLC|N\.V\.|B\.V\.|"
    r"FOUNDATION|TRUST|HOLDINGS?)\s*$",
    re.IGNORECASE,
)
_ROLE_RE = re.compile(
    r"^(?P<name>.+?)\s+(?P<role>Beneficial Owner|Shareholder|Director|Secretary)\s*$",
    re.IGNORECASE,
)
_ROLE_MAP = {
    "beneficial owner": "beneficial_owner",
    "shareholder": "shareholder",
    "director": "director",
    "secretary": "secretary",
}
_AMOUNT_RE = re.compile(r"(?P<cur>[A-Z]{3})\s*(?P<amt>[\d][\d,' ]*\.\d{2})")
_STATEMENT_RE = re.compile(
    r"^(?P<date>\d{2}/\d{2}/\d{4})\s+Transfer\s+(?P<dir>to|from)\s+(?P<name>.+?)\s+"
    r"(?P<amt>-?[\d][\d,]*\.\d{2})\s*$",
    re.IGNORECASE,
)
_POA_GRANTOR_RE = re.compile(
    r"^We,\s*(?P<name>.+?),\s*acting as (?P<role>[a-z ]+?) of", re.IGNORECASE
)


def _label_value(line: str, label: str) -> str | None:
    """Valeur d'une ligne « Label: valeur » (OCR : séparateurs et espaces variables)."""
    m = re.match(rf"^\s*{label}\s*[:;]?\s*(?P<v>.+)$", line, re.IGNORECASE)
    return m["v"].strip() if m else None


def _amount_on_page(amount: float, ocr: OcrPage) -> bool:
    """Un mot OCR témoin porte-t-il ce montant (unités, ou unités + centimes, sans séparateurs) ?"""
    units = str(int(amount))
    for w in ocr.words:
        digits = re.sub(r"[^\d]", "", w.text)
        if digits in (units, units + f"{round(amount * 100) % 100:02d}"):
            return True
    return False


def _image_data_url(img: Image.Image, max_side: int = 1600) -> str:
    img = img.copy()
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


class VLMEngine:
    name = "vlm"

    def __init__(self, model: str | None = None):
        from openai import OpenAI

        self.model = model or settings.vlm_model
        self.client = OpenAI(
            base_url=settings.get_effective_base_url(),
            api_key=settings.get_effective_api_key() or "EMPTY",
            timeout=120,
        )

    @property
    def slug(self) -> str:
        return f"vlm-{re.sub(r'[^a-z0-9]+', '-', self.model.lower())}-p{PROMPT_VERSION}"

    def extract(self, img: Image.Image, ocr: OcrPage | None) -> DocumentExtraction:
        schema = DocumentExtraction.model_json_schema()
        image = {"type": "image_url", "image_url": {"url": _image_data_url(img)}}
        # Un schéma recopié dans le texte est pris pour un gabarit par certains modèles (réponse
        # vide) : il n'y figure que si le serveur ne sait pas contraindre le décodage.
        attempts = [
            (
                {
                    "type": "json_schema",
                    "json_schema": {"name": "DocumentExtraction", "schema": schema, "strict": True},
                },
                USER_PROMPT,
            ),
            (
                {"type": "json_object"},
                f"{USER_PROMPT}\nSchéma JSON attendu :\n{json.dumps(schema)}",
            ),
        ]
        last_error: Exception | None = None
        for fmt, text in attempts:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [image, {"type": "text", "text": text}]},
            ]
            for attempt_idx in range(4):
                try:
                    resp = self.client.chat.completions.create(
                        model=self.model, messages=messages, temperature=0.0, response_format=fmt
                    )
                    raw = resp.choices[0].message.content or ""
                    match = re.search(r"\{.*\}", raw, re.DOTALL)
                    return DocumentExtraction.model_validate_json(match.group(0) if match else raw)
                except (ValidationError, ValueError) as exc:
                    last_error = exc
                    break
                except OpenAIError as exc:
                    last_error = exc
                    err_str = str(exc).lower()
                    if attempt_idx < 3 and any(
                        w in err_str
                        for w in (
                            "429",
                            "rate",
                            "overloaded",
                            "500",
                            "502",
                            "503",
                            "504",
                            "timeout",
                        )
                    ):
                        time.sleep(2.0 * (attempt_idx + 1))
                        continue
                    break
        raise RuntimeError(f"Extraction VLM invalide ou indisponible : {last_error}")


class RuleEngine:
    """Secours hors ligne : Tesseract + règles lexicales génériques (aucun modèle)."""

    name = "rules"
    slug = "rules-tesseract"

    def extract(self, img: Image.Image, ocr: OcrPage | None) -> DocumentExtraction:
        if ocr is None:
            raise RuntimeError("Tesseract indisponible : aucune extraction possible hors ligne")
        lines = [ln.strip() for ln in ocr.lines if ln.strip()]
        upper = " ".join(lines).upper()
        if "CERTIFICATE OF INCORPORATION" in upper:
            doc_type = "certificate_of_incorporation"
        elif "REGISTER OF DIRECTORS" in upper or "REGISTER OF MEMBERS" in upper:
            doc_type = "register_of_directors"
        elif "POWER OF ATTORNEY" in upper:
            doc_type = "power_of_attorney"
        elif "PAYMENT ORDER" in upper or "MT103" in upper:
            doc_type = "wire_transfer"
        elif "STATEMENT OF ACCOUNT" in upper:
            doc_type = "bank_statement"
        elif "INVOICE" in upper:
            doc_type = "invoice"
        else:
            doc_type = "other"

        entities: dict[str, ExtractedEntity] = {}
        relations: list[ExtractedRelation] = []
        transfers: list[ExtractedTransfer] = []
        subject = ""

        def add(name: str, kind: str) -> str:
            name = name.strip(" .:;,")
            if len(name) >= 3 and name.upper() not in entities:
                entities[name.upper()] = ExtractedEntity(name=name, kind=kind)  # type: ignore[arg-type]
            return name

        def actor(name: str) -> str:
            return add(name, "Societe" if _COMPANY_RE.search(name) else "PersonnePhysique")

        if doc_type == "wire_transfer":
            fields: dict[str, str] = {}
            for ln in lines:
                for label in ("Value date", "Ordering customer", "Beneficiary", "Amount"):
                    value = _label_value(ln, label)
                    if value and label not in fields:
                        fields[label] = value
            m = _AMOUNT_RE.search(fields.get("Amount", ""))
            if m and "Ordering customer" in fields and "Beneficiary" in fields:
                transfers.append(
                    ExtractedTransfer(
                        payer=actor(fields["Ordering customer"]),
                        payee=actor(fields["Beneficiary"]),
                        amount=m["amt"],  # type: ignore[arg-type]
                        currency=m["cur"],
                        date=fields.get("Value date"),  # type: ignore[arg-type]
                    )
                )
            return DocumentExtraction(
                doc_type=doc_type, entities=list(entities.values()), transfers=transfers
            )

        if doc_type == "bank_statement":
            holder = ""
            for ln in lines:
                value = _label_value(ln, "Account holder")
                if value and not holder:
                    holder = actor(value)
                m = _STATEMENT_RE.match(ln)
                if m and holder:
                    other = actor(m["name"])
                    payer, payee = (holder, other) if m["dir"].lower() == "to" else (other, holder)
                    transfers.append(
                        ExtractedTransfer(
                            payer=payer,
                            payee=payee,
                            amount=m["amt"].lstrip("-"),  # type: ignore[arg-type]
                            currency="USD",
                            date=m["date"],  # type: ignore[arg-type]
                        )
                    )
            return DocumentExtraction(
                doc_type=doc_type, entities=list(entities.values()), transfers=transfers
            )

        if doc_type == "power_of_attorney":
            grantor, role = "", ""
            for i, ln in enumerate(lines):
                m = _POA_GRANTOR_RE.match(ln)
                if m:
                    grantor = add(m["name"], "PersonnePhysique")
                    role = m["role"].strip().lower().replace(" ", "_")
                    subject = actor(lines[i - 1]) if i else ""
                elif grantor and "appoint" in lines[i - 1].lower() and not _COMPANY_RE.search(ln):
                    attorney = add(ln, "PersonnePhysique")
                    if subject:
                        relations.append(
                            ExtractedRelation(source=attorney, target=subject, role="attorney")
                        )
            if grantor and subject and role in _ROLE_MAP.values():
                relations.append(ExtractedRelation(source=grantor, target=subject, role=role))  # type: ignore[arg-type]
            return DocumentExtraction(
                doc_type=doc_type, entities=list(entities.values()), relations=relations
            )

        for i, ln in enumerate(lines):
            m_role = _ROLE_RE.match(ln)
            if ln.lower().startswith("registered agent"):
                agent = add(ln.split(":", 1)[-1], "Intermediaire")
                if subject:
                    relations.append(
                        ExtractedRelation(source=agent, target=subject, role="intermediary")
                    )
            elif m_role and doc_type == "register_of_directors" and subject:
                officer = add(m_role["name"], "PersonnePhysique")
                role = _ROLE_MAP[m_role["role"].lower()]
                relations.append(ExtractedRelation(source=officer, target=subject, role=role))  # type: ignore[arg-type]
            elif ln.lower().startswith(("bill to:", "attention:")):
                add(
                    ln.split(":", 1)[-1],
                    "Societe" if _COMPANY_RE.search(ln) else "PersonnePhysique",
                )
            elif _COMPANY_RE.search(ln):
                name = add(ln, "Societe")
                prev = lines[i - 1].lower() if i else ""
                if not subject and ("certify that" in prev or doc_type == "register_of_directors"):
                    subject = name
        return DocumentExtraction(
            doc_type=doc_type,  # type: ignore[arg-type]
            entities=list(entities.values()),
            relations=relations,
        )


def _cache_file(sha: str, slug: str, cache_dir: Path | None = None) -> Path:
    return Path(cache_dir or settings.extraction_cache_dir) / f"{sha[:24]}_{slug}.json"


def cached_coverage(directory: Path | str, engine, cache_dir: Path | None = None) -> float:
    """Part des pièces du dossier dont l'extraction par ce moteur est déjà scellée en cache."""
    files = [p for p in Path(directory).iterdir() if p.suffix.lower() in IMAGE_SUFFIXES]
    if not files:
        return 0.0
    hits = sum(_cache_file(file_sha256(p), engine.slug, cache_dir).exists() for p in files)
    return hits / len(files)


def extract_piece(
    path: Path, engine, use_cache: bool = True, cache_dir: Path | None = None
) -> PieceExtraction:
    sha = file_sha256(path)
    t0 = time.perf_counter()
    img = load_page_image(path)
    ocr = run_tesseract(img)
    cache = _cache_file(sha, engine.slug, cache_dir)
    from_cache = False
    error = ""
    extraction: DocumentExtraction | None = None
    if use_cache and cache.exists():
        extraction = DocumentExtraction.model_validate_json(cache.read_text(encoding="utf-8"))
        from_cache = True
    else:
        try:
            extraction = engine.extract(img, ocr)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(extraction.model_dump_json(indent=2), encoding="utf-8")
        except (RuntimeError, ValidationError) as exc:
            error = str(exc)
            logger.warning("Pièce %s non extraite : %s", path.name, exc)

    # Un témoin OCR qui n'a pas su lire la page ne peut pas attester d'une absence :
    # l'entité est alors « non vérifiable » (None), pas « hallucinée » (False).
    witness_ok = ocr is not None and len(ocr.words) >= MIN_WITNESS_WORDS
    grounded: list[GroundedEntity] = []
    transfers: list[GroundedTransfer] = []
    if extraction:
        resolved = extraction.resolved_transfers()
        entities = list(extraction.entities)
        known = {e.name.upper() for e in entities}
        for t in resolved:  # une partie citée dans un virement est une entité
            for party in (t.payer, t.payee):
                if party.upper() not in known and len(party) >= 2:
                    kind = "Societe" if _COMPANY_RE.search(party) else "PersonnePhysique"
                    entities.append(ExtractedEntity(name=party, kind=kind))  # type: ignore[arg-type]
                    known.add(party.upper())
        for ent in entities:
            score, _ = ocr.ground(ent.name) if ocr else (0.0, None)
            grounded.append(
                GroundedEntity(
                    name=ent.name,
                    kind=ent.kind,
                    grounded=(score >= 0.6) if witness_ok else None,
                    grounding_score=round(score, 3),
                )
            )
        transfers = [
            GroundedTransfer(
                **t.model_dump(),
                amount_grounded=_amount_on_page(t.amount, ocr) if witness_ok and ocr else None,
            )
            for t in resolved
        ]
    return PieceExtraction(
        piece_id=path.stem,
        file=path.name,
        file_sha256=sha,
        engine=engine.slug,
        from_cache=from_cache,
        seconds=round(time.perf_counter() - t0, 3),
        doc_type=extraction.doc_type if extraction else "other",
        entities=grounded,
        relations=extraction.relations if extraction else [],
        transfers=transfers,
        error=error,
    )


def make_engine(kind: str = "auto"):
    """'auto' = VLM si une clé/endpoint est configuré, sinon règles + Tesseract."""
    if kind == "rules":
        return RuleEngine()
    if kind == "vlm":
        return VLMEngine()
    key = settings.get_effective_api_key()
    if settings.llm_backend == "local_gx10" or (key and key != "EMPTY" and "your_" not in key):
        return VLMEngine()
    return RuleEngine()


def extract_dossier(
    directory: Path | str,
    engine=None,
    workers: int = 4,
    use_cache: bool = True,
    cache_dir: Path | None = None,
) -> list[PieceExtraction]:
    """Extrait toutes les pièces d'un dossier (ordre alphabétique, parallélisé)."""
    engine = engine or make_engine()
    files = sorted(p for p in Path(directory).iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda p: extract_piece(p, engine, use_cache, cache_dir), files))
