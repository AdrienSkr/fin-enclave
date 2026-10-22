"""Erreurs silencieuses du triage « à relire », par jeu et par station à lecture (rejeu hors ligne).

Chaque jeu de `data/demo/` est relu depuis ses lectures scellées (`<jeu>.extractions/`) par chaque
station dont toutes les lectures existent (8B, 72B, 235B). Chaque virement et chaque lien de
gouvernance est classé juste / faux / manquant, signalé ou non (pièce à relire ou en erreur, ligne
réparée, suspecte ou portant un motif `review_flags`) ; une pièce à relire par ses seules lignes ne
signale que ces lignes. Puis chaque contrôle déterministe candidat est évalué : erreurs
silencieuses qu'il fermerait encore, et charge de relecture qu'il ajouterait. Aucun appel réseau.

Usage : uv run python scripts/measure_review_triage.py [--set investigation] [--json out.json] [--markdown]
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from rich.console import Console
from rich.table import Table

from fin_enclave.comparison import TIERS
from fin_enclave.documents.extractor import (
    VLMEngine,
    _cache_file,
    _n_pages,
    cached_coverage,
    extract_piece,
    line_review_reason,
)
from fin_enclave.documents.forge import truth_path
from fin_enclave.documents.image_loader import IMAGE_SUFFIXES, file_sha256
from fin_enclave.documents.models import DocumentExtraction, PieceExtraction
from fin_enclave.documents.review_triage import (
    CONTROLS,
    Link,
    Outcome,
    PieceRead,
    Transfer,
    check_silent_ceilings,
    classify_links,
    classify_transfers,
    evaluate_control,
    summarize,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
console = Console(width=140, force_terminal=True)

ROOT = Path(__file__).parents[1]
DEMO = ROOT / "data" / "demo"
DATASETS = {"investigation": "pieces"}
STATIONS = {t.model: label for t, label in zip(TIERS[1:], ("8B", "72B", "235B"), strict=True)}


class _OfflineEngine(VLMEngine):
    """Moteur de rejeu : même extraction que la station, aucun appel au modèle."""

    def extract(self, *args, **kwargs):
        raise RuntimeError("rejeu hors ligne : extraction absente")


def _flagged_lines(path: Path, slug: str, cache_dir: Path) -> set[tuple[str, float]]:
    """(date, montant) des lignes de relevé réparées par solde ou suspectes, dans le scellé."""
    sha = file_sha256(path)
    out: set[tuple[str, float]] = set()
    for page in range(_n_pages(path)):
        f = _cache_file(sha, slug, cache_dir, page)
        if not f.exists():
            continue
        ext = DocumentExtraction.model_validate_json(f.read_text(encoding="utf-8"))
        for ln in ext.statement_lines:
            if ln.repair or ln.suspect:
                out.add((ln.date.isoformat() if ln.date else "", round(abs(ln.amount), 2)))
    return out


def _piece_read(p: PieceExtraction, flagged: set) -> PieceRead:
    grounded = {e.name.upper(): e.grounded for e in p.entities}
    transfers = [
        Transfer(
            t.payer,
            t.payee,
            t.amount,
            t.date.isoformat() if t.date else "",
            (t.date.isoformat() if t.date else "", round(t.amount, 2)) in flagged
            or bool(t.review_flags),
        )
        for t in p.transfers
    ]

    def witness(*names: str) -> bool | None:
        marks = [grounded.get(n.upper()) for n in names]
        return False if False in marks else (True if all(marks) else None)

    links = [r for r in p.relations if r.role != "other"]
    return PieceRead(
        piece_id=p.piece_id,
        doc_type=p.doc_type,
        transfers=transfers,
        links=[Link(r.source, r.target, r.role) for r in links],
        period=(p.period_start, p.period_end),
        amount_witness=[t.amount_grounded for t in p.transfers],
        party_witness=[witness(t.payer, t.payee) for t in p.transfers],
        link_witness=[witness(r.source, r.target) for r in links],
        side_witness=[None for _ in p.transfers],
        witness_text="",
        dated_rows=0,
    )


def measure(jeu: str, model: str) -> dict | None:
    folder = DEMO / DATASETS[jeu]
    cache_dir = DEMO / f"{DATASETS[jeu]}.extractions"
    engine = _OfflineEngine(model)
    if cached_coverage(folder, engine, cache_dir) < 1.0:
        return None
    truth = {t["piece_id"]: t for t in json.loads(truth_path(folder).read_text(encoding="utf-8"))}
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    outcomes: list[Outcome] = []
    reads: list[PieceRead] = []
    flagged_pieces: set[str] = set()
    lines_total = lines_flagged = 0
    reasons: Counter = Counter()
    line_motifs: Counter = Counter()
    for path in files:
        p = extract_piece(path, engine, use_cache=True, cache_dir=cache_dir)
        read = _piece_read(p, _flagged_lines(path, engine.slug, cache_dir))
        reads.append(read)
        if p.needs_review or p.error:
            flagged_pieces.add(p.piece_id)
        # Une pièce « à relire » par ses seules lignes ne signale que ces lignes (granularité ligne).
        line_reason = line_review_reason(p.transfers)
        piece_reasons = [r for r in p.review_reason.split("; ") if r and r != line_reason]
        piece_flagged = bool(piece_reasons) or bool(p.error)
        for r in piece_reasons or ([p.error] if p.error else []):
            reasons[r.split(" : ")[0][:60]] += 1
        line_motifs.update(f for t in p.transfers for f in t.review_flags)
        lines_total += len(read.transfers)
        lines_flagged += sum(piece_flagged or t.flagged for t in read.transfers)
        t = truth[p.piece_id]
        true_tx = [
            Transfer(x["payer"], x["payee"], x["amount"], x.get("date") or "")
            for x in t.get("transfers", [])
        ]
        true_links = [Link(r["source"], r["target"], r["role"]) for r in t["relations"]]
        outcomes += classify_transfers(p.piece_id, read.transfers, true_tx, piece_flagged)
        outcomes += classify_links(p.piece_id, read.links, true_links, piece_flagged)
    silent = [o for o in outcomes if o.silent]
    controls = {}
    for name, fn in CONTROLS.items():
        hits = fn(reads)
        controls[name] = evaluate_control(hits, outcomes, flagged_pieces)
        controls[name]["closed_ids"] = [k for k, o in enumerate(silent) if hits.closes(o)]
    return {
        "set": jeu,
        "station": STATIONS[model],
        "model": model,
        "pieces": len(files),
        "pieces_flagged": len(flagged_pieces),
        "review_reasons": dict(reasons.most_common()),
        "line_motifs": dict(line_motifs.most_common()),
        "lines": lines_total,
        "lines_flagged": lines_flagged,
        "transfers": summarize([o for o in outcomes if o.kind == "virement"]),
        "links": summarize([o for o in outcomes if o.kind == "lien"]),
        "all": summarize(outcomes),
        "silent_errors": [
            {
                "piece": o.piece_id,
                "kind": o.kind,
                "cause": o.cause,
                "read": o.read,
                "true": o.true,
            }
            for o in silent
        ],
        "controls": controls,
    }


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d:.0%})" if d else "0/0"


def _print_rows(rows: list[dict]) -> None:
    table = Table(title="Triage « à relire » contre la vérité", border_style="magenta")
    for col in (
        "Jeu",
        "Station",
        "Silencieuses / faits",
        "Virements",
        "Liens",
        "Silencieuses / erreurs",
        "Pièces à relire",
        "Lignes à relire",
        "Exactitude non-signalé",
    ):
        table.add_column(col, justify="center")
    for r in rows:
        a = r["all"]
        table.add_row(
            r["set"],
            r["station"],
            _pct(a["silent"], a["facts"]),
            str(r["transfers"]["silent"]),
            str(r["links"]["silent"]),
            _pct(a["silent"], a["errors"]),
            _pct(r["pieces_flagged"], r["pieces"]),
            _pct(r["lines_flagged"], r["lines"]),
            f"{a['unflagged_precision']:.1%} (n = {a['unflagged_read']})",
        )
    console.print(table)


def _markdown(rows: list[dict]) -> None:
    print(
        "| Jeu | Station | Erreurs silencieuses | Virements / liens | Part des erreurs "
        "non signalées | Pièces à relire | Lignes à relire | Exactitude du non-signalé |"
    )
    print("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
    for r in rows:
        a = r["all"]
        print(
            f"| {r['set']} | {r['station']} | {_pct(a['silent'], a['facts'])} | "
            f"{r['transfers']['silent']} / {r['links']['silent']} | "
            f"{_pct(a['silent'], a['errors'])} | {_pct(r['pieces_flagged'], r['pieces'])} | "
            f"{_pct(r['lines_flagged'], r['lines'])} | "
            f"{a['unflagged_precision']:.1%} (n = {a['unflagged_read']}) |"
        )
    print(
        "\n| Jeu | Station | Juste n.s. | Juste s. | Faux s. | Faux n.s. | Manquant s. "
        "| Manquant n.s. |"
    )
    print("| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for r in rows:
        c = r["all"]["categories"]
        keys = (
            "juste non signalé",
            "juste signalé",
            "faux signalé",
            "faux non signalé",
            "manquant signalé",
            "manquant non signalé",
        )
        print(
            f"| {r['set']} | {r['station']} | " + " | ".join(str(c.get(k, 0)) for k in keys) + " |"
        )
    motifs = sorted({m for r in rows for m in r["line_motifs"]})
    print(
        "\n| Jeu | Station | Fausses alertes (justes signalés) | "
        + " | ".join(f"Motif : {m}" for m in motifs)
        + " |"
    )
    print("| :--- | :--- | ---: |" + " ---: |" * len(motifs))
    for r in rows:
        print(
            f"| {r['set']} | {r['station']} | {r['all']['categories'].get('juste signalé', 0)} | "
            + " | ".join(str(r["line_motifs"].get(m, 0)) for m in motifs)
            + " |"
        )
    print("\n| Cause | " + " | ".join(f"{r['set']} {r['station']}" for r in rows) + " | Total |")
    print("| :--- |" + " ---: |" * (len(rows) + 1))
    causes = Counter(e["cause"] for r in rows for e in r["silent_errors"])
    for cause, total in causes.most_common():
        per = [sum(e["cause"] == cause for e in r["silent_errors"]) for r in rows]
        print(f"| {cause} | " + " | ".join(map(str, per)) + f" | {total} |")
    print(
        "\n| Contrôle candidat | Erreurs silencieuses fermées | Fausses alertes "
        "(faits justes signalés) | Pièces ajoutées à la relecture |"
    )
    print("| :--- | ---: | ---: | ---: |")
    totals = {
        name: [
            sum(r["controls"][name][k] for r in rows)
            for k in ("closed", "false_alarms", "new_pieces")
        ]
        for name in CONTROLS
    }
    for name, (closed, fa, newp) in sorted(totals.items(), key=lambda kv: -kv[1][0]):
        print(f"| {name} | {closed} | {fa} | {newp} |")
    print("\nOrdre glouton (gain marginal, tous jeux et stations) :\n")
    print(
        "| Rang | Contrôle | Erreurs silencieuses fermées en plus | Restantes | Fausses alertes |"
    )
    print("| ---: | :--- | ---: | ---: | ---: |")
    closed: set[tuple[int, int]] = set()
    remaining = sum(len(r["silent_errors"]) for r in rows)
    pool = set(CONTROLS)
    rank = 0
    while pool:
        gains = {
            name: {(n, k) for n, r in enumerate(rows) for k in r["controls"][name]["closed_ids"]}
            - closed
            for name in pool
        }
        best = max(sorted(gains), key=lambda name: len(gains[name]))
        if not gains[best]:
            break
        rank += 1
        closed |= gains[best]
        pool.remove(best)
        remaining -= len(gains[best])
        print(f"| {rank} | {best} | {len(gains[best])} | {remaining} | {totals[best][1]} |")
    left = Counter(
        e["cause"]
        for n, r in enumerate(rows)
        for k, e in enumerate(r["silent_errors"])
        if (n, k) not in closed
    )
    print(
        "\nRésidu après tous les contrôles, par cause : "
        + (", ".join(f"{c} {n}" for c, n in left.most_common()) or "aucun")
    )
    print("\nErreurs silencieuses (cote, nature, cause, lu, vrai) :")
    for r in rows:
        print(f"\n{r['set']} / {r['station']}")
        for e in r["silent_errors"]:
            print(
                f"- {e['piece']} {e['kind']} [{e['cause']}] lu : {e['read'] or '—'} ; "
                f"vrai : {e['true'] or '—'}"
            )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--set", dest="sets", action="append", choices=list(DATASETS))
    ap.add_argument("--json", type=Path, help="Écrit le détail complet en JSON")
    ap.add_argument("--markdown", action="store_true", help="Tableaux Markdown et liste détaillée")
    args = ap.parse_args()
    rows: list[dict] = []
    for jeu in args.sets or list(DATASETS):
        for model, station in STATIONS.items():
            row = measure(jeu, model)
            if row is None:
                console.print(
                    f"[yellow]{jeu} / {station} : lectures scellées "
                    "incomplètes, station ignorée[/yellow]"
                )
                continue
            rows.append(row)
    _print_rows(rows)
    ceiling_msgs = check_silent_ceilings(rows)
    for msg in ceiling_msgs:
        console.print(f"[red]Plafond dépassé : {msg}[/red]")
    if args.markdown:
        _markdown(rows)
    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"Détail écrit dans {args.json}")
    if ceiling_msgs:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
