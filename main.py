"""
FinEnclave : une commande, un dossier de pièces -> qui détient quoi, qui est au centre,
où va l'argent, avec la pièce qui fonde chaque lien.

    uv run python main.py                      # dossier de démonstration (rejouable hors ligne)
    uv run python main.py --dossier MES_PIECES # n'importe quel dossier de scans / photos / PDF
    uv run python main.py --forge              # régénère le dossier de démo depuis la base ICIJ
"""

import argparse
import json
import sys
import time
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from fin_enclave.comparison import compare
from fin_enclave.config import settings
from fin_enclave.documents.evaluation import (
    evaluate_graph,
    evaluate_pieces,
    evaluate_scenario,
)
from fin_enclave.documents.extractor import (
    RuleEngine,
    VLMEngine,
    cached_coverage,
)
from fin_enclave.documents.forge import (
    forge_dossier,
    scenario_path,
    select_case,
    truth_path,
)
from fin_enclave.documents.ocr import IMAGE_SUFFIXES
from fin_enclave.investigation import investigate
from fin_enclave.reporting import write_outputs

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

console = Console(width=120)
DEMO_DOSSIER = Path("data/demo/pieces")


def _usd(x: float) -> str:
    return f"{x:,.0f} USD".replace(",", " ")


def _cache_dir(dossier: Path) -> Path:
    """Lectures scellées du dossier, versionnées à côté de lui : rejouables sans réseau."""
    return dossier.parent / f"{dossier.name}.extractions"


def forge(dossier: Path, icij: Path, companies: int, distractors: int, seed: int) -> None:
    from fin_enclave.documents.forge import anonymize_case
    from fin_enclave.graph.structural import detect_nominee_hubs
    from fin_enclave.ingestion.icij_loader import load_offshore_leaks

    case_file = dossier.parent / f"{dossier.name}.cas_icij.json"
    if icij.exists():
        with console.status("Chargement de la base ICIJ Offshore Leaks (Panama Papers)..."):
            G = load_offshore_leaks(icij)
            hub = next(h for h in detect_nominee_hubs(G, 30) if 40 <= h["k_out"] <= 150)
            raw = select_case(G, hub["node"], companies, seed)
            # Anonymisation AVANT écriture : le dépôt ne contient jamais de noms ICIJ bruts
            case = anonymize_case(raw, seed)
        case_file.parent.mkdir(parents=True, exist_ok=True)
        case_file.write_text(json.dumps(case, indent=2, ensure_ascii=False), encoding="utf-8")
        console.print(
            f"[green]✓[/green] Topologie ICIJ (hub {hub['k_out']} sociétés) → "
            f"{len(case)} sociétés, [bold]noms fictifs[/bold] (aucune identité réelle)"
        )
    elif case_file.exists():
        case = json.loads(case_file.read_text(encoding="utf-8"))
        console.print(f"[green]✓[/green] Cas anonymisé relu depuis {case_file}")
    else:
        sys.exit(f"Base ICIJ absente ({icij}) et aucun extrait {case_file} : voir README.")
    if dossier.exists():
        for f in dossier.glob("PIECE-*"):
            f.unlink()
    # Déjà anonymisé dans case_file : ne pas re-anonymiser (sinon double alias)
    pieces = forge_dossier(case, dossier, distractors, seed, anonymize=False)
    console.print(f"[green]✓[/green] {len(pieces)} pièces générées dans {dossier}")


