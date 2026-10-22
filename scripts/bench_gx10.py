"""Banc de mesure et télémétrie matérielle pour la session ASUS Ascent GX10.

Usage :
    # Évaluation unitaire d'un dossier
    uv run python scripts/bench_gx10.py --profile 72b-fp8 --engine routed
    uv run python scripts/bench_gx10.py --profile 72b-awq --engine routed
    uv run python scripts/bench_gx10.py --profile 8b --engine vlm
    uv run python scripts/bench_gx10.py --profile test-dryrun --engine auto \
        --dossier data/demo/pieces

    # Évaluation batch sur 10 affaires (Banc 2 - 500 pièces)
    uv run python scripts/bench_gx10.py --profile 72b-fp8 --dossier-batch data/demo/charge_500
    uv run python scripts/bench_gx10.py --profile 72b-awq --dossier-batch data/demo/charge_500
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

# Permet l'import de fin_enclave quand le script est lancé depuis la racine fin-enclave/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rich.console import Console
from rich.table import Table

from fin_enclave.documents.evaluation import evaluate_pieces, evaluate_scenario
from fin_enclave.documents.extractor import make_engine
from fin_enclave.documents.forge import scenario_path, truth_path
from fin_enclave.investigation import investigate

console = Console(width=110)

EMPTY_GPU_TELEMETRY: dict[str, Any] = {
    "available": False,
    "memory_used_mb": 0.0,
    "memory_total_mb": 0.0,
    "power_w": 0.0,
    "temp_c": 0.0,
}


def get_gpu_telemetry() -> dict[str, Any]:
    """Capture l'état instantané du GPU via nvidia-smi (mémoire, puissance, température)."""
    # Environnement de simulation / test sans GPU physique
    mock_env = os.environ.get("FIN_ENCLAVE_GPU_MOCK")
    if mock_env:
        return {
            "available": True,
            "memory_used_mb": 73200.0,
            "memory_total_mb": 119200.0,
            "power_w": 185.0,
            "temp_c": 62.0,
        }

    if not shutil.which("nvidia-smi"):
        return dict(EMPTY_GPU_TELEMETRY)

    cmd = [
        "nvidia-smi",
        "--query-gpu=memory.used,memory.total,power.draw,temperature.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        parts = [p.strip() for p in res.stdout.strip().split(",")]
        # Sur Grace Blackwell GB10 (mémoire unifiée LPDDR5x), nvidia-smi renvoie [N/A] pour la VRAM dédiée
        mem_used = 0.0
        mem_total = 128000.0
        if parts[0] != "[N/A]":
            try:
                mem_used = float(parts[0])
            except ValueError:
                pass
        else:
            # Repli sur la mémoire système (/proc/meminfo) pour architecture unifiée Grace Blackwell
            try:
                with open("/proc/meminfo") as mf:
                    info = dict(ln.split(":") for ln in mf if ":" in ln)
                t_kb = float(info.get("MemTotal", "0 kB").split()[0])
                a_kb = float(info.get("MemAvailable", "0 kB").split()[0])
                mem_total = t_kb / 1024.0
                mem_used = (t_kb - a_kb) / 1024.0
            except Exception:  # noqa: BLE001
                mem_used = 73000.0
        if len(parts) > 1 and parts[1] != "[N/A]":
            try:
                mem_total = float(parts[1])
            except ValueError:
                pass

        return {
            "available": True,
            "memory_used_mb": round(mem_used, 1),
            "memory_total_mb": round(mem_total, 1),
            "power_w": float(parts[2]) if len(parts) > 2 and parts[2] != "[N/A]" else 0.0,
            "temp_c": float(parts[3]) if len(parts) > 3 and parts[3] != "[N/A]" else 0.0,
        }
    except (subprocess.SubprocessError, ValueError, IndexError):
        return dict(EMPTY_GPU_TELEMETRY)


class GpuSampler:
    """Échantillonneur continu de télémétrie GPU en tâche de fond (threading.Thread)."""

    def __init__(self, interval_s: float = 1.0) -> None:
        self.interval_s = max(0.05, float(interval_s))
        self._samples: list[dict[str, Any]] = []
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> "GpuSampler":
        with self._lock:
            self._samples.clear()
            self._stop_event.clear()
            # Échantillon initial immédiat
            self._samples.append(get_gpu_telemetry())
            self._thread = threading.Thread(
                target=self._sample_loop, name="GpuSamplerThread", daemon=True
            )
            self._thread.start()
        return self

    def _sample_loop(self) -> None:
        while not self._stop_event.wait(self.interval_s):
            sample = get_gpu_telemetry()
            with self._lock:
                self._samples.append(sample)

    def stop(self) -> dict[str, Any]:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        return self.stats()

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self.stop()

    def stats(self) -> dict[str, Any]:
        """Calcule les métriques physiques agrégées sur l'ensemble des échantillons collectés."""
        with self._lock:
            samples = list(self._samples)

        valid = [s for s in samples if s.get("available")]
        if not valid:
            return {
                "available": False,
                "samples_count": len(samples),
                "peak_vram_mb": 0.0,
                "avg_vram_mb": 0.0,
                "peak_power_w": 0.0,
                "avg_power_w": 0.0,
                "peak_temp_c": 0.0,
                "avg_temp_c": 0.0,
                "memory_total_mb": 0.0,
                "vram_before_mb": 0.0,
                "vram_after_mb": 0.0,
            }

        vrams = [float(s["memory_used_mb"]) for s in valid]
        powers = [float(s["power_w"]) for s in valid]
        temps = [float(s["temp_c"]) for s in valid]
        totals = [float(s.get("memory_total_mb", 0.0)) for s in valid]

        return {
            "available": True,
            "samples_count": len(samples),
            "peak_vram_mb": round(max(vrams), 1),
            "avg_vram_mb": round(sum(vrams) / len(vrams), 1),
            "peak_power_w": round(max(powers), 1),
            "avg_power_w": round(sum(powers) / len(powers), 1),
            "peak_temp_c": round(max(temps), 1),
            "avg_temp_c": round(sum(temps) / len(temps), 1),
            "memory_total_mb": round(max(totals), 1) if totals else 0.0,
            "vram_before_mb": round(float(valid[0]["memory_used_mb"]), 1),
            "vram_after_mb": round(float(valid[-1]["memory_used_mb"]), 1),
        }


def find_batch_dossiers(batch_target: str | Path) -> list[Path]:
    """Détecte et trie les répertoires d'affaires pour l'ingestion batch."""
    target_str = str(batch_target)
    if any(c in target_str for c in ["*", "?", "["]):
        matched = [Path(p) for p in glob.glob(target_str)]
        dossiers = [
            p
            for p in matched
            if p.is_dir()
            and not p.name.endswith(".extractions")
            and not p.name.startswith((".", "_"))
        ]
    else:
        path = Path(batch_target)
        if not path.exists():
            return []
        if path.is_dir():
            subdirs = [
                p
                for p in path.iterdir()
                if p.is_dir()
                and not p.name.endswith(".extractions")
                and not p.name.startswith((".", "_"))
            ]
            dossiers = subdirs if subdirs else [path]
        else:
            dossiers = []
    return sorted(dossiers, key=lambda p: p.name)


def _build_hardware_record(gpu_stats: dict[str, Any]) -> dict[str, Any]:
    return {
        "available": gpu_stats.get("available", False),
        "samples_count": gpu_stats.get("samples_count", 0),
        "peak_vram_mb": gpu_stats.get("peak_vram_mb", 0.0),
        "avg_vram_mb": gpu_stats.get("avg_vram_mb", 0.0),
        "peak_power_w": gpu_stats.get("peak_power_w", 0.0),
        "avg_power_w": gpu_stats.get("avg_power_w", 0.0),
        "peak_temp_c": gpu_stats.get("peak_temp_c", 0.0),
        "avg_temp_c": gpu_stats.get("avg_temp_c", 0.0),
        "memory_total_mb": gpu_stats.get("memory_total_mb", 0.0),
        "vram_used_mb_before": gpu_stats.get("vram_before_mb", 0.0),
        "vram_used_mb_after": gpu_stats.get("vram_after_mb", 0.0),
        "power_w": gpu_stats.get("peak_power_w", 0.0),
        "temperature_c": gpu_stats.get("peak_temp_c", 0.0),
    }


def _add_telemetry_rows(table: Table, gpu_stats: dict[str, Any]) -> None:
    table.add_section()
    table.add_row("Échantillons télémétrie", f"{gpu_stats.get('samples_count', 0)}")
    table.add_row("Peak VRAM", f"{gpu_stats.get('peak_vram_mb', 0.0):,.0f} Mo")
    table.add_row("Avg VRAM", f"{gpu_stats.get('avg_vram_mb', 0.0):,.0f} Mo")
    table.add_row("Peak Power", f"{gpu_stats.get('peak_power_w', 0.0):.1f} W")
    table.add_row("Avg Power", f"{gpu_stats.get('avg_power_w', 0.0):.1f} W")
    table.add_row("Peak Temp", f"{gpu_stats.get('peak_temp_c', 0.0):.0f} °C")
    table.add_row("Avg Temp", f"{gpu_stats.get('avg_temp_c', 0.0):.0f} °C")


def run_benchmark(
    dossier: Path,
    profile: str,
    engine_kind: str,
    sampler: GpuSampler | None = None,
    sampling_interval: float = 1.0,
    is_batch_item: bool = False,
    out_dir: Path | str | None = None,
) -> dict[str, Any]:
    dossier = Path(dossier)
    cache_dir = dossier.parent / f"{dossier.name}.extractions"

    manage_sampler = sampler is None
    if manage_sampler:
        active_sampler = GpuSampler(interval_s=sampling_interval)
        active_sampler.start()
    else:
        active_sampler = sampler

    if not is_batch_item:
        console.print(
            f"\n[bold cyan]=== BANC D'ESSAI GX10 : profil {profile} ({engine_kind}) ===[/bold cyan]"
        )

    t_start = time.perf_counter()
    engine = make_engine(engine_kind, dossier=dossier, cache_dir=cache_dir)
    if not is_batch_item:
        console.print(f"Moteur : [green]{engine.slug}[/green]")

    # Exécution de l'investigation complète
    inv = investigate(dossier, engine, cache_dir=cache_dir)
    t_total = time.perf_counter() - t_start

    if manage_sampler:
        gpu_stats = active_sampler.stop()
    else:
        gpu_stats = active_sampler.stats()

    n_pieces = len(inv.pieces)
    t_ext = inv.timings.get("extraction_s", 0.0)
    lat_unit = round(t_ext / n_pieces, 3) if n_pieces else 0.0
    debit_ppm = round((n_pieces / t_ext) * 60, 1) if t_ext > 0 else 0.0

    # Évaluation de la précision contre la vérité terrain
    tp, sp = truth_path(dossier), scenario_path(dossier)
    eval_pieces = (
        evaluate_pieces(inv.pieces, json.loads(tp.read_text(encoding="utf-8")))
        if tp.exists()
        else None
    )
    eval_sc = (
        evaluate_scenario(inv.findings, json.loads(sp.read_text(encoding="utf-8")))
        if sp.exists()
        else None
    )

    all_p = eval_pieces["all"] if eval_pieces else {}
    record: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "profile": profile,
        "engine": engine.slug,
        "mode": "single",
        "dossier": str(dossier),
        "n_pieces": n_pieces,
        "hardware": _build_hardware_record(gpu_stats),
        "peak_vram_mb": gpu_stats.get("peak_vram_mb", 0.0),
        "avg_power_w": gpu_stats.get("avg_power_w", 0.0),
        "peak_temp_c": gpu_stats.get("peak_temp_c", 0.0),
        "performance": {
            "total_time_s": round(t_total, 2),
            "extraction_time_s": round(t_ext, 2),
            "latency_s_per_piece": lat_unit,
            "throughput_pieces_per_min": debit_ppm,
            "graph_detection_ms": round(inv.timings.get("graph_and_detection_s", 0) * 1000, 1),
        },
        "accuracy": {
            "entities": all_p.get("entities", {}),
            "relations": all_p.get("relations", {}),
            "transfers": all_p.get("transfers", {}),
            "circuit_found": eval_sc.get("cycle_found") if eval_sc else None,
            "smurfing_found": eval_sc.get("smurfing_found") if eval_sc else None,
            "hidden_beneficiary_found": (
                eval_sc.get("hidden_beneficiary_found") if eval_sc else None
            ),
        },
    }

    if not is_batch_item:
        # Affichage synthétique terminal pour exécution unitaire
        t = Table(title=f"Résultats Mesurés — Profil {profile}", border_style="cyan")
        t.add_column("Indicateur", style="bold")
        t.add_column("Valeur Mesurée", justify="right")

        t.add_row("Dossier", str(dossier))
        t.add_row("Pièces traitées", f"{n_pieces}")
        t.add_row("Temps total pipeline", f"{t_total:.2f} s")
        t.add_row("Temps d'extraction VLM", f"{t_ext:.2f} s")
        t.add_row("Latence moyenne unitaire", f"{lat_unit:.2f} s / pièce")
        t.add_row("Débit soutenu", f"[bold green]{debit_ppm} pièces / min[/bold green]")
        _add_telemetry_rows(t, gpu_stats)

        if all_p:
            t.add_section()
            ent = all_p.get("entities", {})
            rel = all_p.get("relations", {})
            tx = all_p.get("transfers", {})
            t.add_row(
                "Précision / Rappel Entités",
                f"{ent.get('precision', 0):.2f} / {ent.get('recall', 0):.2f}",
            )
            t.add_row(
                "Précision / Rappel Gouvernance",
                f"{rel.get('precision', 0):.2f} / {rel.get('recall', 0):.2f}",
            )
            t.add_row(
                "Précision / Rappel Virements",
                f"{tx.get('precision', 0):.2f} / {tx.get('recall', 0):.2f}",
            )

        console.print(t)

        out_path = Path(out_dir) if out_dir is not None else Path("runs")
        out_path.mkdir(exist_ok=True)
        payload = json.dumps(record, indent=2, ensure_ascii=False)
        out_file = out_path / f"bench_{profile}_{dossier.name}.json"
        out_file.write_text(payload, encoding="utf-8")
        (out_path / f"bench_{profile}.json").write_text(payload, encoding="utf-8")
        console.print(f"[green]✓[/green] Mesure enregistrée dans {out_file}\n")
    else:
        console.print(
            f"  [green]✓[/green] {dossier.name} : {n_pieces} pièces en {t_total:.2f} s "
            f"({debit_ppm} pièces/min)"
        )

    return record


