#!/usr/bin/env python3
"""
Affiche les chiffres exacts à copier-coller dans le README, le rapport et l'email
dès que les runs de 6h00 sont terminés.
"""
import json
from pathlib import Path

RUNS_DIR = Path("runs")

def load(filename):
    p = RUNS_DIR / filename
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None

fp8_p = load("bench_72b-fp8_pieces.json")
awq_p = load("bench_72b-awq_pieces.json")
fp8_b = load("bench_72b-fp8_batch.json")
awq_b = load("bench_72b-awq_batch.json")
b7_p = load("bench_7b_pieces.json")

print("\n" + "="*70)
print("  RÉCAPITULATIF CHIRURGICAL POUR LE LIVRABLE (CHEF OF STAFF)")
print("="*70)

print("\n1. BANC 1 : 50 PIÈCES ÉTALON (EXACTITUDE)")
print("-" * 50)
if fp8_p:
    hw = fp8_p.get("hardware", {})
    perf = fp8_p.get("performance", {})
    acc = fp8_p.get("accuracy", {})
    print(f"[72B-FP8] VRAM Peak : {hw.get('peak_vram_mb', 0)/1024:.1f} Go | Avg Power : {hw.get('avg_power_w', 0):.1f} W | Latence : {perf.get('latency_s_per_piece', 0):.2f} s")
    print(f"          P/R Entités: {acc.get('entities', {}).get('precision', 0):.2f}/{acc.get('entities', {}).get('recall', 0):.2f} | Infractions: Circuit={acc.get('circuit_found')} Smurf={acc.get('smurfing_found')} UBO={acc.get('hidden_beneficiary_found')}")

if awq_p:
    hw = awq_p.get("hardware", {})
    perf = awq_p.get("performance", {})
    acc = awq_p.get("accuracy", {})
    print(f"[72B-AWQ] VRAM Peak : {hw.get('peak_vram_mb', 0)/1024:.1f} Go | Avg Power : {hw.get('avg_power_w', 0):.1f} W | Latence : {perf.get('latency_s_per_piece', 0):.2f} s")
    print(f"          P/R Entités: {acc.get('entities', {}).get('precision', 0):.2f}/{acc.get('entities', {}).get('recall', 0):.2f} | Infractions: Circuit={acc.get('circuit_found')} Smurf={acc.get('smurfing_found')} UBO={acc.get('hidden_beneficiary_found')}")
else:
    print("[72B-AWQ] EN ATTENTE DU RUN DE 6H00...")

if b7_p:
    hw = b7_p.get("hardware", {})
    perf = b7_p.get("performance", {})
    acc = b7_p.get("accuracy", {})
    print(f"[7B-RTX ] Latence : {perf.get('latency_s_per_piece', 0):.2f} s | Rappel : {acc.get('entities', {}).get('recall', 0):.2f} | Infractions: {acc.get('circuit_found')}")

print("\n2. BANC 2 : CHARGE 500 PIÈCES / 10 AFFAIRES")
print("-" * 50)
if fp8_b:
    perf = fp8_b.get("performance", {})
    print(f"[72B-FP8 Batch] Durée : {perf.get('total_time_s', 0):.0f} s ({perf.get('total_time_s', 0)/3600:.2f} h) | Débit : {perf.get('throughput_pieces_per_min', 0):.1f} p/min")

if awq_b:
    perf = awq_b.get("performance", {})
    print(f"[72B-AWQ Batch] Durée : {perf.get('total_time_s', 0):.0f} s ({perf.get('total_time_s', 0)/3600:.2f} h) | Débit : {perf.get('throughput_pieces_per_min', 0):.1f} p/min")
else:
    print("[72B-AWQ Batch] EN ATTENTE DU RUN DE 6H00...")

print("\n" + "="*70 + "\n")
