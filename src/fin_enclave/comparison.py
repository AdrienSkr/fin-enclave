"""
Même dossier, quatre colonnes : pourquoi la lecture des pièces exige un grand modèle.

- CPU sans LLM : règles + Tesseract, ce que fait un poste sans GPU ;
- petit modèle (Qwen3-VL 8B) : ce qui tient dans la VRAM d'une RTX grand public ;
- GX10 (Qwen2.5-VL 72B) : ce qui tient dans les 128 Go de mémoire
  unifiée et que la RTX ne peut pas charger ;
- référence 235B (Qwen3-VL), hors GX10 : ne tient pas en mémoire, gardée comme borne haute.

Chaque modèle lit les pièces (vision) puis rédige les notes d'analyse ; les détecteurs, la mise
en relation et le contrôle de fidélité des notes sont identiques pour toutes les colonnes.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from .config import MODEL_GX10, MODEL_LARGE, MODEL_SMALL
from .documents.evaluation import evaluate_pieces, evaluate_scenario, evaluate_typologies
from .documents.extractor import RuleEngine, VLMEngine, cached_coverage, is_live
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
    Tier("Petit modèle 8B", "RTX 5070 / 5080 (16 Go)", "≈ 8 Go (FP8)", MODEL_SMALL),
    Tier("GX10 : 72B", "GX10 (128 Go unifiés)", "≈ 71 Go (FP8)", MODEL_GX10),
    Tier(
        "Référence 235B, hors GX10",
        "hors GX10 (ne tient pas en mémoire)",
        "≈ 120 Go (4 bits)",
        MODEL_LARGE,
    ),
)


def scenario_findings(sc: dict, scenario: dict) -> dict[str, bool | None]:
    """Constats retrouvés ; `None` (sans objet) quand le scénario caché ne contient pas ce constat."""
    return {
        "circuit": sc["cycle_found"] if "cycle" in scenario else None,
        "fractionnement": sc["smurfing_found"] if scenario.get("smurfing") else None,
        "beneficiaire_cache": sc["hidden_beneficiary_found"] if "beneficiary" in scenario else None,
    }


def run_tier(tier: Tier, dossier: Path, cache_dir: Path) -> dict:
    engine = VLMEngine(tier.model) if tier.model else RuleEngine()
    row = {"tier": tier.label, "station": tier.station, "memory": tier.memory, "model": tier.model}
    if tier.model and not is_live() and cached_coverage(dossier, engine, cache_dir) < 1.0:
        return {**row, "measured": False}
    inv = investigate(dossier, engine, cache_dir=cache_dir)
    truth = json.loads(truth_path(dossier).read_text(encoding="utf-8"))
    scenario = json.loads(scenario_path(dossier).read_text(encoding="utf-8"))
    pieces = evaluate_pieces(inv.pieces, truth)["all"]
    sc = evaluate_scenario(inv.findings, scenario)
    res = {
        **row,
        "measured": True,
        "entities": pieces["entities"],
        "relations": pieces["relations"],
        "transfers": pieces["transfers"],
        "transfers_currency": pieces["transfers_currency"],
        "failed_pieces": sum(bool(p.error) for p in inv.pieces),
        "findings": scenario_findings(sc, scenario),
    }
    if "ibm_patterns" in scenario:
        res["typologies"] = evaluate_typologies(inv.graph, scenario)
    return res


def compare(dossier: Path, cache_dir: Path) -> list[dict]:
    return [run_tier(t, dossier, cache_dir) for t in TIERS]
