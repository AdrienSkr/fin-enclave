"""
Agrégation des résultats comparatifs (CPU sans LLM vs 8B vs 235B) sur plusieurs graines.

Lit les fichiers 'comparaison.json' générés sur différents dossiers (ex: graines 1, 2, 3)
et calcule pour chaque station la moyenne et l'écart min-max.
Produit un affichage console Rich et un tableau Markdown prêt pour le README.

Usage :
    uv run python scripts/aggregate_comparison.py path/to/c1.json path/to/c2.json path/to/c3.json
    uv run python scripts/aggregate_comparison.py data/outputs/complexe_s*/comparaison.json
"""

import argparse
import glob
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

# Windows cp1252 ne gère pas ≈ et certains accents Rich ; forcer UTF-8 sur stdout.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
console = Console(width=120, force_terminal=True)


def _fmt(val_list: list[float], is_percent: bool = True) -> str:
    if not val_list:
        return "—"
    mean = sum(val_list) / len(val_list)
    mn, mx = min(val_list), max(val_list)
    if is_percent:
        return f"{mean:.1%} [{mn:.1%} - {mx:.1%}]"
    return f"{mean:.2f} [{mn:.2f} - {mx:.2f}]"


def _fmt_pr(p_list: list[float], r_list: list[float]) -> str:
    if not p_list or not r_list:
        return "—"
    p_mean = sum(p_list) / len(p_list)
    r_mean = sum(r_list) / len(r_list)
    return f"{p_mean:.2f} / {r_mean:.2f}"


