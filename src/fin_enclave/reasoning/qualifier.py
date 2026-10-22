"""
Qualification déterministe des constats d'un dossier en rapports AnomalyReport.

Séparation stricte :
- Les constats (cycles, fractionnement, bénéficiaire caché, prête-noms) proviennent
  exclusivement de l'analyse topologique déterministe du graphe et des pièces.
- Les notes de synthèse sont générées directement via des modèles de chaînes déterministes (f-strings)
  adossées à la table statique de bases légales (LEGAL_BASIS).
- Le score de confiance est déterministe : réconciliation arithmétique exacte des soldes
  pour les relevés, validité structurelle et temporelle pour les actes.
"""

import logging

from ..config import settings
from .models import AnomalyReport

logger = logging.getLogger("fin_enclave.reasoning")

LEGAL_BASIS = {
    "BLANCHIMENT_CYCLE_FERME": [
        "Art. 324-1 du Code pénal : blanchiment (dissimulation de l'origine des fonds)",
        "Art. L. 561-15 du Code monétaire et financier : déclaration de soupçon (TRACFIN)",
    ],
    "FRACTIONNEMENT_SCHTROUMPFAGE": [
        "Art. 324-1 du Code pénal : blanchiment (concours à une opération de dissimulation)",
        "Art. L. 561-15 du Code monétaire et financier : déclaration de soupçon (TRACFIN)",
    ],
    "DISSIMULATION_UBO_PRETE_NOM": [
        "Art. L. 561-2-2 du Code monétaire et financier : définition du bénéficiaire effectif",
        (
            "Recommandation 24 du GAFI : transparence des bénéficiaires effectifs des personnes "
            "morales"
        ),
        "Art. 324-1 du Code pénal : blanchiment, si l'origine des fonds est établie",
    ],
}


def _usd(x: float) -> str:
    return f"{x:,.0f} USD"


def compute_piece_confidence(piece) -> float:
    """
    Score de confiance métier déterministe :
    - Relevé bancaire : réconciliation arithmétique exacte des soldes et présence de flux.
    - Acte / autre : validité structurelle (entités non vides) et temporelle (période).
    """
    if getattr(piece, "error", ""):
        return 0.0
    doc_type = getattr(piece, "doc_type", "other")
    if doc_type == "bank_statement":
        # Réconciliation arithmétique exacte des soldes
        if getattr(piece, "balance_reconciled", True) is False:
            return 0.0
        if getattr(piece, "needs_review", False) and "soldes non réconciliés" in getattr(
            piece, "review_reason", ""
        ):
            return 0.0
        # Relevé vide sans flux extrait
        if not getattr(piece, "transfers", []):
            return 0.0
        start = getattr(piece, "period_start", None)
        end = getattr(piece, "period_end", None)
        if start and end and start > end:
            return 0.5
        return 1.0

    # Actes et gouvernance
    entities = getattr(piece, "entities", [])
    if not entities:
        return 0.0
    start = getattr(piece, "period_start", None)
    end = getattr(piece, "period_end", None)
    if start and end and start > end:
        return 0.5
    return 1.0


def corroboration(inv, pieces: list[str]) -> float:
    """Score de confiance métier déterministe agrégé sur les pièces d'un constat."""
    by_id = inv.piece_by_id
    scores = [compute_piece_confidence(by_id[p]) for p in pieces if p in by_id]
    return round(sum(scores) / len(scores), 3) if scores else 0.0


def _common_front(inv, names: list[str]) -> str:
    """Acteur inscrit au registre du plus grand nombre de sociétés du constat."""
    wanted = set(names)
    counts: dict[str, int] = {}
    for row in inv.findings["ownership"]:
        if row["company"] in wanted:
            for h in row["holders"]:
                counts[h["name"]] = counts.get(h["name"], 0) + 1
    return max(counts, key=lambda k: (counts[k], k)) if counts else inv.detection.pivot_name


def _cycle_report(inv, c: dict) -> AnomalyReport:
    steps = c["steps"]
    pieces = sorted({p for s in steps for p in s["pieces"]})
    names = c["cycle_nodes"]
    first, last = steps[0], steps[-1]
    dated = bool(first["date"] and last["date"])
    note = (
        f"Circuit fermé de {len(names)} sociétés : {' -> '.join(names + [names[0]])}. "
        f"{_usd(c['entry_amount_usd'])} sortent de {first['from']}"
        + (f" le {first['date']}" if dated else "")
        + f" et {_usd(c['exit_amount_usd'])} y reviennent"
        + (f" le {last['date']}" if dated else "")
        + f" (écart {c['leakage_pct']:.1f} %, au plus {c['max_step_deviation_pct']:.1f} % par "
        f"étape). Pièces : {', '.join(pieces)}."
    )
    return AnomalyReport(
        infraction_type="BLANCHIMENT_CYCLE_FERME",
        confidence_score=corroboration(inv, pieces),
        entities_involved=names,
        total_amount_usd=c["entry_amount_usd"],
        cycle_detected=names,
        pivot_intermediary=_common_front(inv, names),
        legal_basis=LEGAL_BASIS["BLANCHIMENT_CYCLE_FERME"],
        pieces=pieces,
        summary_note=note,
        recommendations=[
            "Confronter les pièces citées aux originaux scellés avant toute exploitation",
            "Requérir les relevés complets des comptes du circuit sur la période",
            "Si confirmé : déclaration de soupçon (Art. L. 561-15 CMF)",
        ],
    )


