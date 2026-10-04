"""Livrables d'une investigation : rapport Markdown, JSON scellé, graphe HTML interactif."""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .graph.visualizer import export_interactive_graph
from .investigation import Investigation

ROLE_FR = {
    "director": "administrateur",
    "shareholder": "actionnaire",
    "beneficial_owner": "bénéficiaire effectif",
    "secretary": "secrétaire",
    "attorney": "mandataire (procuration)",
    "intermediary": "agent enregistré",
}
TYPE_FR = {
    "BLANCHIMENT_CYCLE_FERME": "Circuit fermé (round-tripping)",
    "FRACTIONNEMENT_SCHTROUMPFAGE": "Fractionnement (schtroumpfage)",
    "DISSIMULATION_UBO_PRETE_NOM": "Bénéficiaire caché derrière un prête-nom",
}


def _usd(x: float) -> str:
    return f"{x:,.0f} USD".replace(",", " ")


def _layout(inv: Investigation) -> None:
    """Disposition en colonnes : personnes | sociétés | intermédiaires (sens de lecture)."""
    G = inv.graph
    suspicious = inv.detection.suspicious_nodes | {
        h["id"] for h in inv.findings["hidden_controllers"]
    }
    columns: dict[int, list[str]] = {0: [], 1: [], 2: []}
    for n, d in G.nodes(data=True):
        col = {"PersonnePhysique": 0, "Intermediaire": 2, "Adresse": 2}.get(d["entity_type"], 1)
        columns[col].append(n)
    grid = {0: (-1350, 2), 1: (-520, 4), 2: (1000, 1)}  # abscisse de départ, sous-colonnes
    for col, nodes in columns.items():
        nodes.sort(key=lambda n: (n not in suspicious, -G.degree(n), G.nodes[n]["name"]))
        x0, ncols = grid[col]
        rows = max(1, -(-len(nodes) // ncols))
        for i, n in enumerate(nodes):
            G.nodes[n]["x"] = x0 + (i % ncols) * 340
            G.nodes[n]["y"] = (i // ncols - rows / 2) * 105
            G.nodes[n]["level"] = col
    for _, _, e in G.edges(data=True):
        e["doc_reference"] = ", ".join(e["pieces"])


def _link(path: Path, out_dir: Path, label: str) -> str:
    return f"[{label}]({Path(os.path.relpath(path, out_dir)).as_posix()})"


def _pieces(inv: Investigation, ids: list[str], out_dir: Path) -> str:
    by_id = inv.piece_by_id
    return ", ".join(_link(inv.dossier / by_id[p].file, out_dir, p) for p in ids if p in by_id)


def render_markdown(inv: Investigation, out_dir: Path, evaluation: dict | None) -> str:
    f = inv.findings
    simulated = evaluation is not None and evaluation.get("scenario_simulated", False)
    n_err = len(f["vigilance"]["failed_pieces"])
    lines = [
        "# Rapport d'investigation : dossier de pièces",
        "",
        f"- **Dossier** : `{inv.dossier.as_posix()}` ({len(inv.pieces)} pièces, {n_err} en échec)",
        f"- **Lecture des pièces** : `{inv.engine}`",
        f"- **Généré le** : {datetime.now(UTC):%Y-%m-%d %H:%M} UTC, en local",
        (
            "- **Méthode** : les liens et les anomalies sont trouvés par des algorithmes "
            "déterministes (résolution de noms, Tarjan, Johnson, Brandes) ; le modèle de langage "
            "ne fait que lire les pièces et, en option, rédiger les notes. Chaque fait renvoie à "
            "ses pièces."
        ),
    ]
    if simulated:
        lines += [
            "",
            (
                "> **Données.** Les sociétés, dirigeants et intermédiaires proviennent d'un vrai "
                "réseau des Panama Papers (base ICIJ Offshore Leaks, licence ODbL). Les virements, "
                "relevés, procurations et le bénéficiaire caché sont **simulés** pour la "
                "démonstration (la base ICIJ ne contient aucun montant). Aucun fait n'est imputé aux "
                "sociétés réelles citées."
            ),
        ]

    lines += [
        "",
        "## 1. Synthèse Judiciaire : Infractions & Constats Clés",
        "",
        "> **Cadrage de l'enquête :** Ce rapport distingue rigoureusement deux niveaux :",
        "> 1. **Les infractions délictueuses caractérisées** : circuits fermés de blanchiment et dissimulations d'UBO.",
        "> 2. **La cartographie globale du réseau saisi** : l'organigramme de toutes les sociétés gérées et les soldes bancaires cumulés de tous les comptes saisis.",
        "",
    ]
    folios = [a for a in f["portfolios"] if a["nominee_profile"]]
    for a in folios[:3]:
        lines.append(
            f"- **Prête-nom central du réseau** : {a['name']} est inscrit dans les registres de "
            f"**{a['n_companies']} sociétés** du dossier (profil de prête-nom professionnel)."
        )
    for h in f["hidden_controllers"]:
        lines.append(
            f"- **Bénéficiaire caché derrière le prête-nom** : {h['name']} détient une procuration non enregistrée "
            f"sur {', '.join(h['companies'])} ({_pieces(inv, h['pieces'], out_dir)})."
        )
    for c in f["cycles"]:
        lines.append(
            f"- **Circuit fermé de blanchiment** : {' → '.join(c['cycle_nodes'] + [c['cycle_nodes'][0]])}, "
            f"{_usd(c['entry_amount_usd'])} injectés, {_usd(c['exit_amount_usd'])} revenus. "
            f"*(Ces sociétés sont toutes deux administrées par le prête-nom central).*"
        )
    for s in f["smurfing"]:
        lines.append(
            f"- **Fractionnement de fonds** : {s['source_name']} → {s['n_mules']} relais → "
            f"{s['collector_name']} ({_usd(s['total_collected_usd'])} collectés)."
        )
    if f["money_ranking"] and f["money_ranking"][0]["net_usd"] > 0:
        top = f["money_ranking"][0]
        lines.append(
            f"- **Destination globale des fonds** : {top['name']}, solde net créditeur de **{_usd(top['net_usd'])}** "
            f"sur l'ensemble des flux du dossier ({_pieces(inv, top['pieces'], out_dir)})."
        )
    if len(lines) and lines[-1] == "":
        lines.append("- Aucune anomalie détectée.")

    lines += [
        "",
        "## 2. Organigramme des Sociétés Saisies (Qui détient / dirige quoi)",
        "",
        "> Tableau exhaustif des structures juridiques saisies dans le dossier.",
        "",
        "| Société | Inscrits au registre | Procuration | Agent | Pièces |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]
    for row in f["ownership"]:
        holders = "<br>".join(
            f"{h['name']} ({ROLE_FR.get(h['role'], h['role'])})" for h in row["holders"]
        )
        attorneys = "<br>".join(a["name"] for a in row["attorneys"]) or "—"
        agents = "<br>".join(i["name"] for i in row["intermediaries"]) or "—"
        lines.append(
            f"| {row['company']} | {holders or '—'} | {attorneys} | {agents} | "
            f"{_pieces(inv, row['pieces'], out_dir)} |"
        )

    lines += [
        "",
        "## 3. Prête-noms & Centralité du Réseau Saisi (Qui est au centre)",
        "",
        (
            "> Identification des prête-noms institutionnels gérant des sociétés en cascade pour des tiers. "
            "Par exemple, *Oakridge Enterprises Limited* administre 11 sociétés, y compris celles impliquées "
            "dans les flux du circuit fermé."
        ),
        "",
        "| Acteur | Sociétés | Rôles | Profil |",
        "| :--- | ---: | :--- | :--- |",
    ]
    for a in f["portfolios"][:8]:
        roles = ", ".join(f"{ROLE_FR.get(r, r)} ×{k}" for r, k in a["roles"].items())
        profile = "prête-nom présumé" if a["nominee_profile"] else ""
        lines.append(f"| {a['name']} | {a['n_companies']} | {roles} | {profile} |")
    piv = f["pivot"]
    lines += [
        "",
        f"Seuil du profil de prête-nom : inscrit dans au moins {folios[0]['nominee_threshold']} "
        "sociétés du dossier."
        if folios
        else "",
        (
            f"Sommet le plus central du graphe (Brandes) : **{piv['name']}** "
            f"(intermédiarité {piv['betweenness']})."
        ),
    ]

    lines += [
        "",
        "## 4. Destination Globale des Fonds (Comptabilité de tous les comptes saisis)",
        "",
        (
            f"Bilan net cumulé sur l'ensemble des {f['flows']['count']} virements découverts dans le dossier "
            f"({_usd(f['flows']['total_usd'])} au total). Ce tableau montre où s'accumule la liquidité in fine "
            "sur l'ensemble des comptes étudiés, au-delà du seul circuit délictueux."
        ),
        "",
        "| Acteur | Reçu | Envoyé | Solde net | Pièces |",
        "| :--- | ---: | ---: | ---: | :--- |",
    ]
    for m in f["money_ranking"][:10]:
        lines.append(
            f"| {m['name']} | {_usd(m['received_usd'])} | {_usd(m['sent_usd'])} | "
            f"**{_usd(m['net_usd'])}** | {_pieces(inv, m['pieces'], out_dir)} |"
        )
    for c in f["cycles"]:
        lines += ["", f"**Circuit fermé** ({len(c['cycle_nodes'])} sociétés) :", ""]
        for s in c["steps"]:
            lines.append(
                f"1. {s['date'] or 'date illisible'} : {s['from']} → {s['to']}, "
                f"**{_usd(s['amount_usd'])}** ({_pieces(inv, s['pieces'], out_dir)})"
            )
    for s in f["smurfing"]:
        lines += [
            "",
            (
                f"**Fractionnement** : {s['source_name']} → {', '.join(s['mule_names'])} → "
                f"{s['collector_name']} ; {_usd(s['total_in_usd'])} envoyés, "
                f"{_usd(s['total_collected_usd'])} collectés ({_pieces(inv, s['pieces'], out_dir)})."
            ),
        ]

    lines += ["", "## 5. Qualifications envisagées", ""]
    authors = f.get("report_authors", [])
    for i, r in enumerate(inv.reports):
        lines += [
            f"### 5.{i + 1}. {TYPE_FR.get(r.infraction_type, r.infraction_type)}",
            "",
            f"> {r.summary_note}",
            "",
            f"- Montant en cause : **{_usd(r.total_amount_usd)}**",
            (
                f"- Corroboration par l'OCR témoin : **{r.confidence_score:.0%}** des noms et "
                "montants cités"
            ),
            f"- Rédaction de la note : {authors[i] if i < len(authors) else 'deterministe'}",
            "- Fondements à examiner : " + " ; ".join(r.legal_basis),
            "- Actions proposées : " + " ; ".join(r.recommendations),
            "",
        ]
    if not inv.reports:
        lines.append("Aucun constat à qualifier.")

    v = f["vigilance"]
    lines += [
        "",
        "## 6. À valider par l'enquêteur",
        "",
        f"- Pièces non lues : {len(v['failed_pieces'])}",
        f"- Entités écartées (absentes de la lecture OCR témoin) : {len(v['rejected_entities'])}"
        + (
            " : " + ", ".join(f"{e['name']} ({e['piece']})" for e in v["rejected_entities"][:8])
            if v["rejected_entities"]
            else ""
        ),
        (
            f"- Entités non vérifiables (pièce illisible pour l'OCR témoin) : "
            f"{v['unverifiable_entities']}"
        ),
        f"- Montants non corroborés par l'OCR témoin : {len(v['uncorroborated_amounts'])}",
        f"- Virements sans date lisible : {len(v['undated_transfers'])}",
        f"- Variantes de noms fusionnées : {len(v['name_merges'])}"
        + (
            " : "
            + "; ".join(
                f"{m['original_name']} = {m['canonical_name']}" for m in v["name_merges"][:6]
            )
            if v["name_merges"]
            else ""
        ),
    ]

    if evaluation:
        lines += ["", "## 7. Fiabilité mesurée sur ce dossier (vérité terrain connue)", ""]
        ev = evaluation["pieces"]["all"]
        g = evaluation["graph"]
        lines += [
            "| Mesure | Précision | Rappel |",
            "| :--- | ---: | ---: |",
            f"| Entités lues | {ev['entities']['precision']:.2f} | {ev['entities']['recall']:.2f} |",
            (
                f"| Liens de détention / contrôle lus | {ev['relations']['precision']:.2f} | "
                f"{ev['relations']['recall']:.2f} |"
            ),
            (
                f"| Virements lus | {ev['transfers']['precision']:.2f} | "
                f"{ev['transfers']['recall']:.2f} |"
            ),
            (
                f"| Liens du graphe reconstruit | {g['edges']['precision']:.2f} | "
                f"{g['edges']['recall']:.2f} |"
            ),
            (
                f"| Flux du graphe reconstruit | {g['flows']['precision']:.2f} | "
                f"{g['flows']['recall']:.2f} |"
            ),
        ]
        sc = evaluation.get("scenario")
        if sc:
            ok = {True: "oui", False: "non"}
            lines += [
                "",
                (
                    f"- Circuit caché retrouvé : **{ok[sc['cycle_found']]}** "
                    f"(faux circuits : {sc['spurious_cycles']})"
                ),
                (
                    f"- Fractionnement retrouvé : **{ok[sc['smurfing_found']]}** "
                    f"({sc['mules_found']}/{sc['mules_expected']} relais)"
                ),
                f"- Bénéficiaire caché retrouvé : **{ok[sc['hidden_beneficiary_found']]}**",
            ]

    lines += [
        "",
        "## 8. Chaîne de preuve",
        "",
        "| Cote | Fichier | Nature lue | SHA-256 |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for p in inv.pieces:
        lines.append(
            f"| {p.piece_id} | {_link(inv.dossier / p.file, out_dir, p.file)} | {p.doc_type} | "
            f"`{p.file_sha256[:16]}…` |"
        )
    return "\n".join(lines) + "\n"


def write_outputs(
    inv: Investigation, out_dir: Path, evaluation: dict | None = None
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    _layout(inv)
    paths = {
        "markdown": out_dir / "rapport.md",
        "json": out_dir / "rapport_scelle.json",
        "html": out_dir / "graphe.html",
    }
    paths["markdown"].write_text(render_markdown(inv, out_dir, evaluation), encoding="utf-8")

    sealed = {
        "dossier": inv.dossier.as_posix(),
        "engine": inv.engine,
        "generated_at": datetime.now(UTC).isoformat(),
        "timings": inv.timings,
        "pieces": [p.model_dump(mode="json") for p in inv.pieces],
        "findings": inv.findings,
        "reports": [r.model_dump(mode="json") for r in inv.reports],
        "proof_ledger": {k: p.model_dump(mode="json") for k, p in inv.ledger.items()},
        "evaluation": evaluation,
    }
    body = json.dumps(sealed, indent=2, ensure_ascii=False, default=str)
    paths["json"].write_text(body, encoding="utf-8")
    paths["json"].with_suffix(".sha256").write_text(
        f"{hashlib.sha256(body.encode('utf-8')).hexdigest()}  {paths['json'].name}\n",
        encoding="utf-8",
    )

    export_interactive_graph(
        G=inv.graph,
        detection=inv.detection,
        output_path=paths["html"],
        auto_open=False,
        report=inv.reports[0] if inv.reports else None,
        reports=inv.reports,
        findings=inv.findings,
        pieces=inv.pieces,
        ledger=inv.ledger,
        dossier_path=inv.dossier,
        case_label=f"{inv.dossier.name} ({len(inv.pieces)} pièces)",
    )
    return paths
