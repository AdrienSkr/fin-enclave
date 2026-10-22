"""Livrables d'une investigation : rapport Markdown, JSON scellé, graphe HTML interactif."""

import os
from datetime import UTC, datetime
from pathlib import Path

from .analyst import build_analyst_view
from .config import settings
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


def analyst_view(inv: Investigation) -> dict:
    return build_analyst_view(inv.graph, inv.findings, inv.pieces, inv.detection)


def _findings_dict(inv: Investigation, view: dict) -> dict:
    """Constats sérialisables (le dataclass n'est pas JSON) enrichis des fonctions d'analyste."""
    base = inv.findings.to_dict() if hasattr(inv.findings, "to_dict") else dict(inv.findings)
    return {**base, "analyst": view}


def _link(path: Path, out_dir: Path, label: str) -> str:
    return f"[{label}]({Path(os.path.relpath(path, out_dir)).as_posix()})"


def _pieces(inv: Investigation, ids: list[str], out_dir: Path) -> str:
    by_id = inv.piece_by_id
    return ", ".join(_link(inv.dossier / by_id[p].file, out_dir, p) for p in ids if p in by_id)


def _shared_front(f, company_names: list[str]) -> str | None:
    """Acteur au profil de prête-nom inscrit dans TOUTES les sociétés citées (preuve du graphe)."""
    wanted = set(company_names)
    for a in f["portfolios"]:
        if a["nominee_profile"] and wanted <= set(a["companies"]):
            return a["name"]
    return None


