"""
Extraction d'entités et de relations depuis des pièces hétérogènes (scans, photos, PDF image).

Moteurs :
- `vlm`    : modèle de vision (Qwen-VL) via API compatible OpenAI.
- `routed` : VLM principal pour actes et gouvernance, PaddleOCR-VL / TableEngine pour relevés tabulaires.
"""

import hashlib
import json
import logging
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openai import OpenAIError
from PIL import Image
from pydantic import ValidationError

from ..config import MODEL_GX10, MODEL_T1, settings
from .image_loader import (
    IMAGE_SUFFIXES,
    file_sha256,
    image_data_url,
    load_page_image,
    page_count,
)
from .models import (
    CODE_ONLY_FIELDS,
    DocumentExtraction,
    ExtractedEntity,
    ExtractedRelation,
    ExtractedTransfer,
    GroundedEntity,
    GroundedTransfer,
    PageRelation,
    PieceExtraction,
    StatementLine,
)
from .review_triage import (
    line_amount_flags,
    line_date_flags,
    line_side_flags,
)
from .routing import dated_rows, route_piece
from .table_engine import TableEngine

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
RETRY_HINT = (
    "Relance : la lecture précédente d'un relevé était vide. Transcris TOUTES les lignes de "
    "mouvement dans statement_lines et recopie le titulaire du compte (account_holder)."
)
MAX_OUTPUT_TOKENS = 4096
PROMPT_VERSION = hashlib.sha256(
    f"{SYSTEM_PROMPT}\n{USER_PROMPT}\nimage-first".encode()
).hexdigest()[:8]

_COMPANY_RE = re.compile(
    r"\b(LIMITED|LTD\.?|INC\.?|CORP\.?|CORPORATION|S\.?A\.?|LLC|PTE\.?|PLC|N\.V\.|B\.V\.|"
    r"FOUNDATION|TRUST|HOLDINGS?)\s*$",
    re.IGNORECASE,
)


def vlm_schema() -> dict:
    """Schéma demandé au modèle de vision, sans les champs écrits par le code."""
    schema = DocumentExtraction.model_json_schema()
    for name, fields in CODE_ONLY_FIELDS.items():
        node = schema if name == "DocumentExtraction" else schema.get("$defs", {}).get(name, {})
        for field in fields:
            node.get("properties", {}).pop(field, None)
    return schema