def forge_complex(
    dossier: Path,
    icij: Path,
    ibm_patterns_path: Path,
    companies: int,
    distractors: int,
    seed: int,
    preset: str = "stress",
) -> None:
    from fin_enclave.documents.forge import anonymize_case
    from fin_enclave.documents.forge_complex import PRESETS, STRESS, forge_complex_dossier
    from fin_enclave.graph.structural import detect_nominee_hubs
    from fin_enclave.ingestion.ibm_aml import parse_ibm_patterns, select_attempts
    from fin_enclave.ingestion.icij_loader import load_offshore_leaks

    difficulty = PRESETS.get(preset, STRESS)
    case_file = dossier.parent / f"{dossier.name}.cas_icij.json"
    fallback_case = Path("data/demo/pieces.cas_icij.json")
    if icij.exists():
        with console.status("Chargement de la base ICIJ Offshore Leaks (Panama Papers)..."):
            G = load_offshore_leaks(icij)
            hub = next(h for h in detect_nominee_hubs(G, 30) if 40 <= h["k_out"] <= 150)
            raw = select_case(G, hub["node"], companies, seed)
            case = anonymize_case(raw, seed)
        case_file.parent.mkdir(parents=True, exist_ok=True)
        case_file.write_text(json.dumps(case, indent=2, ensure_ascii=False), encoding="utf-8")
        console.print(
            f"[green]✓[/green] Topologie ICIJ (hub {hub['k_out']} sociétés) → "
            f"{len(case)} sociétés, [bold]noms fictifs[/bold]"
        )
    elif case_file.exists():
        case = json.loads(case_file.read_text(encoding="utf-8"))
        console.print(f"[green]✓[/green] Cas anonymisé relu depuis {case_file}")
    elif fallback_case.exists():
        case = json.loads(fallback_case.read_text(encoding="utf-8"))
        console.print(f"[green]✓[/green] Cas anonymisé relu depuis {fallback_case}")
    else:
        sys.exit(f"Base ICIJ absente ({icij}) et aucun extrait {case_file} ou {fallback_case}.")

    if not ibm_patterns_path.exists():
        sys.exit(f"Fichier de motifs IBM AML introuvable : {ibm_patterns_path}.")
    with console.status(f"Chargement et sélection des motifs IBM AMLworld ({difficulty.name})..."):
        all_attempts = parse_ibm_patterns(ibm_patterns_path)
        selected_attempts = select_attempts(
            all_attempts, seed=seed, typologies=difficulty.typologies
        )
    console.print(
        f"[green]✓[/green] {len(selected_attempts)} typologies IBM AML sélectionnées "
        f"({sum(len(a['transactions']) for a in selected_attempts)} tx) [preset {difficulty.name}]"
    )

    if dossier.exists():
        for f in dossier.glob("PIECE-*"):
            f.unlink()

    with console.status(f"Génération des pièces du dossier complexe dans {dossier}..."):
        pieces = forge_complex_dossier(
            case=case,
            ibm_attempts=selected_attempts,
            out_dir=dossier,
            n_distractors=distractors,
            seed=seed,
            anonymize=False,
            render_images=True,
            difficulty=difficulty,
        )
    console.print(f"[green]✓[/green] {len(pieces)} pièces complexes générées dans {dossier}")


def choose_engine(kind: str, dossier: Path):
    if kind == "rules":
        return RuleEngine(), "règles + Tesseract (hors ligne)"
    key = settings.get_effective_api_key()
    live = settings.llm_backend == "local_gx10" or (key and key != "EMPTY" and "your_" not in key)
    vlm = VLMEngine()
    where = "vLLM local (GX10)" if settings.llm_backend == "local_gx10" else settings.llm_backend
    if kind == "vlm" or live:
        return vlm, f"modèle de vision {vlm.model} ({where})"
    if cached_coverage(dossier, vlm, _cache_dir(dossier)) == 1.0:
        return vlm, f"rejeu des lectures scellées de {vlm.model} (aucun appel réseau)"
    return RuleEngine(), "règles + Tesseract (hors ligne, aucune clé configurée)"


def evaluate(inv, dossier: Path) -> dict | None:
    tp = truth_path(dossier)
    if not tp.exists():
        return None
    truth = json.loads(tp.read_text(encoding="utf-8"))
    out = {
        "pieces": evaluate_pieces(inv.pieces, truth),
        "graph": evaluate_graph(inv.graph, truth),
        "scenario_simulated": False,
    }
    sp = scenario_path(dossier)
    if sp.exists():
        scenario = json.loads(sp.read_text(encoding="utf-8"))
        out["scenario"] = evaluate_scenario(inv.findings, scenario)
        out["scenario_simulated"] = bool(scenario.get("simulated"))
    return out