def _evaluation_lines(evaluation: dict) -> list[str]:
    ev = evaluation["pieces"]["all"]
    g = evaluation["graph"]
    lines = [
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
    return lines


def _limit_warnings(f) -> list[str]:
    """Plafonds du détecteur atteints : l'absence de constat n'est alors pas une preuve."""
    limits = f.get("limits", {}) or {}
    out = []
    if limits.get("cycles_truncated"):
        out.append(
            "l'énumération des circuits est tronquée (plafond atteint) : l'absence de circuit "
            "dans ce rapport ne prouve rien."
        )
    if limits.get("smurfing_skipped"):
        out.append(
            "la recherche de fractionnement a été sautée (graphe de flux trop grand) : aucun "
            "fractionnement n'a été testé."
        )
    return out


def _flagged_piece_ids(inv: Investigation) -> set[str]:
    """Pièces à relire (motif pièce) ou portant au moins une ligne signalée."""
    return {
        p.piece_id for p in inv.pieces if p.needs_review or any(t.review_flags for t in p.transfers)
    }


def _line_review_rows(inv: Investigation) -> list[tuple[str, int, str]]:
    """(cote, n° de ligne 1-based, motifs) pour chaque virement signalé."""
    rows: list[tuple[str, int, str]] = []
    for p in inv.pieces:
        for i, t in enumerate(p.transfers, 1):
            if t.review_flags:
                rows.append((p.piece_id, i, ", ".join(t.review_flags)))
    return rows


def _review_lines(inv: Investigation) -> list[str]:
    rows = [p for p in inv.pieces if p.needs_review]
    line_rows = _line_review_rows(inv)
    if not rows and not line_rows:
        return []
    out: list[str] = []
    if rows:
        out.append(
            f"- **À relire** : {len(rows)} pièce(s) dont la lecture est suspecte ; les mouvements "
            "qui en manquent peuvent fausser les constats et les réquisitions : "
            + " ; ".join(f"{p.piece_id} ({p.review_reason})" for p in rows)
        )
    if line_rows:
        out += [
            "",
            "### Lignes à relire",
            "",
            "| Cote | Ligne | Motif |",
            "| :--- | ---: | :--- |",
        ]
        for cote, num, motif in line_rows:
            out.append(f"| {cote} | {num} | {motif} |")
    return out


def _confirm_suffix(inv: Investigation, piece_ids: list[str] | set[str]) -> str:
    flagged = _flagged_piece_ids(inv)
    hit = sorted(flagged & set(piece_ids))
    if not hit:
        return ""
    return f" *(à confirmer : {', '.join(hit)})*"


def _summary_lines(inv: Investigation, out_dir: Path) -> list[str]:
    f = inv.findings
    lines: list[str] = []
    anomalies = 0
    for a in [a for a in f["portfolios"] if a["nominee_profile"]][:3]:
        anomalies += 1
        lines.append(
            f"- **Profil de prête-nom présumé** : {a['name']} est inscrit au registre de "
            f"**{a.get('n_mandates', a['n_companies'])} sociétés** du dossier au titre de "
            "mandats ; hypothèse à vérifier."
        )
    for h in f["hidden_controllers"]:
        anomalies += 1
        lines.append(
            f"- **Bénéficiaire caché possible** : {h['name']} détient une procuration non "
            f"enregistrée sur {', '.join(h['companies'])} ({_pieces(inv, h['pieces'], out_dir)})."
            + _confirm_suffix(inv, h.get("pieces", []))
        )
    for c in f["cycles"]:
        anomalies += 1
        ring = " → ".join(c["cycle_nodes"] + [c["cycle_nodes"][0]])
        cotes = {p for step in c.get("steps", []) for p in step.get("pieces", [])} or set(
            c.get("pieces", [])
        )
        line = (
            f"- **Circuit fermé de flux** : {ring}, {_usd(c['entry_amount_usd'])} injectés, "
            f"{_usd(c['exit_amount_usd'])} revenus."
        )
        front = _shared_front(f, c["cycle_nodes"])
        if front:
            line += (
                f" *Ces sociétés sont toutes inscrites au registre au nom de {front} "
                "(profil de prête-nom présumé).*"
            )
        line += _confirm_suffix(inv, cotes)
        lines.append(line)
    for s in f["smurfing"]:
        anomalies += 1
        lines.append(
            f"- **Fractionnement possible** : {s['source_name']} → {s['n_mules']} relais → "
            f"{s['collector_name']} ({_usd(s['total_collected_usd'])} collectés, virements "
            f"sous {_usd(s.get('threshold_usd', settings.smurf_threshold_usd))})."
            + _confirm_suffix(inv, s.get("pieces", []))
        )
    if not anomalies:
        lines.append("- Aucune anomalie détectée sur les pièces lues.")
    lines += [f"- **Limite de l'analyse** : {w}" for w in _limit_warnings(f)]
    n_review = sum(p.needs_review for p in inv.pieces)
    if n_review:
        lines.append(
            f"- **Lecture à relire** : {n_review} pièce(s) à relire avant de conclure (section 4)."
        )
    if f["money_ranking"] and f["money_ranking"][0]["net_usd"] > 0:
        top = f["money_ranking"][0]
        lines.append(
            f"- **Solde net le plus élevé** : {top['name']}, **{_usd(top['net_usd'])}** sur "
            f"l'ensemble des flux du dossier ({_pieces(inv, top['pieces'], out_dir)})."
        )
    return lines


def _timeline_lines(inv: Investigation, view: dict, out_dir: Path) -> list[str]:
    rows = view["timeline"]
    if not rows:
        return []
    lines = [
        "### Chronologie des flux des constats",
        "",
        "| Date | Émetteur | Bénéficiaire | Montant | Constat | Cotes |",
        "| :--- | :--- | :--- | ---: | :--- | :--- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['date'] or 'date illisible'} | {r['from']} | {r['to']} | "
            f"{_usd(r['amount_usd'])} | {r['finding']} | {_pieces(inv, r['pieces'], out_dir)} |"
        )
    return [*lines, ""]


def _score_cell(row: dict) -> str:
    b = row["breakdown"]
    return " + ".join(f"{k} {v:g}" for k, v in b.items() if v) or "0"


def _priority_lines(view: dict) -> list[str]:
    p = view["priorities"]
    w = view["weights"]
    lines = [
        "",
        "### Priorisation des entités et des constats",
        "",
        (
            "Score explicable sur 100 : montant en jeu dans les constats "
            f"(max {w['amount']:g}), typologies distinctes ({w['typologies']:g}), centralité "
            f"({w['centrality']:g}), nombre de constats ({w['findings']:g}). Une société sans "
            "constat ne peut dépasser le seul poids de la centralité."
        ),
        *(
            []
            if view.get("centrality_available", True)
            else [
                "",
                "*Centralité non calculée sur ce dossier : son poids vaut 0 dans les scores.*",
            ]
        ),
        "",
        "| Rang | Entité | Score | Décomposition | Typologies |",
        "| ---: | :--- | ---: | :--- | :--- |",
    ]
    for i, r in enumerate(p["entities"][:10], 1):
        lines.append(
            f"| {i} | {r['name']} | **{r['score']:g}** | {_score_cell(r)} | "
            f"{', '.join(r['typologies']) or '—'} |"
        )
    if p["findings"]:
        lines += [
            "",
            "| Rang | Constat | Score | Décomposition | Montant |",
            "| ---: | :--- | ---: | :--- | ---: |",
        ]
        for r in p["findings"]:
            lines.append(
                f"| {r['rank']} | {r['finding']} | **{r['score']:g}** | {_score_cell(r)} | "
                f"{_usd(r['amount_usd'])} |"
            )
    return lines


def _control_lines(inv: Investigation, view: dict, out_dir: Path) -> list[str]:
    rows = view["control_chains"]
    if not rows:
        return []
    lines = [
        "",
        "### Chaîne de contrôle jusqu'à la personne physique",
        "",
        "| Société d'un constat | Chaîne de détention | Personne physique | Pièces |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for r in rows:
        if not r["chains"]:
            lines.append(f"| {r['company']} | — | *{r['note']}* | — |")
            continue
        for c in r["chains"]:
            ubo = c["ubo"] or f"*non atteinte ({r['note'] or 'chaîne interrompue'})*"
            lines.append(
                f"| {r['company']} | {' → '.join(c['path'])} | {ubo} | "
                f"{_pieces(inv, c['pieces'], out_dir)} |"
            )
    return lines


def _requisition_lines(inv: Investigation, view: dict, out_dir: Path) -> list[str]:
    rows = view["requisitions"]
    lines = ["", "### Réquisitions complémentaires à envisager", ""]
    if not rows:
        return [*lines, "Tout compte cité dans un flux a un relevé couvrant ses mouvements."]
    lines += [
        (
            "| Compte (titulaire) | Banque | Période à requérir | Motif | Confirmation | "
            "Pièces citant le compte |"
        ),
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for r in rows[:15]:
        period = " au ".join(dict.fromkeys(r["period"])) or "non datée"
        flag = " (constat)" if r["in_finding"] else ""
        iban = f" ({r['iban']})" if r.get("iban") else ""
        confirm = f"à confirmer ({r['confirm_reason']})" if r.get("to_confirm") else "—"
        lines.append(
            f"| {r['account']}{iban}{flag} | {r['bank']} | {period} | {r['reason']} | "
            f"{confirm} | {_pieces(inv, r['cited_by'], out_dir)} |"
        )
    if len(rows) > 15:
        lines.append(f"\n{len(rows) - 15} autres comptes figurent dans le JSON scellé.")
    return lines


def _findings_lines(inv: Investigation, out_dir: Path) -> list[str]:
    f = inv.findings
    lines: list[str] = []
    authors = f.get("report_authors", [])
    for i, r in enumerate(inv.reports):
        cotes = sorted(r.pieces)
        confirm = _confirm_suffix(inv, cotes)
        title = TYPE_FR.get(r.infraction_type, r.infraction_type)
        if confirm:
            title += " *(à confirmer)*"
        lines += [
            f"### 2.{i + 1}. {title}",
            "",
            f"> {r.summary_note}",
            "",
            f"- Score de confiance : **{r.confidence_score:.0%}**",
            f"- Rédaction de la note : {authors[i] if i < len(authors) else 'deterministe'}",
            "- Fondements à examiner : " + " ; ".join(r.legal_basis),
            "- Actions proposées : " + " ; ".join(r.recommendations),
            "- Cotes : " + ", ".join(cotes) + (confirm.replace("*", "") if confirm else ""),
            "",
        ]
    if not inv.reports:
        lines += ["Aucun constat à qualifier.", ""]
    for s in f["smurfing"]:
        lines += [
            (
                f"**Fractionnement** : {s['source_name']} → {', '.join(s['mule_names'])} → "
                f"{s['collector_name']} ; {_usd(s['total_in_usd'])} envoyés, "
                f"{_usd(s['total_collected_usd'])} collectés ({_pieces(inv, s['pieces'], out_dir)})."
            ),
            "",
        ]
    return lines


def _entities_lines(inv: Investigation, out_dir: Path) -> list[str]:
    f = inv.findings
    lines = [
        "### 3.1. Qui détient / dirige quoi",
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
        "### 3.2. Portefeuilles de mandats",
        "",
        "| Acteur | Sociétés | Rôles | Profil |",
        "| :--- | ---: | :--- | :--- |",
    ]
    for a in f["portfolios"][:8]:
        roles = ", ".join(f"{ROLE_FR.get(r, r)} ×{k}" for r, k in a["roles"].items())
        if a["nominee_profile"]:
            profile = "prête-nom présumé (à vérifier)"
        elif a.get("declared_ubo"):
            profile = "bénéficiaire effectif déclaré"
        else:
            profile = ""
        lines.append(f"| {a['name']} | {a['n_companies']} | {roles} | {profile} |")
    piv = f["pivot"]
    folios = [a for a in f["portfolios"] if a["nominee_profile"]]
    if folios:
        lines += [
            "",
            (
                f"Seuil du profil de prête-nom : au moins {folios[0]['nominee_threshold']} "
                "sociétés au titre de mandats (les rôles de bénéficiaire effectif déclaré "
                "ne comptent pas)."
            ),
        ]
    if piv.get("name"):
        lines += [
            "",
            (
                f"Sommet le plus central du graphe (Brandes) : **{piv['name']}** "
                f"(intermédiarité {piv['betweenness']})."
            ),
        ]
    lines += [
        "",
        "### 3.3. Destination des fonds",
        "",
        (
            f"Bilan net cumulé sur {f['flows']['count']} virements "
            f"({_usd(f['flows']['total_usd'])} au total)."
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
    return lines


def _vigilance_lines(f) -> list[str]:
    v = f["vigilance"]
    return [
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


def _annex_lines(inv: Investigation, out_dir: Path, evaluation: dict | None) -> list[str]:
    f = inv.findings
    p = inv.detection.params
    lines: list[str] = []
    if evaluation:
        lines += [
            "### 5.1. Fiabilité mesurée sur ce dossier (vérité terrain connue)",
            "",
            *_evaluation_lines(evaluation),
            "",
        ]
    lines += [
        "### 5.2. Chaîne de preuve",
        "",
        "| Cote | Fichier | Nature lue | SHA-256 |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for piece in inv.pieces:
        lines.append(
            f"| {piece.piece_id} | {_link(inv.dossier / piece.file, out_dir, piece.file)} | "
            f"{piece.doc_type} | `{piece.file_sha256[:16]}…` |"
        )
    thr = p.get("smurf_threshold_usd", settings.smurf_threshold_usd)
    lines += [
        "",
        "### 5.3. Paramètres de détection",
        "",
        f"- Longueur des cycles : {p.get('min_cycle_len', '?')} à {p.get('max_cycle_len', '?')}",
        (
            "- Tolérance de conservation du montant par étape : "
            f"{float(p.get('step_tolerance', 0)) * 100:.0f} %"
        ),
        (
            f"- Seuil de fractionnement : {_usd(thr)} par virement ; au moins "
            f"{p.get('smurf_min_mules', '?')} relais en {p.get('smurf_window_days', '?')} jours"
        ),
        (
            "- Cycles écartés (conservation ou chronologie non respectées) : "
            f"{inv.detection.rejected_cycles_count}"
        ),
        *[f"- **Limite atteinte** : {w}" for w in _limit_warnings(f)],
        "",
        "### 5.4. Métriques d'exécution et télémétrie",
        "",
        f"- **Temps d'extraction / lecture** : {inv.timings.get('extraction_s', 0.0)} s",
        (
            "- **Temps de construction & détection graphe** : "
            f"{inv.timings.get('graph_and_detection_s', 0.0)} s"
        ),
        f"- **Temps de qualification juridique** : {inv.timings.get('qualification_s', 0.0)} s",
        f"- **Durée totale d'investigation** : {inv.timings.get('total_investigation_s', 0.0)} s",
    ]
    telemetry = f.get("telemetry", {})
    if telemetry:
        lines += [
            (
                f"- **Détails de l'analyse déterministe** : liaison "
                f"`{telemetry.get('link_ms', 0)} ms`, détection topologique "
                f"`{telemetry.get('detection_ms', 0)} ms`, constats "
                f"`{telemetry.get('findings_ms', 0)} ms`"
            ),
            f"- **Pic de mémoire vive (analyse)** : `{telemetry.get('peak_memory_mb', 0)} Mo`",
        ]
    return lines


def render_markdown(inv: Investigation, out_dir: Path, evaluation: dict | None) -> str:
    """Rapport magistrat : synthèse, constats avec cotes, entités, à valider, annexes."""
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
                "démonstration (la base ICIJ ne contient aucun montant). Aucun fait n'est imputé "
                "aux sociétés réelles citées."
            ),
        ]
    lines += ["", "## 1. Synthèse", "", *_summary_lines(inv, out_dir)]
    view = analyst_view(inv)
    lines += ["", "## 2. Constats et qualifications envisagées", ""]
    lines += _findings_lines(inv, out_dir)
    lines += _timeline_lines(inv, view, out_dir)
    lines += ["## 3. Entités et flux", "", *_entities_lines(inv, out_dir)]
    lines += _control_lines(inv, view, out_dir) + _priority_lines(view)
    lines += ["", "## 4. À valider par l'enquêteur", "", "### Contrôles de lecture", ""]
    lines += [*_vigilance_lines(f), *_review_lines(inv), *_requisition_lines(inv, view, out_dir)]
    lines += ["", "## 5. Annexes techniques", "", *_annex_lines(inv, out_dir, evaluation)]
    return "\n".join(lines) + "\n"


def write_outputs(
    inv: Investigation, out_dir: Path, evaluation: dict | None = None
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    _layout(inv)
    paths = {
        "markdown": out_dir / "rapport.md",
        "html": out_dir / "graphe.html",
    }
    paths["markdown"].write_text(render_markdown(inv, out_dir, evaluation), encoding="utf-8")
    findings = _findings_dict(inv, analyst_view(inv))

    export_interactive_graph(
        G=inv.graph,
        detection=inv.detection,
        output_path=paths["html"],
        auto_open=False,
        report=inv.reports[0] if inv.reports else None,
        reports=inv.reports,
        findings=findings,
        pieces=inv.pieces,
        dossier_path=inv.dossier,
        case_label=f"{inv.dossier.name} ({len(inv.pieces)} pièces)",
    )
    return paths
