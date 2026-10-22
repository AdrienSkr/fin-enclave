"""Tests pour le banc d'essai et la télémétrie continue GX10 (scripts/bench_gx10.py)."""

import json
import sys
from pathlib import Path

# Permet d'importer scripts/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.bench_gx10 import (
    GpuSampler,
    run_benchmark,
)


def test_gpu_sampler_lifecycle_and_aggregation(monkeypatch):
    """Vérifie le cycle de vie start/stop et l'agrégation statistique déterministe de GpuSampler."""
    fake_telemetry = {
        "available": True,
        "memory_used_mb": 60000.0,
        "memory_total_mb": 128000.0,
        "power_w": 185.0,
        "temp_c": 58.0,
    }
    monkeypatch.setattr("scripts.bench_gx10.get_gpu_telemetry", lambda: fake_telemetry)

    sampler = GpuSampler(interval_s=1.0)
    sampler.start()
    stats = sampler.stop()

    assert stats["available"] is True
    assert stats["samples_count"] >= 1
    assert stats["peak_vram_mb"] == 60000.0
    assert stats["avg_power_w"] == 185.0
    assert stats["peak_temp_c"] == 58.0


def test_run_benchmark_dryrun(tmp_path):
    """Vérifie l'enregistrement et les clés attendues d'un run unitaire isolé dans tmp_path."""
    res = run_benchmark(
        dossier=Path("data/demo/pieces"),
        profile="test-pytest",
        engine_kind="auto",
        sampling_interval=0.1,
        out_dir=tmp_path,
    )
    assert res["profile"] == "test-pytest"
    assert res["n_pieces"] == 50
    assert "hardware" in res
    assert "peak_vram_mb" in res
    assert "avg_power_w" in res
    assert "peak_temp_c" in res

    # Vérification du fichier JSON isolé
    out_file = tmp_path / "bench_test-pytest_pieces.json"
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["profile"] == "test-pytest"
    assert "peak_vram_mb" in data
    assert "avg_power_w" in data
    assert "peak_temp_c" in data