def show(inv) -> None:
    f = inv.findings
    t = Table(title="Qui est au centre", title_justify="left", border_style="blue")
    for c in ("Acteur", "Sociétés", "Profil"):
        t.add_column(c)
    for a in f["portfolios"][:5]:
        t.add_row(a["name"], str(a["n_companies"]), "prête-nom présumé" * a["nominee_profile"])
    console.print(t)

    for h in f["hidden_controllers"]:
        console.print(
            f"[bold red]Derrière le prête-nom :[/bold red] [bold]{h['name']}[/bold] a une "
            f"procuration sur {', '.join(h['companies'])} [dim]({', '.join(h['pieces'])})[/dim]"
        )

    t = Table(title="Où va l'argent (solde net des flux attestés)", title_justify="left")
    for c in ("Acteur", "Reçu", "Envoyé", "Solde net", "Pièces"):
        t.add_column(c, justify="right" if c in ("Reçu", "Envoyé", "Solde net") else "left")
    for m in f["money_ranking"][:6]:
        t.add_row(
            m["name"],
            _usd(m["received_usd"]),
            _usd(m["sent_usd"]),
            f"[bold]{_usd(m['net_usd'])}[/bold]",
            ", ".join(m["pieces"][:4]) + (" …" if len(m["pieces"]) > 4 else ""),
        )
    console.print(t)

    for c in f["cycles"]:
        console.print("[bold red]Circuit fermé :[/bold red]")
        for s in c["steps"]:
            console.print(
                f"  {s['date'] or '????-??-??'}  {s['from']} → {s['to']}  "
                f"[bold]{_usd(s['amount_usd'])}[/bold]  [dim]{', '.join(s['pieces'])}[/dim]"
            )
    for s in f["smurfing"]:
        console.print(
            f"[bold red]Fractionnement :[/bold red] {s['source_name']} → {s['n_mules']} relais "
            f"→ {s['collector_name']} ({_usd(s['total_collected_usd'])}, "
            f"{s['span_days']} jours) [dim]{', '.join(s['pieces'])}[/dim]"
        )
    for r in inv.reports:
        console.print(
            f"  [magenta]{r.infraction_type}[/magenta] — {_usd(r.total_amount_usd)} — "
            f"corroboration OCR {r.confidence_score:.0%}"
        )


def show_evaluation(ev: dict) -> None:
    p, g = ev["pieces"]["all"], ev["graph"]
    t = Table(title="Fiabilité mesurée (vérité terrain du dossier)", title_justify="left")
    for c in ("Mesure", "Précision", "Rappel"):
        t.add_column(c, justify="left" if c == "Mesure" else "right")
    for label, m in (
        ("Entités lues", p["entities"]),
        ("Liens détention / contrôle lus", p["relations"]),
        ("Virements lus", p["transfers"]),
        ("Liens du graphe", g["edges"]),
        ("Flux du graphe", g["flows"]),
    ):
        t.add_row(label, f"{m['precision']:.2f}", f"{m['recall']:.2f}")
    console.print(t)
    sc = ev.get("scenario")
    if sc:
        ok = {True: "[green]oui[/green]", False: "[red]non[/red]"}
        console.print(
            f"Scénario caché : circuit {ok[sc['cycle_found']]} · fractionnement "
            f"{ok[sc['smurfing_found']]} ({sc['mules_found']}/{sc['mules_expected']} relais) · "
            f"bénéficiaire caché {ok[sc['hidden_beneficiary_found']]}"
        )