def aggregate(files: list[Path], dataset_name: str = "") -> None:
    if not files:
        console.print("[red]Aucun fichier comparaison.json fourni ou trouvé.[/red]")
        return

    console.print(f"[bold cyan]Agrégation sur {len(files)} dossier(s) :[/bold cyan]")
    for f in files:
        console.print(f"  • {f}")

    # Données par tier
    # tier_name -> { metric -> list of values }
    tiers_data: dict[str, dict] = {}
    tier_meta: dict[str, dict] = {}
    all_typos: list[str] = []

    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data:
            if not row.get("measured"):
                continue
            tier = row["tier"]
            if tier not in tiers_data:
                tiers_data[tier] = {
                    "ent_p": [],
                    "ent_r": [],
                    "rel_p": [],
                    "rel_r": [],
                    "tx_p": [],
                    "tx_r": [],
                    "hallucinated": [],
                    "failed": [],
                    "circuit": [],
                    "fractionnement": [],
                    "beneficiaire": [],
                    "typos": {},
                }
                tier_meta[tier] = {
                    "station": row.get("station", ""),
                    "memory": row.get("memory", ""),
                    "model": row.get("model", ""),
                }

            td = tiers_data[tier]
            td["ent_p"].append(row["entities"]["precision"])
            td["ent_r"].append(row["entities"]["recall"])
            td["rel_p"].append(row["relations"]["precision"])
            td["rel_r"].append(row["relations"]["recall"])
            td["tx_p"].append(row["transfers"]["precision"])
            td["tx_r"].append(row["transfers"]["recall"])
            td["hallucinated"].append(row.get("hallucinated_entities", 0))
            td["failed"].append(row.get("failed_pieces", 0))

            fnd = row.get("findings", {})
            td["circuit"].append(1.0 if fnd.get("circuit") else 0.0)
            td["fractionnement"].append(1.0 if fnd.get("fractionnement") else 0.0)
            td["beneficiaire"].append(1.0 if fnd.get("beneficiaire_cache") else 0.0)

            typos = row.get("typologies", {})
            for t_name, t_val in typos.items():
                if t_name not in all_typos:
                    all_typos.append(t_name)
                td["typos"].setdefault(t_name, []).append(t_val["recall"])

    # Table Rich
    title_suffix = f" (dossier {dataset_name})" if dataset_name else ""
    table = Table(
        title=f"Moyenne et écarts min-max sur {len(files)} graines{title_suffix}",
        border_style="magenta",
    )
    table.add_column("Métrique")
    tier_names = list(tiers_data.keys())
    for t in tier_names:
        meta = tier_meta[t]
        table.add_column(f"{t}\n[dim]{meta['station']}[/dim]", justify="center")

    table.add_row("Mémoire des poids", *(tier_meta[t]["memory"] for t in tier_names))
    table.add_section()
    table.add_row("[bold]Lecture des pièces (P / R)[/bold]", *("" for _ in tier_names))
    table.add_row(
        "  Entités", *(_fmt_pr(tiers_data[t]["ent_p"], tiers_data[t]["ent_r"]) for t in tier_names)
    )
    table.add_row(
        "  Liens détention / contrôle",
        *(_fmt_pr(tiers_data[t]["rel_p"], tiers_data[t]["rel_r"]) for t in tier_names),
    )
    table.add_row(
        "  Virements", *(_fmt_pr(tiers_data[t]["tx_p"], tiers_data[t]["tx_r"]) for t in tier_names)
    )
    table.add_row(
        "  Noms inventés (rejetés OCR)",
        *(_fmt(tiers_data[t]["hallucinated"], is_percent=False) for t in tier_names),
    )
    table.add_row(
        "  Pièces illisibles",
        *(_fmt(tiers_data[t]["failed"], is_percent=False) for t in tier_names),
    )

    table.add_section()
    table.add_row("[bold]Constats retrouvés (taux de succès)[/bold]", *("" for _ in tier_names))
    table.add_row("  Circuit fermé", *(_fmt(tiers_data[t]["circuit"]) for t in tier_names))
    table.add_row("  Fractionnement", *(_fmt(tiers_data[t]["fractionnement"]) for t in tier_names))
    table.add_row(
        "  Bénéficiaire caché", *(_fmt(tiers_data[t]["beneficiaire"]) for t in tier_names)
    )

    if all_typos:
        table.add_section()
        table.add_row("[bold]Rappel par typologie IBM AML[/bold]", *("" for _ in tier_names))
        for typo in all_typos:
            table.add_row(
                f"  {typo}",
                *(_fmt(tiers_data[t]["typos"].get(typo, [])) for t in tier_names),
            )

    console.print(table)

    # Affichage du Markdown prêt à copier
    console.print("\n[bold cyan]Tableau Markdown formaté pour le README :[/bold cyan]\n")
    md_header = (
        "| Métrique | " + " | ".join(f"{t} ({tier_meta[t]['station']})" for t in tier_names) + " |"
    )
    md_sep = "|---|" + "|".join("---:" for _ in tier_names) + "|"
    print(md_header)
    print(md_sep)
    print("| Mémoire | " + " | ".join(tier_meta[t]["memory"] for t in tier_names) + " |")
    print(
        "| Entités (P / R) | "
        + " | ".join(_fmt_pr(tiers_data[t]["ent_p"], tiers_data[t]["ent_r"]) for t in tier_names)
        + " |"
    )
    print(
        "| Liens gouvernance (P / R) | "
        + " | ".join(_fmt_pr(tiers_data[t]["rel_p"], tiers_data[t]["rel_r"]) for t in tier_names)
        + " |"
    )
    print(
        "| Virements (P / R) | "
        + " | ".join(_fmt_pr(tiers_data[t]["tx_p"], tiers_data[t]["tx_r"]) for t in tier_names)
        + " |"
    )
    print(
        "| Hallucinations rejetées | "
        + " | ".join(_fmt(tiers_data[t]["hallucinated"], is_percent=False) for t in tier_names)
        + " |"
    )
    print(
        "| Circuit fermé | " + " | ".join(_fmt(tiers_data[t]["circuit"]) for t in tier_names) + " |"
    )
    if all_typos:
        for typo in all_typos:
            print(
                f"| Typologie IBM {typo} | "
                + " | ".join(_fmt(tiers_data[t]["typos"].get(typo, [])) for t in tier_names)
                + " |"
            )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--set",
        dest="dataset_set",
        choices=["realiste", "complexe"],
        default="realiste",
        help="Jeu de données par défaut (realiste ou complexe)",
    )
    ap.add_argument("files", nargs="*", type=str, help="Fichiers comparaison.json ou motifs glob")
    args = ap.parse_args()

    targets: list[Path] = []
    if args.files:
        for pattern in args.files:
            matches = glob.glob(pattern)
            if matches:
                targets.extend(Path(m) for m in matches)
            elif Path(pattern).exists():
                targets.append(Path(pattern))
    else:
        # Recherche par défaut selon le jeu choisi
        chosen = [
            Path(f"data/outputs/{args.dataset_set}_s1/comparaison.json"),
            Path(f"data/outputs/{args.dataset_set}_s2/comparaison.json"),
            Path(f"data/outputs/{args.dataset_set}_s3/comparaison.json"),
        ]
        targets = [p for p in chosen if p.exists()]
        if not targets:
            # Repli sur l'autre jeu si le jeu demandé n'existe pas encore
            other_set = "complexe" if args.dataset_set == "realiste" else "realiste"
            other = [
                Path(f"data/outputs/{other_set}_s1/comparaison.json"),
                Path(f"data/outputs/{other_set}_s2/comparaison.json"),
                Path(f"data/outputs/{other_set}_s3/comparaison.json"),
            ]
            targets = [p for p in other if p.exists()]
        if not targets:
            # Essai sur n'importe quel comparaison.json dans outputs
            targets = list(Path("data/outputs").glob("**/comparaison.json"))

    aggregate(targets, dataset_name=args.dataset_set)


if __name__ == "__main__":
    main()
