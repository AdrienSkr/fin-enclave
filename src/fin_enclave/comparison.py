"""
Même dossier, trois stations : pourquoi la lecture des pièces exige un grand modèle.

- CPU sans LLM : règles + Tesseract, ce que fait un poste sans GPU ;
- petit modèle (8B) : ce qui tient dans la VRAM d'une RTX grand public ;
- grand modèle (235B) : ce qui ne tient que dans les 128 Go de mémoire unifiée du GX10.

Le petit et le grand modèle sont de la même famille (Qwen3-VL) : seule la taille change. Chaque
modèle lit les pièces (vision) puis rédige les notes d'analyse ; les détecteurs, la mise en
relation et le contrôle de fidélité des notes sont identiques pour les trois.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from .config import settings
from .documents.evaluation import evaluate_pieces, evaluate_scenario, evaluate_typologies
from .documents.extractor import RuleEngine, VLMEngine, cached_coverage
from .documents.forge import scenario_path, truth_path
from .investigation import investigate


@dataclass(frozen=True)
class Tier:
    label: str
    station: str
    memory: str
    model: str | None


TIERS = (
    Tier("CPU, sans LLM", "tout poste", "—", None),
    Tier(
        "Petit modèle 8B",
        "RTX 4090 (24 Go)",
        "≈ 17 Go (BF16)",
        "qwen/qwen3-vl-8b-instruct",
    ),
    Tier(
        "Grand modèle 235B",
        "GX10 (128 Go unifiés)",
        "≈ 120 Go (4 bits)",
        "qwen/qwen3-vl-235b-a22b-instruct",
    ),
)


def _live() -> bool:
    key = settings.get_effective_api_key()
    return settings.llm_backend == "local_gx10" or bool(
        key and key != "EMPTY" and "your_" not in key
    )


def run_tier(tier: Tier, dossier: Path, cache_dir: Path) -> dict:
    engine = VLMEngine(tier.model) if tier.model else RuleEngine()
    row = {"tier": tier.label, "station": tier.station, "memory": tier.memory, "model": tier.model}
    if tier.model and not _live() and cached_coverage(dossier, engine, cache_dir) < 1.0:
        return {**row, "measured": False}
    inv = investigate(
        dossier, engine, cache_dir=cache_dir, llm_notes=bool(tier.model), llm_model=tier.model
    )
    truth = json.loads(truth_path(dossier).read_text(encoding="utf-8"))
    scenario = json.loads(scenario_path(dossier).read_text(encoding="utf-8"))
    pieces = evaluate_pieces(inv.pieces, truth)["all"]
    sc = evaluate_scenario(inv.findings, scenario)
    authors = inv.findings.get("report_authors", [])
    res = {
        **row,
        "measured": True,
        "entities": pieces["entities"],
        "relations": pieces["relations"],
        "transfers": pieces["transfers"],
        "hallucinated_entities": len(inv.findings["vigilance"]["rejected_entities"]),
        "failed_pieces": sum(bool(p.error) for p in inv.pieces),
        "findings": {
            "circuit": sc["cycle_found"],
            "fractionnement": sc["smurfing_found"],
            "beneficiaire_cache": sc["hidden_beneficiary_found"],
        },
        "notes_llm": {
            "total": len(authors),
            "accepted": sum(a.startswith("llm:") for a in authors),
        }
        if tier.model
        else None,
    }
    if "ibm_patterns" in scenario:
        res["typologies"] = evaluate_typologies(inv.graph, scenario)
    return res


def compare(dossier: Path, cache_dir: Path) -> list[dict]:
    return [run_tier(t, dossier, cache_dir) for t in TIERS]