class VLMEngine:
    name = "vlm"
    supports_retry_hint = True

    def __init__(self, model: str | None = None, client=None):
        from openai import OpenAI

        self.model = model or settings.vlm_model
        self.client = client or OpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.get_effective_api_key() or "EMPTY",
            timeout=300,
        )

    @property
    def slug(self) -> str:
        return f"vlm-{re.sub(r'[^a-z0-9]+', '-', self.model.lower())}-p{PROMPT_VERSION}"

    def extract(
        self, img: Image.Image, *args: Any, retry: bool = False, **kwargs: Any
    ) -> DocumentExtraction:
        schema = vlm_schema()
        image = {"type": "image_url", "image_url": {"url": image_data_url(img)}}
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
        if retry:
            attempts = [(fmt, f"{text}\n{RETRY_HINT}") for fmt, text in reversed(attempts)]
        last_error: Exception | None = None
        for fmt, text in attempts:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [image, {"type": "text", "text": text}]},
            ]
            for attempt_idx in range(4):
                try:
                    resp = self.client.chat.completions.create(
                        model=self.model,
                        messages=messages,
                        temperature=0.0,
                        max_tokens=MAX_OUTPUT_TOKENS,
                        response_format=fmt,
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
    """Secours mock déterministe pour rejeu hors ligne (sans Tesseract)."""

    name = "rules"
    slug = "rules-tesseract"

    def extract(self, img: Image.Image, *args: Any, **kwargs: Any) -> DocumentExtraction:
        return DocumentExtraction(doc_type="other")


def _cache_file(sha: str, slug: str, cache_dir: Path | None = None, page: int = 0) -> Path:
    """Scellé d'une page : la page 0 garde le nom historique."""
    tag = "" if page == 0 else f"_pg{page}"
    return Path(cache_dir or settings.extraction_cache_dir) / f"{sha[:24]}{tag}_{slug}.json"


def _n_pages(path: Path) -> int:
    try:
        return page_count(path)
    except Exception:  # noqa: BLE001
        return 1


def _is_cached(engine, sha: str, cache_dir: Path | None = None, page: int = 0) -> bool:
    if hasattr(engine, "is_cached"):
        return engine.is_cached(sha, cache_dir, page)
    return _cache_file(sha, engine.slug, cache_dir, page).exists()


def cached_coverage(directory: Path | str, engine, cache_dir: Path | None = None) -> float:
    """Part des pièces du dossier dont toutes les pages sont déjà scellées pour ce moteur."""
    files = [p for p in Path(directory).iterdir() if p.suffix.lower() in IMAGE_SUFFIXES]
    if not files:
        return 0.0
    hits = sum(
        all(_is_cached(engine, file_sha256(p), cache_dir, page) for page in range(_n_pages(p)))
        for p in files
    )
    return hits / len(files)


def _common_party(transfers: list[ExtractedTransfer]) -> str:
    """Partie présente dans tous les virements : le titulaire probable d'un relevé."""
    if not transfers:
        return ""
    common = None
    names: dict[str, str] = {}
    for t in transfers:
        parties = {t.payer.upper(): t.payer, t.payee.upper(): t.payee}
        names.update(parties)
        common = set(parties) if common is None else common & set(parties)
    return names[next(iter(common))] if common and len(common) == 1 else ""


MIN_WITNESS_WORDS = 10


def _statement_currency(extraction: DocumentExtraction) -> DocumentExtraction:
    return extraction


def normalize_statement(
    extraction: DocumentExtraction, holder_hint: str = ""
) -> DocumentExtraction:
    """Relevé : titulaire et conversion de transfers en statement_lines si nécessaire."""
    if extraction.doc_type != "bank_statement":
        return extraction
    holder = extraction.account_holder or holder_hint
    if not holder:
        holder = _common_party(extraction.transfers) or (
            extraction.entities[0].name if extraction.entities else ""
        )
    update: dict = {}
    if holder and holder != extraction.account_holder:
        update["account_holder"] = holder
    if holder and extraction.transfers and not extraction.statement_lines:
        mine = holder.upper()
        if all(mine in (t.payer.upper(), t.payee.upper()) for t in extraction.transfers):
            update["statement_lines"] = [
                StatementLine(
                    date=t.date,
                    counterparty=t.payee if t.payer.upper() == mine else t.payer,
                    amount=-t.amount if t.payer.upper() == mine else t.amount,
                    currency=t.currency,
                )
                for t in extraction.transfers
            ]
            update["transfers"] = []
    out = extraction.model_copy(update=update) if update else extraction
    return _statement_currency(out)


def normalize_relations(extraction: DocumentExtraction) -> DocumentExtraction:
    """Registered agent ramené à intermediary si aucun n'est une adresse."""
    kinds = {e.name.upper(): e.kind for e in extraction.entities}
    changed = False
    relations = []
    for r in extraction.relations:
        ends = (kinds.get(r.source.upper()), kinds.get(r.target.upper()))
        if r.role == "registered_address" and all(k and k != "Adresse" for k in ends):
            r = r.model_copy(update={"role": "intermediary"})
            changed = True
        relations.append(r)
    return extraction.model_copy(update={"relations": relations}) if changed else extraction


_DATE_WORD_RE = re.compile(r"^\d{1,2}[/.]\d{1,2}[/.]\d{2,4}$")


def statement_problem(extraction: DocumentExtraction, witness: Any = None) -> str:
    """Raison pour laquelle un relevé lu est suspect (vide alors que la page est dense), ou ''."""
    if extraction.doc_type == "bank_statement" and extraction.balance_reconciled is False:
        return f"soldes non réconciliés : {extraction.balance_note}"
    if extraction.doc_type != "bank_statement" or witness is None:
        return ""
    words = getattr(witness, "words", [])
    if len(words) < MIN_WITNESS_WORDS:
        return ""
    if extraction.raw_output:
        seen = dated_rows(witness)
        if seen > len(extraction.statement_lines):
            return (
                f"tableau lu avec {len(extraction.statement_lines)} lignes alors que le témoin "
                f"OCR voit {seen} lignes datées : ligne(s) possiblement manquante(s)"
            )
    if extraction.resolved_transfers():
        return ""
    n_dates = sum(bool(_DATE_WORD_RE.match(getattr(w, "text", ""))) for w in words)
    if n_dates >= 3:
        return f"relevé sans aucun mouvement alors que le témoin OCR voit {n_dates} dates"
    return ""


def _call_engine_extract(engine, img: Image.Image, retry: bool = False) -> DocumentExtraction:
    try:
        if getattr(engine, "supports_retry_hint", False) or retry:
            return engine.extract(img, retry=retry)
        return engine.extract(img)
    except TypeError:
        try:
            if getattr(engine, "supports_retry_hint", False) or retry:
                return engine.extract(img, None, retry=retry)
            return engine.extract(img, None)
        except TypeError:
            return engine.extract(img)


def _find_cached(engine, cache: Path) -> tuple[DocumentExtraction | None, Path]:
    if hasattr(engine, "find_cached"):
        return engine.find_cached(cache)
    if cache.exists():
        return DocumentExtraction.model_validate_json(cache.read_text(encoding="utf-8")), cache
    return None, cache


def _target_cache(engine, cache: Path, ext: DocumentExtraction) -> Path:
    if hasattr(engine, "target_cache"):
        return engine.target_cache(cache, ext)
    return cache


def _engine_supports_retry(engine, extraction: DocumentExtraction) -> bool:
    if hasattr(engine, "should_retry"):
        return engine.should_retry(extraction)
    return getattr(engine, "supports_retry_hint", False) and getattr(engine, "name", "") not in (
        "rules",
        "table",
    )


def _read_page(
    engine,
    img: Image.Image,
    cache: Path,
    use_cache: bool,
    holder_hint: str = "",
) -> tuple[DocumentExtraction | None, bool, str, str]:
    """Lit une page : (extraction, depuis le scellé, erreur, motif « à relire »)."""
    if use_cache:
        cached_ext, _ = _find_cached(engine, cache)
        if cached_ext is not None:
            ext = normalize_relations(normalize_statement(cached_ext, holder_hint=holder_hint))
            return ext, True, "", statement_problem(ext)

    try:
        ext = _call_engine_extract(engine, img)
        ext = normalize_relations(normalize_statement(ext, holder_hint=holder_hint))
    except (RuntimeError, ValidationError) as exc:
        logger.warning("Page non extraite : %s", exc)
        return None, False, str(exc), ""

    problem = statement_problem(ext)
    if problem and _engine_supports_retry(engine, ext):
        try:
            retried = _call_engine_extract(engine, img, retry=True)
            ext = normalize_relations(normalize_statement(retried, holder_hint=holder_hint))
            problem = statement_problem(ext)
        except (RuntimeError, ValidationError) as exc:
            logger.warning("Relance impossible : %s", exc)

    if not problem:
        target_cache = _target_cache(engine, cache, ext)
        target_cache.parent.mkdir(parents=True, exist_ok=True)
        target_cache.write_text(ext.model_dump_json(indent=2), encoding="utf-8")

    return ext, False, "", problem


def _merge_pages(pages: list[DocumentExtraction]) -> DocumentExtraction:
    """Fusionne les pages d'une même pièce."""
    if len(pages) == 1:
        return pages[0]
    doc_type = next((p.doc_type for p in pages if p.doc_type != "other"), "other")
    entities: dict[tuple[str, str], ExtractedEntity] = {}
    relations: dict[tuple[str, str, str], ExtractedRelation] = {}
    for p in pages:
        for e in p.entities:
            entities.setdefault((e.name.upper(), e.kind), e)
        for r in p.relations:
            relations.setdefault((r.source.upper(), r.target.upper(), r.role), r)
    return DocumentExtraction(
        doc_type=doc_type,
        entities=list(entities.values()),
        relations=list(relations.values()),
        transfers=[t for p in pages for t in p.transfers],
        account_holder=next((p.account_holder for p in pages if p.account_holder), ""),
        statement_lines=[line for p in pages for line in p.statement_lines],
        account_iban=next((p.account_iban for p in pages if p.account_iban), ""),
        bank=next((p.bank for p in pages if p.bank), ""),
        period_start=min((p.period_start for p in pages if p.period_start), default=None),
        period_end=max((p.period_end for p in pages if p.period_end), default=None),
        header_currency=next((p.header_currency for p in pages if p.header_currency), ""),
        opening_balance=next(
            (p.opening_balance for p in pages if p.opening_balance is not None), None
        ),
        closing_balance=next(
            (p.closing_balance for p in reversed(pages) if p.closing_balance is not None), None
        ),
        balance_reconciled=False
        if any(p.balance_reconciled is False for p in pages)
        else (True if any(p.balance_reconciled for p in pages) else None),
        balance_note="; ".join(p.balance_note for p in pages if p.balance_note),
    )


def line_review_reason(transfers: list[GroundedTransfer]) -> str:
    """Motif « à relire » agrégé des virements signalés d'une pièce, '' si aucun."""
    flagged = [t for t in transfers if t.review_flags]
    if not flagged:
        return ""
    motifs = Counter(f for t in flagged for f in t.review_flags)
    detail = ", ".join(f"{m} ({n})" for m, n in motifs.most_common())
    return f"{len(flagged)} ligne(s) à relire : {detail}"


def extract_piece(
    path: Path, engine, use_cache: bool = True, cache_dir: Path | None = None
) -> PieceExtraction:
    sha = file_sha256(path)
    t0 = time.perf_counter()
    extractions: list[DocumentExtraction] = []
    page_of: list[int] = []
    errors: list[str] = []
    reasons: list[str] = []
    from_cache = True
    holder = ""
    n_pages = _n_pages(path)
    for page in range(n_pages):
        img = load_page_image(path, page=page)
        page_engine = engine
        ext, cached, error, problem = _read_page(
            page_engine,
            img,
            _cache_file(sha, page_engine.slug, cache_dir, page),
            use_cache,
            holder,
        )
        from_cache = from_cache and cached
        if ext is None:
            errors.append(f"page {page + 1} : {error}" if n_pages > 1 else error)
            continue
        holder = ext.account_holder or holder
        extractions.append(ext)
        page_of.append(page + 1)
        if problem:
            reasons.append(f"page {page + 1} : {problem}" if n_pages > 1 else problem)
    extraction = _merge_pages(extractions) if extractions else None
    error = "; ".join(errors) if extraction is None else ""
    if extraction is not None and errors:
        reasons.extend(f"non lue ({e})" for e in errors)

    grounded: list[GroundedEntity] = []
    transfers: list[GroundedTransfer] = []
    relations: list[PageRelation] = []
    if extraction:
        resolved: list[tuple[ExtractedTransfer, int]] = []
        seen_rel: set[tuple[str, str, str]] = set()
        for ext, page_no in zip(extractions, page_of, strict=True):
            if not ext.account_holder and extraction.account_holder:
                ext = ext.model_copy(update={"account_holder": extraction.account_holder})
            resolved += [(t, page_no) for t in ext.resolved_transfers()]
            for r in ext.relations:
                key = (r.source.upper(), r.target.upper(), r.role)
                if key not in seen_rel:
                    seen_rel.add(key)
                    relations.append(PageRelation(**r.model_dump(), page=page_no))
        entities = list(extraction.entities)
        known = {e.name.upper() for e in entities}
        for t, _ in resolved:
            for party in (t.payer, t.payee):
                if party.upper() not in known and len(party) >= 2:
                    kind = "Societe" if _COMPANY_RE.search(party) else "PersonnePhysique"
                    entities.append(ExtractedEntity(name=party, kind=kind))  # type: ignore[arg-type]
                    known.add(party.upper())
        for ent in entities:
            valid = bool(ent.name and len(ent.name.strip()) >= 2)
            grounded.append(
                GroundedEntity(
                    name=ent.name,
                    kind=ent.kind,
                    grounded=bool(valid),
                    grounding_score=1.0 if valid else 0.0,
                )
            )
        today = datetime.now(UTC).date()
        period = (extraction.period_start, extraction.period_end)
        account_holder = extraction.account_holder
        transfers = [
            GroundedTransfer(
                **t.model_dump(),
                amount_grounded=t.amount > 0,
                page=page_no,
                review_flags=(
                    line_date_flags(t.date, today, "", period)
                    + line_side_flags(t.payer, t.payee, account_holder, None)
                    + line_amount_flags(t.amount, "")
                ),
            )
            for t, page_no in resolved
        ]
        line_reason = line_review_reason(transfers)
        if line_reason:
            reasons.append(line_reason)

    return PieceExtraction(
        piece_id=path.stem,
        file=path.name,
        file_sha256=sha,
        engine=getattr(engine, "slug", getattr(engine, "name", "unknown")),
        from_cache=from_cache,
        seconds=round(time.perf_counter() - t0, 2),
        doc_type=extraction.doc_type if extraction else "other",
        entities=grounded,
        relations=relations,
        transfers=transfers,
        error=error,
        needs_review=bool(reasons),
        review_reason=" ; ".join(reasons),
        balance_reconciled=extraction.balance_reconciled if extraction else None,
        account_iban=extraction.account_iban if extraction else "",
        bank=extraction.bank if extraction else "",
        period_start=extraction.period_start if extraction else None,
        period_end=extraction.period_end if extraction else None,
    )


class RoutedEngine:
    """Moteur hybride : VLM principal pour actes et gouvernance, PaddleOCR-VL pour relevés tabulaires."""

    name = "routed"
    supports_retry_hint = True

    def __init__(self, deed_engine, statement_engine=None):
        self.deed_engine = deed_engine
        self.statement_engine = statement_engine

    @property
    def slug(self) -> str:
        parts = [self.deed_engine.slug] + (
            [self.statement_engine.slug] if self.statement_engine else []
        )
        return "routed-" + "+".join(parts)

    def engine_for(self, doc: Any = None):
        if self.statement_engine is not None and route_piece(doc) == "statement":
            return self.statement_engine
        return self.deed_engine

    def is_cached(self, sha: str, cache_dir: Path | None = None, page: int = 0) -> bool:
        if (
            self.statement_engine
            and _cache_file(sha, self.statement_engine.slug, cache_dir, page).exists()
        ):
            return True
        if _cache_file(sha, self.deed_engine.slug, cache_dir, page).exists():
            return True
        return _cache_file(sha, self.slug, cache_dir, page).exists()

    def find_cached(self, default_cache: Path) -> tuple[DocumentExtraction | None, Path]:
        stmt_cache = (
            default_cache.with_name(
                default_cache.name.replace(self.slug, self.statement_engine.slug)
            )
            if self.statement_engine
            else None
        )
        deed_cache = default_cache.with_name(
            default_cache.name.replace(self.slug, self.deed_engine.slug)
        )
        if stmt_cache and stmt_cache.exists():
            return (
                DocumentExtraction.model_validate_json(stmt_cache.read_text(encoding="utf-8")),
                stmt_cache,
            )
        if deed_cache.exists():
            ext = DocumentExtraction.model_validate_json(deed_cache.read_text(encoding="utf-8"))
            if ext.doc_type != "bank_statement" or self.statement_engine is None:
                return ext, deed_cache
            if stmt_cache and not stmt_cache.exists():
                return ext, deed_cache
        if default_cache.exists():
            return (
                DocumentExtraction.model_validate_json(default_cache.read_text(encoding="utf-8")),
                default_cache,
            )
        return None, default_cache

    def target_cache(self, default_cache: Path, extraction: DocumentExtraction) -> Path:
        if (
            self.statement_engine is not None
            and extraction.doc_type == "bank_statement"
            and getattr(extraction, "raw_output", "")
        ):
            return default_cache.with_name(
                default_cache.name.replace(self.slug, self.statement_engine.slug)
            )
        return default_cache.with_name(default_cache.name.replace(self.slug, self.deed_engine.slug))

    def should_retry(self, extraction: DocumentExtraction) -> bool:
        if getattr(extraction, "raw_output", ""):
            return False
        return bool(getattr(self.deed_engine, "supports_retry_hint", False))

    def extract(
        self, img: Image.Image, *args: Any, retry: bool = False, **kwargs: Any
    ) -> DocumentExtraction:
        if self.statement_engine is None:
            return _call_engine_extract(self.deed_engine, img, retry=retry)
        vlm_ext = _call_engine_extract(self.deed_engine, img, retry=retry)
        if vlm_ext.doc_type == "bank_statement":
            try:
                table_ext = _call_engine_extract(self.statement_engine, img, retry=retry)
                if table_ext.statement_lines:
                    update: dict[str, Any] = {}
                    if not table_ext.account_holder and vlm_ext.account_holder:
                        update["account_holder"] = vlm_ext.account_holder
                    if not table_ext.entities and vlm_ext.entities:
                        update["entities"] = vlm_ext.entities
                    if not table_ext.bank and vlm_ext.bank:
                        update["bank"] = vlm_ext.bank
                    if not table_ext.account_iban and vlm_ext.account_iban:
                        update["account_iban"] = vlm_ext.account_iban
                    if not table_ext.period_start and vlm_ext.period_start:
                        update["period_start"] = vlm_ext.period_start
                    if not table_ext.period_end and vlm_ext.period_end:
                        update["period_end"] = vlm_ext.period_end
                    return table_ext.model_copy(update=update) if update else table_ext
                logger.info("TableEngine n'a extrait aucune ligne, repli sur VLM.")
                return vlm_ext
            except Exception as exc:  # noqa: BLE001
                logger.warning("TableEngine failed, falling back to VLM: %s", exc)
                return vlm_ext
        return vlm_ext


def make_routed_engine() -> tuple[RoutedEngine, str]:
    """Moteur routé : VLM principal (actes) + PaddleOCR-VL / TableEngine (relevés)."""
    deed = VLMEngine(settings.vlm_model)
    table = TableEngine(settings.table_model)
    label = f"VLM {settings.vlm_model} (actes) + Table {settings.table_model} (relevés)"
    return RoutedEngine(deed, table), label


def is_live() -> bool:
    key = settings.get_effective_api_key()
    return bool(key and key != "EMPTY" and "your_" not in key)


def make_engine(
    kind: str = "auto", dossier: Path | str | None = None, cache_dir: Path | None = None
):
    """Moteur seul : une seule politique de choix, celle de select_engine."""
    return select_engine(kind, dossier, cache_dir)[0]


def select_engine(kind: str, dossier: Path | str | None = None, cache_dir: Path | None = None):
    """Moteur de lecture d'un dossier et libellé à afficher."""
    if kind == "rules":
        return RuleEngine(), "secours déterministe (hors ligne)"
    if kind == "routed":
        return make_routed_engine()
    vlm = VLMEngine()
    if kind == "vlm":
        return vlm, f"modèle de vision {vlm.model}"
    if dossier is not None and cached_coverage(dossier, vlm, cache_dir) == 1.0:
        return vlm, f"rejeu des lectures scellées de {vlm.model} (aucun appel réseau)"
    if dossier is not None and vlm.model == MODEL_T1:
        measured = VLMEngine(MODEL_GX10)
        if cached_coverage(dossier, measured, cache_dir) == 1.0:
            return measured, (
                f"rejeu des lectures scellées de {measured.model} pour {MODEL_T1} (aucun appel réseau)"
            )
    if is_live():
        return vlm, f"modèle de vision {vlm.model} : aucune lecture scellée complète"
    return RuleEngine(), (
        f"secours déterministe (hors ligne) : aucune lecture scellée pour {vlm.model} "
        "et aucun accès configuré"
    )


def extract_dossier(
    directory: Path | str,
    engine=None,
    workers: int | None = None,
    use_cache: bool = True,
    cache_dir: Path | None = None,
) -> list[PieceExtraction]:
    """Extrait toutes les pièces d'un dossier (ordre alphabétique, parallélisé)."""
    engine = engine or make_engine(dossier=directory, cache_dir=cache_dir)
    files = sorted(p for p in Path(directory).iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    with ThreadPoolExecutor(max_workers=workers or settings.extraction_workers) as pool:
        return list(pool.map(lambda p: extract_piece(p, engine, use_cache, cache_dir), files))