def _smurf_report(inv, s: dict) -> AnomalyReport:
    names = [s["source_name"], *s["mule_names"], s["collector_name"]]
    threshold = s.get("threshold_usd", settings.smurf_threshold_usd)
    note = (
        f"{s['source_name']} aurait fractionné {_usd(s['total_in_usd'])} en {s['n_mules']} "
        f"virements chacun sous le seuil de {_usd(threshold)} vers {s['n_mules']} relais "
        f"({', '.join(s['mule_names'])}), "
        f"qui reversent {_usd(s['total_collected_usd'])} à {s['collector_name']}"
        + (f" en {s['span_days']} jours" if s["span_days"] >= 0 else "")
        + (
            f" ; les fonds repartent ensuite vers {', '.join(s['downstream_names'])}"
            if s["downstream_names"]
            else ""
        )
        + f". Pièces : {', '.join(s['pieces'])}."
    )
    return AnomalyReport(
        infraction_type="FRACTIONNEMENT_SCHTROUMPFAGE",
        confidence_score=corroboration(inv, s["pieces"]),
        entities_involved=names,
        total_amount_usd=s["total_in_usd"],
        pivot_intermediary=s["collector_name"],
        legal_basis=LEGAL_BASIS["FRACTIONNEMENT_SCHTROUMPFAGE"],
        pieces=s["pieces"],
        summary_note=note,
        recommendations=[
            "Identifier les titulaires réels des comptes relais (KYC des banques teneuses)",
            "Rechercher d'autres éventails du même émetteur hors de la période",
            "Si confirmé : déclaration de soupçon (Art. L. 561-15 CMF)",
        ],
    )


def _controller_report(inv, h: dict) -> AnomalyReport:
    money = next((m for m in inv.findings["money_ranking"] if m["id"] == h["id"]), None)
    received = money["received_usd"] if money else 0.0
    pieces = sorted(set(h["pieces"]) | set(money["pieces"] if money else []))
    note = (
        f"Les registres désignent {', '.join(h['nominees'])} (profil de prête-nom présumé) pour "
        f"{', '.join(h['companies'])}. Une procuration non enregistrée donne à {h['name']} le "
        f"pouvoir d'opérer les comptes de ces sociétés"
        + (f" ; {h['name']} reçoit {_usd(received)} de flux attestés" if received else "")
        + f". Bénéficiaire effectif présumé, à confirmer. Pièces : {', '.join(pieces)}."
    )
    names = [h["name"], *h["companies"], *h["nominees"]]
    return AnomalyReport(
        infraction_type="DISSIMULATION_UBO_PRETE_NOM",
        confidence_score=corroboration(inv, pieces),
        entities_involved=names,
        total_amount_usd=received,
        pivot_intermediary=", ".join(h["nominees"]),
        legal_basis=LEGAL_BASIS["DISSIMULATION_UBO_PRETE_NOM"],
        pieces=pieces,
        summary_note=note,
        recommendations=[
            f"Confronter {h['name']} au registre des bénéficiaires effectifs des juridictions",
            "Requérir les mandats bancaires et les signatures des comptes des sociétés citées",
            "Rechercher les autres sociétés sur lesquelles ce mandataire détient une procuration",
        ],
    )


def _nominee_hub_report(inv, p: dict) -> AnomalyReport:
    pieces = sorted(
        {
            pie
            for row in inv.findings["ownership"]
            if row["company"] in p["companies"]
            for h in row["holders"]
            if h["name"] == p["name"]
            for pie in h.get("pieces", [])
        }
    )
    note = (
        f"{p['name']} est inscrit comme administrateur, secrétaire ou actionnaire de "
        f"{p.get('n_mandates', p['n_companies'])} sociétés du dossier (seuil du profil : "
        f"{p['nominee_threshold']}). Aucun bénéficiaire effectif n'est déclaré à son titre dans "
        f"les pièces lues. Ce profil pourrait correspondre à un prête-nom, hypothèse à vérifier "
        f"auprès du registre des bénéficiaires effectifs. "
        f"Pièces : {', '.join(pieces[:6])}."
    )
    names = [p["name"], *p["companies"]]
    return AnomalyReport(
        infraction_type="DISSIMULATION_UBO_PRETE_NOM",
        confidence_score=corroboration(inv, pieces),
        entities_involved=names,
        total_amount_usd=0.0,
        pivot_intermediary=p["name"],
        legal_basis=LEGAL_BASIS["DISSIMULATION_UBO_PRETE_NOM"],
        pieces=pieces,
        summary_note=note,
        recommendations=[
            (
                "Requérir le registre des bénéficiaires effectifs (RBE) des sociétés que le "
                "graphe rattache à ce profil"
            ),
            "Confronter la structure aux déclarations fiscales et bancaires de l'administrateur",
            "Vérifier l'absence de convention de prête-nom occulte (nominee agreement)",
        ],
    )


def qualify_findings(inv) -> list[AnomalyReport]:
    """
    Qualification juridique 100 % déterministe adossée aux textes légaux (CMF, Code pénal).

    Génère un rapport d'anomalie par constat (circuit fermé, fractionnement,
    dissimulation de bénéficiaire effectif ou prête-nom présumé).
    """
    reports: list[AnomalyReport] = [_cycle_report(inv, c) for c in inv.findings["cycles"]]
    reports += [_smurf_report(inv, s) for s in inv.findings["smurfing"]]
    if inv.findings["hidden_controllers"]:
        reports += [_controller_report(inv, h) for h in inv.findings["hidden_controllers"]]
    else:
        nominees = [p for p in inv.findings.get("portfolios", []) if p.get("nominee_profile")]
        if nominees:
            reports += [_nominee_hub_report(inv, nominees[0])]

    for _ in reports:
        inv.findings.setdefault("report_authors", []).append("deterministe")

    return reports