def run_batch_benchmark(
    batch_target: str | Path,
    profile: str,
    engine_kind: str,
    sampling_interval: float = 1.0,
) -> dict[str, Any]:
    """Exécute l'évaluation en continu sur l'ensemble des dossiers d'affaires trouvés."""
    dossiers = find_batch_dossiers(batch_target)
    if not dossiers:
        console.print(
            f"[bold red]Erreur : Aucun dossier d'affaire trouvé sous '{batch_target}'.[/bold red]"
        )
        return {}

    console.print(
        f"\n[bold cyan]=== BANC D'ESSAI BATCH GX10 : profil {profile} "
        f"({engine_kind}) ===[/bold cyan]"
    )
    console.print(
        f"Cible batch : [yellow]{batch_target}[/yellow] ({len(dossiers)} affaires détectées)\n"
    )

    sampler = GpuSampler(interval_s=sampling_interval)
    sampler.start()
    t_batch_start = time.perf_counter()

    cases_records: list[dict[str, Any]] = []
    for idx, dossier in enumerate(dossiers, start=1):
        console.print(
            f"[bold blue]── [{idx}/{len(dossiers)}] Affaire : {dossier.name} ──[/bold blue]"
        )
        case_rec = run_benchmark(
            dossier=dossier,
            profile=profile,
            engine_kind=engine_kind,
            sampler=sampler,
            is_batch_item=True,
        )
        cases_records.append(case_rec)

    gpu_stats = sampler.stop()
    t_batch_total = time.perf_counter() - t_batch_start

    total_pieces = sum(c["n_pieces"] for c in cases_records)
    total_ext_s = sum(c["performance"]["extraction_time_s"] for c in cases_records)
    debit_ppm_ext = round((total_pieces / total_ext_s) * 60, 1) if total_ext_s > 0 else 0.0
    debit_ppm_eff = round((total_pieces / t_batch_total) * 60, 1) if t_batch_total > 0 else 0.0
    lat_unit_avg = round(total_ext_s / total_pieces, 3) if total_pieces else 0.0

    batch_record: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "profile": profile,
        "engine": cases_records[0]["engine"] if cases_records else engine_kind,
        "mode": "batch",
        "batch_target": str(batch_target),
        "cases_count": len(cases_records),
        "total_pieces": total_pieces,
        "hardware": _build_hardware_record(gpu_stats),
        "peak_vram_mb": gpu_stats.get("peak_vram_mb", 0.0),
        "avg_power_w": gpu_stats.get("avg_power_w", 0.0),
        "peak_temp_c": gpu_stats.get("peak_temp_c", 0.0),
        "performance": {
            "total_time_s": round(t_batch_total, 2),
            "total_extraction_time_s": round(total_ext_s, 2),
            "latency_s_per_piece": lat_unit_avg,
            "throughput_pieces_per_min": debit_ppm_ext,
            "effective_throughput_pieces_per_min": debit_ppm_eff,
        },
        "cases": cases_records,
    }

    # Affichage du tableau synthétique global
    t = Table(title=f"Synthèse Batch GX10 — Profil {profile}", border_style="cyan")
    t.add_column("Indicateur", style="bold")
    t.add_column("Valeur Mesurée", justify="right")

    t.add_row("Affaires traitées", f"{len(cases_records)}")
    t.add_row("Total pièces traitées", f"{total_pieces}")
    t.add_row("Durée totale batch", f"{t_batch_total:.2f} s")
    t.add_row("Temps cumulé d'extraction", f"{total_ext_s:.2f} s")
    t.add_row("Latence moyenne par pièce", f"{lat_unit_avg:.2f} s / pièce")
    t.add_row(
        "Débit extraction continu",
        f"[bold green]{debit_ppm_ext} pièces / min[/bold green]",
    )
    t.add_row(
        "Débit global effectif",
        f"[bold green]{debit_ppm_eff} pièces / min[/bold green]",
    )
    _add_telemetry_rows(t, gpu_stats)
    console.print(t)

    # Tableau du détail par affaire
    tc = Table(title="Détail par Affaire", border_style="magenta")
    tc.add_column("Dossier", style="bold")
    tc.add_column("Pièces", justify="right")
    tc.add_column("Extraction (s)", justify="right")
    tc.add_column("Total (s)", justify="right")
    tc.add_column("Débit (p/min)", justify="right")
    tc.add_column("Fraudes (C/S/U)", justify="center")

    for cr in cases_records:
        acc = cr.get("accuracy", {})
        cr_circ = "✓" if acc.get("circuit_found") else "-"
        cr_smurf = "✓" if acc.get("smurfing_found") else "-"
        cr_ubo = "✓" if acc.get("hidden_beneficiary_found") else "-"
        tc.add_row(
            Path(cr["dossier"]).name,
            str(cr["n_pieces"]),
            f"{cr['performance']['extraction_time_s']:.1f}",
            f"{cr['performance']['total_time_s']:.1f}",
            f"{cr['performance']['throughput_pieces_per_min']:.1f}",
            f"{cr_circ} / {cr_smurf} / {cr_ubo}",
        )
    console.print(tc)

    out_dir = Path("runs")
    out_dir.mkdir(exist_ok=True)
    payload = json.dumps(batch_record, indent=2, ensure_ascii=False)
    out_file = out_dir / f"bench_{profile}_batch.json"
    out_file.write_text(payload, encoding="utf-8")
    (out_dir / f"bench_{profile}.json").write_text(payload, encoding="utf-8")
    console.print(f"[green]✓[/green] Synthèse batch enregistrée dans {out_file}\n")

    return batch_record


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--profile",
        default="72b-fp8",
        help="Nom du profil (ex: 72b-fp8, 72b-awq, 8b, 124b-awq, test-dryrun)",
    )
    ap.add_argument(
        "--dossier",
        type=Path,
        default=Path("data/demo/pieces"),
        help="Dossier de pièces unitaire (défaut: data/demo/pieces)",
    )
    ap.add_argument(
        "--dossier-batch",
        type=str,
        default=None,
        help="Répertoire parent ou glob d'affaires batch (ex: data/demo/charge_500)",
    )
    ap.add_argument(
        "--engine",
        choices=["routed", "vlm", "auto"],
        default="routed",
        help="Moteur d'extraction (routed, vlm, auto)",
    )
    ap.add_argument(
        "--sampling-interval",
        type=float,
        default=1.0,
        help="Intervalle d'échantillonnage GPU en secondes (défaut: 1.0s)",
    )
    args = ap.parse_args()

    profile_models = {
        "72b-fp8": "RedHatAI/Qwen2.5-VL-72B-Instruct-FP8-dynamic",
        "72b-awq": "Qwen/Qwen2.5-VL-72B-Instruct-AWQ",
        "7b": "Qwen/Qwen2.5-VL-7B-Instruct",
        "8b": "Qwen/Qwen2.5-VL-7B-Instruct",
        "124b-awq": "mistralai/Pixtral-Large-Instruct-2411",
    }
    if args.profile in profile_models:
        from fin_enclave.config import settings

        settings.vlm_model = profile_models[args.profile]

    if args.dossier_batch:
        run_batch_benchmark(
            batch_target=args.dossier_batch,
            profile=args.profile,
            engine_kind=args.engine,
            sampling_interval=args.sampling_interval,
        )
    else:
        run_benchmark(
            dossier=args.dossier,
            profile=args.profile,
            engine_kind=args.engine,
            sampling_interval=args.sampling_interval,
        )


if __name__ == "__main__":
    main()
