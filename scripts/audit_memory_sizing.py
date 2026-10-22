"""Audit et dimensionnement transparent de la mémoire unifiée pour l'ASUS Ascent GX10 (GB10).

Vérifie l'adéquation physique d'un modèle et de sa configuration d'inférence sous le
cap mémoire de 90 % (119,2 GiB utiles sur 128 Go LPDDR5x unifiés).

Formule de dimensionnement :
    Budget Total = M_poids + M_kv_cache + M_activations + M_cuda + M_os <= 119,2 GiB

Usage :
    uv run python scripts/audit_memory_sizing.py --model 72b --quant fp8
    uv run python scripts/audit_memory_sizing.py --model 72b --quant awq
    uv run python scripts/audit_memory_sizing.py --model 124b --quant awq
    uv run python scripts/audit_memory_sizing.py --model 235b --quant fp8
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

# Permet l'import fin_enclave si exécuté depuis fin-enclave/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from fin_enclave.config import MODEL_LARGE, MODEL_SMALL, MODEL_T1

console = Console(width=110)

TOTAL_UNIFIED_RAM_GB = 128.0
USABLE_CAP_GIB = 119.2  # ~90 % de la mémoire physique disponible

# Réservations système et tampons matériels (GiB)
OS_OVERHEAD_GIB = 5.0
CUDA_RUNTIME_GIB = 2.0
VISION_ACTIVATIONS_GIB = 3.5
PADDLEOCR_WEIGHTS_GIB = 2.5


@dataclass
class ArchitectureSpec:
    model_id: str
    display_name: str
    params_b: float
    layers: int
    hidden_size: int
    num_heads: int
    kv_heads: int
    head_dim: int
    attn_type: str
    weights_gib: dict[str, float]
    weights_gb: dict[str, float]


SPECS: dict[str, ArchitectureSpec] = {
    "72b": ArchitectureSpec(
        model_id=MODEL_T1,
        display_name="Qwen2.5-VL-72B-Instruct",
        params_b=72.7,
        layers=80,
        hidden_size=8192,
        num_heads=64,
        kv_heads=8,
        head_dim=128,
        attn_type="GQA (8 têtes KV / 64 Q)",
        weights_gib={
            "fp8": 71.36,
            "awq": 40.05,
            "bf16": 135.40,
        },
        weights_gb={
            "fp8": 76.62,
            "awq": 43.00,
            "bf16": 145.40,
        },
    ),
    "124b": ArchitectureSpec(
        model_id="mistralai/Pixtral-Large-Instruct-2411",
        display_name="Pixtral-Large-Instruct-2411 (124B)",
        params_b=124.0,
        layers=88,
        hidden_size=12288,
        num_heads=96,
        kv_heads=8,
        head_dim=128,
        attn_type="GQA (8 têtes KV / 96 Q)",
        weights_gib={
            "fp8": 118.00,
            "awq": 68.50,
            "bf16": 231.00,
        },
        weights_gb={
            "fp8": 126.70,
            "awq": 73.55,
            "bf16": 248.00,
        },
    ),
    "8b": ArchitectureSpec(
        model_id=MODEL_SMALL,
        display_name="Qwen3-VL-8B-Instruct",
        params_b=8.3,
        layers=36,
        hidden_size=4096,
        num_heads=32,
        kv_heads=8,
        head_dim=128,
        attn_type="GQA (8 têtes KV / 32 Q)",
        weights_gib={
            "fp8": 8.50,
            "awq": 5.00,
            "bf16": 16.33,
        },
        weights_gb={
            "fp8": 9.12,
            "awq": 5.37,
            "bf16": 17.53,
        },
    ),
    "235b": ArchitectureSpec(
        model_id=MODEL_LARGE,
        display_name="Qwen3-VL-235B-A22B (MoE 235B/22B)",
        params_b=235.0,
        layers=96,
        hidden_size=8192,
        num_heads=64,
        kv_heads=8,
        head_dim=128,
        attn_type="MoE GQA (8 têtes KV / 64 Q)",
        weights_gib={
            "fp8": 220.70,
            "awq": 125.70,
            "bf16": 437.70,
        },
        weights_gb={
            "fp8": 237.00,
            "awq": 135.00,
            "bf16": 470.00,
        },
    ),
}


def compute_kv_token_bytes(spec: ArchitectureSpec, kv_dtype: str = "fp8") -> int:
    """Calcule la taille en octets d'un token dans le KV Cache.

    Formule : 2 (K et V) * couches * têtes_kv * head_dim * octets_par_élément.
    """
    bytes_per_elem = 1 if kv_dtype == "fp8" else 2
    return 2 * spec.layers * spec.kv_heads * spec.head_dim * bytes_per_elem


@dataclass
class MemoryBudgetVerdict:
    remaining_kv_pool_gib: float
    max_guaranteed_tokens: int
    max_concurrent_full_seqs: int
    target_tokens: int
    target_kv_gib: float
    headroom_gib: float
    verdict: str  # "VALIDE", "ATTENTION", "ECHEC"
    status_label: str
    verdict_color: str


def evaluate_memory_verdict(
    spec: ArchitectureSpec,
    quant: str = "fp8",
    context_len: int = 8192,
    max_num_seqs: int = 16,
    kv_quant: str = "fp8",
    with_t2: bool = True,
) -> MemoryBudgetVerdict:
    """Évalue l'adéquation mémoire d'un modèle et retourne le bilan et le verdict."""
    t2_overhead = PADDLEOCR_WEIGHTS_GIB if with_t2 else 0.0
    fixed_overhead = OS_OVERHEAD_GIB + CUDA_RUNTIME_GIB + VISION_ACTIVATIONS_GIB + t2_overhead

    model_weight_gib = spec.weights_gib[quant]
    remaining_kv_pool_gib = USABLE_CAP_GIB - fixed_overhead - model_weight_gib
    bytes_per_token = compute_kv_token_bytes(spec, kv_quant)
    gib_per_token = bytes_per_token / (1024**3)

    if remaining_kv_pool_gib > 0:
        max_guaranteed_tokens = int((remaining_kv_pool_gib * (1024**3)) // bytes_per_token)
        max_concurrent_full_seqs = max_guaranteed_tokens // context_len
    else:
        max_guaranteed_tokens = 0
        max_concurrent_full_seqs = 0

    target_tokens = max_num_seqs * context_len
    target_kv_gib = target_tokens * gib_per_token
    headroom_gib = remaining_kv_pool_gib - target_kv_gib

    if remaining_kv_pool_gib <= 0:
        verdict = "ECHEC"
        status_label = f"[bold red]ÉCHEC (OOM - Dépassement de {-remaining_kv_pool_gib:.1f} GiB)[/]"
        verdict_color = "red"
    elif max_guaranteed_tokens < target_tokens:
        verdict = "ATTENTION"
        status_label = (
            f"[bold yellow]ATTENTION (Pool insuffisant pour {max_num_seqs} flux pleins : "
            f"max {max_concurrent_full_seqs})[/]"
        )
        verdict_color = "yellow"
    else:
        verdict = "VALIDE"
        status_label = f"[bold green]VALIDE ({max_concurrent_full_seqs} séquences pleines sans OOM garanties)[/]"
        verdict_color = "green"

    return MemoryBudgetVerdict(
        remaining_kv_pool_gib=remaining_kv_pool_gib,
        max_guaranteed_tokens=max_guaranteed_tokens,
        max_concurrent_full_seqs=max_concurrent_full_seqs,
        target_tokens=target_tokens,
        target_kv_gib=target_kv_gib,
        headroom_gib=headroom_gib,
        verdict=verdict,
        status_label=status_label,
        verdict_color=verdict_color,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--model",
        choices=["72b", "124b", "8b", "235b"],
        default="72b",
        help="Architecture cible (défaut : 72b)",
    )
    parser.add_argument(
        "--quant",
        choices=["fp8", "awq", "bf16"],
        default="fp8",
        help="Format de quantification des poids (défaut : fp8)",
    )
    parser.add_argument(
        "--context-len",
        type=int,
        default=8192,
        help="Longueur de contexte maximale par requête (défaut : 8192)",
    )
    parser.add_argument(
        "--max-num-seqs",
        type=int,
        default=16,
        help="Nombre de requêtes concurrentes maximales vLLM (défaut : 16)",
    )
    parser.add_argument(
        "--kv-quant",
        choices=["fp8", "fp16"],
        default="fp8",
        help="Format de stockage du KV-cache PagedAttention (défaut : fp8)",
    )
    parser.add_argument(
        "--no-t2",
        action="store_true",
        help="Désactiver l'instance T2 (PaddleOCR-VL 2.5 GiB) pour simuler un profil mono",
    )
    args = parser.parse_args()

    spec = SPECS[args.model]
    model_weight_gib = spec.weights_gib[args.quant]
    model_weight_gb = spec.weights_gb[args.quant]

    budget = evaluate_memory_verdict(
        spec=spec,
        quant=args.quant,
        context_len=args.context_len,
        max_num_seqs=args.max_num_seqs,
        kv_quant=args.kv_quant,
        with_t2=not args.no_t2,
    )
    remaining_kv_pool_gib = budget.remaining_kv_pool_gib
    max_guaranteed_tokens = budget.max_guaranteed_tokens
    max_concurrent_full_seqs = budget.max_concurrent_full_seqs
    target_tokens = budget.target_tokens
    target_kv_gib = budget.target_kv_gib
    headroom_gib = budget.headroom_gib
    status_label = budget.status_label
    verdict_color = budget.verdict_color
    bytes_per_token = compute_kv_token_bytes(spec, args.kv_quant)

    console.print()
    console.print(
        Panel(
            f"[bold cyan]AUDIT DU DIMENSIONNEMENT MÉMOIRE GX10[/bold cyan]\n"
            f"Station : [bold]ASUS Ascent GX10[/bold] · NVIDIA Grace Blackwell GB10 · "
            f"128 Go LPDDR5x unifiés\n"
            f"Modèle : [bold]{spec.display_name}[/bold] ({args.quant.upper()}) · "
            f"Statut : {status_label}",
            border_style=verdict_color,
            expand=False,
        )
    )

    # 1. Caractéristiques architecture
    t_arch = Table(
        title="1. Architecture & Poids du Modèle",
        title_justify="left",
        border_style="blue",
    )
    t_arch.add_column("Propriété", style="bold")
    t_arch.add_column("Valeur", justify="right")
    t_arch.add_column("Détail / Note")

    t_arch.add_row("Identifiant HuggingFace", spec.model_id, "")
    t_arch.add_row("Nombre de paramètres", f"{spec.params_b:.1f} Mds", "")
    t_arch.add_row("Quantification des poids", args.quant.upper(), "")
    t_arch.add_row(
        "Poids mémoire vive (GiB)",
        f"{model_weight_gib:.2f} GiB",
        f"~{model_weight_gb:.2f} Go décimaux",
    )
    t_arch.add_row(
        "Architecture d'attention",
        spec.attn_type,
        f"{spec.layers} couches, dim {spec.head_dim}",
    )
    t_arch.add_row(
        "Taille KV-cache par token",
        f"{bytes_per_token:,} B",
        f"{bytes_per_token / 1024:.1f} KiB/tok ({args.kv_quant.upper()})",
    )
    console.print(t_arch)

    # 2. Bilan d'allocation
    t_mem = Table(
        title=(
            f"2. Bilan d'Allocation de la Mémoire Unifiée (Cap 90 % = {USABLE_CAP_GIB:.1f} GiB)"
        ),
        title_justify="left",
        border_style="cyan",
    )
    t_mem.add_column("Composante", style="bold")
    t_mem.add_column("Volume alloué", justify="right")
    t_mem.add_column("Part cap", justify="right")
    t_mem.add_column("Rôle / Justification")

    def row_mem(label: str, gib: float, desc: str, style: str = "") -> None:
        pct = (gib / USABLE_CAP_GIB) * 100
        t_mem.add_row(
            f"[{style}]{label}[/{style}]" if style else label,
            f"{gib:.2f} GiB",
            f"{pct:.1f} %",
            desc,
        )

    row_mem("OS Linux & Runtime Host", OS_OVERHEAD_GIB, "Noyau, daemons système, swap virtuel")
    row_mem("Contexte CUDA & PyTorch", CUDA_RUNTIME_GIB, "Driver GPU, gestionnaires de mémoire")
    row_mem(
        "Activations Vision",
        VISION_ACTIVATIONS_GIB,
        "Tampons d'inférence visuelle (scans A4)",
    )
    if not args.no_t2:
        row_mem(
            "Poids T2 (PaddleOCR-VL)",
            PADDLEOCR_WEIGHTS_GIB,
            "Extraction tabulaire dédiée :8001",
        )
    else:
        row_mem("Poids T2 (Désactivé)", 0.0, "Mode mono-modèle sans OCR dédié")

    row_mem(
        f"Poids Modèle T1 ({args.quant.upper()})",
        model_weight_gib,
        "Shards FP8 / AWQ chargés en VRAM",
        "bold",
    )

    kv_style = "bold green" if remaining_kv_pool_gib > 0 else "bold red"
    t_mem.add_section()
    row_mem(
        "Pool KV-Cache disponible",
        max(0.0, remaining_kv_pool_gib),
        "PagedAttention vLLM pour sessions concurrentes",
        kv_style,
    )
    console.print(t_mem)

    # 3. Dimensionnement KV Cache & Concurrence
    t_kv = Table(
        title="3. Dimensionnement Concurrence & Débit",
        title_justify="left",
        border_style="magenta",
    )
    t_kv.add_column("Métrique d'Inférence", style="bold")
    t_kv.add_column("Valeur", justify="right")
    t_kv.add_column("Analyse")

    t_kv.add_row(
        "Longueur de contexte requise",
        f"{args.context_len:,} tok",
        "Contexte max par requête (--max-model-len)",
    )
    t_kv.add_row(
        "Requêtes concurrentes cibles",
        f"{args.max_num_seqs}",
        "Parallélisme ciblé (--max-num-seqs)",
    )
    t_kv.add_row(
        "Besoin KV pour cible pleine",
        f"{target_kv_gib:.2f} GiB",
        f"{target_tokens:,} tokens ({args.max_num_seqs} × {args.context_len})",
    )
    t_kv.add_row(
        "Capacité max tokens garantis",
        f"{max_guaranteed_tokens:,} tok",
        "Tokens allouables sans débordement",
    )
    t_kv.add_row(
        "Flux complets garantis",
        f"{max_concurrent_full_seqs}",
        f"À {args.context_len:,} tokens chacun",
    )

    headroom_style = "green" if headroom_gib >= 0 else "red"
    t_kv.add_row(
        "Marge de sécurité restante",
        f"[{headroom_style}]{headroom_gib:+.2f} GiB[/{headroom_style}]",
        "Marge après saturation des requêtes cibles",
    )
    console.print(t_kv)
    console.print()


if __name__ == "__main__":
    main()