def show_comparison(rows: list[dict]) -> None:
    def pr(m: dict) -> str:
        return f"{m['precision']:.2f} / {m['recall']:.2f}"

    def ok(b: bool) -> str:
        return "[green]oui[/green]" if b else "[red]non[/red]"

    t = Table(
        title="Même dossier, trois stations : qui retrouve le scénario caché ?",
        title_justify="left",
        border_style="magenta",
    )
    t.add_column("Mesure")
    for r in rows:
        t.add_column(f"{r['tier']}\n[dim]{r['station']}[/dim]", justify="center")
    measured = [r for r in rows if r["measured"]]

    def line(label: str, fn) -> None:
        t.add_row(label, *(fn(r) if r["measured"] else "[dim]non mesuré[/dim]" for r in rows))

    t.add_row("Mémoire des poids", *(r["memory"] for r in rows))
    t.add_section()
    t.add_row("[bold]Lecture des pièces[/bold] (P / R)", *("" for _ in rows))
    line("  Entités", lambda r: pr(r["entities"]))
    line("  Liens détention / contrôle", lambda r: pr(r["relations"]))
    line("  Virements", lambda r: pr(r["transfers"]))
    line("  Noms inventés (rejetés par l'OCR)", lambda r: str(r["hallucinated_entities"]))
    line("  Pièces illisibles", lambda r: str(r["failed_pieces"]))
    t.add_section()
    t.add_row("[bold]Constats retrouvés[/bold]", *("" for _ in rows))
    line("  Circuit fermé", lambda r: ok(r["findings"]["circuit"]))
    line("  Fractionnement", lambda r: ok(r["findings"]["fractionnement"]))
    line("  Bénéficiaire caché", lambda r: ok(r["findings"]["beneficiaire_cache"]))
    t.add_section()
    line(
        "[bold]Notes d'analyse fidèles aux faits[/bold]",
        lambda r: (
            f"{r['notes_llm']['accepted']} / {r['notes_llm']['total']}"
            if r["notes_llm"]
            else "[dim]pas de LLM[/dim]"
        ),
    )
    if any(r.get("typologies") for r in measured):
        t.add_section()
        t.add_row("[bold]Typologies IBM (transactions retrouvées)[/bold]", *("" for _ in rows))
        all_typos: list[str] = []
        for r in rows:
            for typo in r.get("typologies", {}):
                if typo not in all_typos:
                    all_typos.append(typo)
        for typo in all_typos:
            line(
                f"  {typo}",
                lambda r, typo_name=typo: (
                    f"{r['typologies'][typo_name]['found']}/{r['typologies'][typo_name]['total']} "
                    f"({r['typologies'][typo_name]['recall']:.0%})"
                    if r.get("typologies") and typo_name in r["typologies"]
                    else "—"
                ),
            )
    console.print(t)
    if len(measured) < len(rows):
        console.print(
            "[dim]Colonnes non mesurées : aucune lecture scellée pour ce modèle et aucune clé "
            "configurée (OPENROUTER_API_KEY ou LLM_BACKEND=local_gx10).[/dim]"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dossier", type=Path, default=DEMO_DOSSIER)
    ap.add_argument("--engine", choices=["auto", "vlm", "rules"], default="auto")
    ap.add_argument("--out", type=Path, default=Path(settings.output_dir) / "investigation")
    ap.add_argument("--forge", action="store_true", help="Régénérer le dossier de démonstration")
    ap.add_argument(
        "--forge-complex",
        action="store_true",
        help="Générer un dossier complexe (motifs IBM AML + relevés multi-pages)",
    )
    ap.add_argument(
        "--preset",
        choices=["stress", "realiste"],
        default="stress",
        help="Preset de difficulté pour --forge-complex (stress ou realiste)",
    )
    ap.add_argument(
        "--ibm-patterns",
        type=Path,
        default=Path("data/external/ibm_aml/HI-Small_Patterns.txt"),
        help="Chemin vers le fichier de motifs IBM AML",
    )
    ap.add_argument("--icij", type=Path, default=Path("data/external/oldb"))
    ap.add_argument("--companies", type=int, default=12)
    ap.add_argument("--distractors", type=int, default=6)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument(
        "--llm-notes",
        action="store_true",
        help="Faire rédiger les notes par le LLM (rejetées si elles s'écartent des faits)",
    )
    ap.add_argument("--open", action="store_true", help="Ouvrir le graphe dans le navigateur")
    ap.add_argument(
        "--no-compare",
        action="store_true",
        help="Ne pas comparer CPU sans LLM / petit modèle 8B / grand modèle 235B",
    )
    args = ap.parse_args()

    console.print(
        Panel(
            "[bold cyan]FINENCLAVE[/bold cyan]  dossier de pièces → qui détient quoi, "
            "qui est au centre, où va l'argent\n[dim]Station locale ASUS Ascent GX10 · "
            "chaque lien renvoie à sa pièce scellée (SHA-256)[/dim]",
            expand=False,
        )
    )
    if args.forge_complex:
        if args.dossier == DEMO_DOSSIER:
            args.dossier = (
                Path("data/demo/realiste")
                if args.preset == "realiste"
                else Path("data/demo/complexe")
            )
        if args.out == Path(settings.output_dir) / "investigation":
            args.out = Path(settings.output_dir) / args.dossier.name
        forge_complex(
            args.dossier,
            args.icij,
            args.ibm_patterns,
            args.companies,
            args.distractors,
            args.seed,
            preset=args.preset,
        )
    elif args.forge:
        forge(args.dossier, args.icij, args.companies, args.distractors, args.seed)
    if not args.dossier.exists():
        sys.exit(f"Dossier introuvable : {args.dossier} (option --forge pour le générer)")

    files = [p for p in args.dossier.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES]
    kinds = {s: sum(p.suffix.lower() == s for p in files) for s in (".png", ".pdf", ".jpg")}
    console.print(
        f"[bold cyan][1/4][/bold cyan] Dossier [yellow]{args.dossier}[/yellow] : {len(files)} "
        f"pièces non triées ({kinds['.pdf']} PDF scannés, {kinds['.jpg']} photos, "
        f"{kinds['.png']} images)"
    )
    engine, label = choose_engine(args.engine, args.dossier)
    console.print(f"[bold cyan][2/4][/bold cyan] Lecture des pièces : {label}")
    t0 = time.perf_counter()
    with console.status("Lecture, contrôle OCR témoin, mise en relation, détection..."):
        inv = investigate(
            args.dossier, engine, cache_dir=_cache_dir(args.dossier), llm_notes=args.llm_notes
        )
    n_tx = inv.findings["flows"]["count"]
    console.print(
        f"  [green]✓[/green] {len(inv.pieces)} pièces lues en {inv.timings['extraction_s']} s "
        f"({sum(p.from_cache for p in inv.pieces)} depuis les lectures scellées, "
        f"{sum(bool(p.error) for p in inv.pieces)} en échec)"
    )
    console.print(
        f"[bold cyan][3/4][/bold cyan] Graphe : {inv.graph.number_of_nodes()} entités, "
        f"{inv.graph.number_of_edges()} liens dont {n_tx} virements "
        f"({_usd(inv.findings['flows']['total_usd'])}) ; "
        f"{len(inv.findings['vigilance']['name_merges'])} variantes de noms fusionnées ; "
        "détection en "
        f"{inv.timings['graph_and_detection_s'] * 1000:.0f} ms"
    )
    show(inv)

    ev = evaluate(inv, args.dossier)
    paths = write_outputs(inv, args.out, ev)
    if ev:
        show_evaluation(ev)
    console.print("[bold cyan][4/4][/bold cyan] Livrables :")
    for label, key in (("Rapport", "markdown"), ("Graphe", "html"), ("Scellé JSON", "json")):
        console.print(
            f"  [green]✓[/green] {label} : [link={paths[key].resolve().as_uri()}]"
            f"{paths[key]}[/link]"
        )
    console.print(f"[dim]Terminé en {time.perf_counter() - t0:.1f} s, en local.[/dim]")
    if ev and not args.no_compare:
        console.print(
            "\n[bold cyan]Comparaison[/bold cyan] : le même dossier relu par trois stations"
        )
        with console.status("Lecture et analyse par chaque station..."):
            rows = compare(args.dossier, _cache_dir(args.dossier))
        show_comparison(rows)
        out = args.out / "comparaison.json"
        out.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        console.print(f"  [green]✓[/green] Comparaison : {out}")
    if args.open:
        webbrowser.open(paths["html"].resolve().as_uri())


if __name__ == "__main__":
    main()
