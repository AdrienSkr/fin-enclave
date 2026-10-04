import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openai import OpenAI
from rapidocr_onnxruntime import RapidOCR

from fin_enclave.config import settings
from fin_enclave.documents.evaluation import evaluate_pieces, evaluate_scenario
from fin_enclave.documents.forge import scenario_path, truth_path
from fin_enclave.documents.models import (
    DocumentExtraction,
    GroundedEntity,
    GroundedTransfer,
    PieceExtraction,
)
from fin_enclave.documents.ocr import file_sha256, load_page_image
from fin_enclave.investigation import analyse

ocr_engine = RapidOCR()

client = OpenAI(
    base_url=settings.get_effective_base_url(),
    api_key=settings.get_effective_api_key(),
    timeout=60,
)

SYSTEM_PROMPT = """Tu es l'étage de structuration d'une station d'investigation financière.
On te donne la transcription textuelle OCR d'une pièce judiciaire saisie.
Extrais fidèlement ce qui est écrit :
- doc_type : nature de la pièce (bank_statement, wire_transfer, certificate_of_incorporation, register_of_directors, power_of_attorney, etc.)
- account_holder : nom du titulaire du compte (si relevé de compte bancaire).
- statement_lines : chaque mouvement du relevé : date (AAAA-MM-JJ), counterparty (nom propre sans libellé de virement), amount (négatif si débit/retrait/transfer to, positif si crédit/reçu/transfer from), currency.
- entities : chaque société, personne physique, intermédiaire, avec son nom EXACT.
- relations : liens juridiques écrits (source = détenteur/dirigeant/mandataire, target = société, role = director / shareholder / attorney / intermediary). Sur un relevé bancaire, relations est vide.
- transfers : ordres de virement ponctuels (payer, payee, amount, currency, date). Sur un relevé bancaire, transfers est vide (utiliser statement_lines).
Réponds uniquement par un objet JSON conforme au schéma DocumentExtraction."""


def extract_one_hybrid(path: Path, model: str = "qwen/qwen-2.5-7b-instruct") -> PieceExtraction:
    t0 = time.perf_counter()
    sha = file_sha256(path)
    img = load_page_image(path)

    # Étape 1 : RapidOCR (Neural OCR ONNX)
    ocr_res, _ = ocr_engine(path if path.suffix.lower() != ".pdf" else img)
    lines = [r[1] for r in (ocr_res or [])]
    ocr_text = "\n".join(lines)

    # Étape 2 : LLM Textuel Open-Weight (Qwen 2.5 7B)
    prompt = f"{SYSTEM_PROMPT}\n\nTranscription OCR de la pièce :\n{ocr_text}\n\nSchéma JSON :\n{json.dumps(DocumentExtraction.model_json_schema())}"
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    raw = resp.choices[0].message.content or ""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    data = json.loads(match.group(0) if match else raw)

    # Normalisation des rôles courants
    role_map = {
        "registered_agent": "intermediary",
        "registered agent": "intermediary",
        "agent": "intermediary",
        "registered_office": "registered_address",
        "address": "registered_address",
        "manager": "director",
        "sole_shareholder": "shareholder",
    }
    for rel in data.get("relations", []):
        r = rel.get("role", "").lower()
        if r in role_map:
            rel["role"] = role_map[r]
        elif r not in {
            "director",
            "shareholder",
            "beneficial_owner",
            "secretary",
            "attorney",
            "intermediary",
            "registered_address",
            "other",
        }:
            rel["role"] = "other"

    try:
        ext = DocumentExtraction.model_validate(data)
        resolved = ext.resolved_transfers()
        entities = [
            GroundedEntity(name=e.name, kind=e.kind, grounded=True, grounding_score=1.0)
            for e in ext.entities
        ]
        transfers = [GroundedTransfer(**t.model_dump(), amount_grounded=True) for t in resolved]
        doc_type = ext.doc_type
        relations = ext.relations
        error = ""
    except Exception as exc:  # noqa: BLE001
        resolved, entities, transfers, relations = [], [], [], []
        doc_type = "other"
        error = str(exc)

    return PieceExtraction(
        piece_id=path.stem,
        file=path.name,
        file_sha256=sha,
        engine=f"hybrid-rapidocr-{model}",
        from_cache=False,
        seconds=round(time.perf_counter() - t0, 3),
        doc_type=doc_type,
        entities=entities,
        relations=relations,
        transfers=transfers,
        error=error,
    )


def main():
    dossier = Path("data/demo/pieces")
    model = "qwen/qwen-2.5-7b-instruct"
    print(
        f"=== TEST ARCHITECTURE HYBRIDE (RapidOCR + {model}) SUR DOSSIER '{dossier.name}' (44 pièces) ===",
        flush=True,
    )
    files = sorted(
        p for p in dossier.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf"}
    )

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as pool:
        pieces = list(pool.map(lambda p: extract_one_hybrid(p, model), files))
    t1 = time.time()
    print(f"Extraction hybride terminée en {t1 - t0:.2f} s pour {len(pieces)} pièces!", flush=True)

    truth = json.loads(truth_path(dossier).read_text("utf-8"))
    scenario = json.loads(scenario_path(dossier).read_text("utf-8"))

    ev = evaluate_pieces(pieces, truth)["all"]
    print("\n--- MESURE LECTURE DES PIÈCES ---", flush=True)
    print(
        f"  Entités : Précision = {ev['entities']['precision']:.2f}, Rappel = {ev['entities']['recall']:.2f}, F1 = {ev['entities']['f1']:.2f}"
    )
    print(
        f"  Relations : Précision = {ev['relations']['precision']:.2f}, Rappel = {ev['relations']['recall']:.2f}, F1 = {ev['relations']['f1']:.2f}"
    )
    print(
        f"  Virements : Précision = {ev['transfers']['precision']:.2f}, Rappel = {ev['transfers']['recall']:.2f}, F1 = {ev['transfers']['f1']:.2f}"
    )

    _G, _resolver, _ledger, _detection, findings = analyse(pieces)
    sc = evaluate_scenario(findings, scenario)
    print("\n--- CONSTATS DU SCÉNARIO DÉTECTÉS ---", flush=True)
    print(f"  Circuit fermé : {'OUI' if sc['cycle_found'] else 'NON'}")
    print(
        f"  Fractionnement : {'OUI' if sc['smurfing_found'] else 'NON'} ({sc['mules_found']}/{sc['mules_expected']} relais)"
    )
    print(f"  Bénéficiaire caché : {'OUI' if sc['hidden_beneficiary_found'] else 'NON'}")


if __name__ == "__main__":
    main()
