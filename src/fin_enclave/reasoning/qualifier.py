"""
Qualification des constats d'un dossier en rapports `AnomalyReport`.

Séparation stricte :
- les FAITS (entités, montants, circuit, pièces, chaîne de preuve) viennent uniquement des
  détecteurs déterministes et du registre de preuves ; ils ne sont jamais demandés au LLM ;
- le LLM (vLLM local sur le GX10, OpenRouter en développement) ne rédige que la note de synthèse,
  à partir des faits transmis. Une note qui cite un montant absent des faits est rejetée et
  remplacée par la note déterministe. Sans LLM, la note déterministe est utilisée directement.

Le score de confiance n'est pas une opinion du modèle : c'est le taux de corroboration des
éléments de preuve (noms et montants) par la lecture OCR témoin indépendante.
"""

import hashlib
import json
import logging
import re
from pathlib import Path

from openai import OpenAI, OpenAIError

from ..config import settings
from ..schemas import AnomalyReport, ProofPoint

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

NARRATION_PROMPT = """Tu rédiges la note de synthèse d'un constat d'investigation financière,
destinée à un magistrat. Tu reçois des FAITS établis par des algorithmes déterministes à partir
de pièces scellées. Règles :
- n'utilise que les faits fournis ; n'ajoute aucune entité, aucun montant, aucune date ;
- recopie les montants exactement au format fourni (ex. 2,431,500 USD) ;
- cite les cotes des pièces (PIECE-xxxx) qui fondent chaque fait ;
- 4 phrases au plus, ton factuel, conditionnel pour toute qualification pénale.
Réponds par un objet JSON : {"summary_note": "..."}"""


def _usd(x: float) -> str:
    return f"{x:,.0f} USD"


def _custody(inv, pieces: list[str], tx_ids: list[str] | None = None) -> list[ProofPoint]:
    """Preuves : les mouvements cités + un scellé par pièce citée (sans doublon)."""
    points: list[ProofPoint] = [inv.ledger[t] for t in (tx_ids or []) if t in inv.ledger]
    seen = {p.cote_judiciaire for p in points}
    for pid in pieces:
        if pid in seen:
            continue
        seal = inv.ledger.get(f"{pid}/piece")
        if seal is not None:
            points.append(seal)
            seen.add(pid)
    return points


def corroboration(inv, pieces: list[str], names: list[str], tx_ids: list[str]) -> float:
    """Part des éléments de preuve (noms cités, montants) confirmés par l'OCR témoin."""
    by_id = inv.piece_by_id
    checks: list[bool] = []
    wanted = {n.upper() for n in names}
    for pid in pieces:
        for e in by_id[pid].entities:
            if inv.resolver.resolve_name(e.name).upper() in wanted or e.name.upper() in wanted:
                checks.append(e.grounded is True)
    for _, _, e in inv.graph.edges(data=True):
        for t in e.get("transfers", []):
            if t["tx_id"] in tx_ids:
                checks.append(t["amount_corroborated"] is True)
    return round(sum(checks) / len(checks), 3) if checks else 0.0


def _cycle_report(inv, c: dict) -> tuple[AnomalyReport, dict]:
    steps = c["steps"]
    tx_ids = [t["tx_id"] for s in steps for t in s["transfers"]]
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
    report = AnomalyReport(
        infraction_type="BLANCHIMENT_CYCLE_FERME",
        confidence_score=corroboration(inv, pieces, names, tx_ids),
        entities_involved=names,
        total_amount_usd=c["entry_amount_usd"],
        cycle_detected=names,
        pivot_intermediary=_common_front(inv, names),
        legal_basis=LEGAL_BASIS["BLANCHIMENT_CYCLE_FERME"],
        chain_of_custody=_custody(inv, pieces, tx_ids),
        summary_note=note,
        recommendations=[
            "Confronter les pièces citées aux originaux scellés avant toute exploitation",
            "Requérir les relevés complets des comptes du circuit sur la période",
            "Si confirmé : déclaration de soupçon (Art. L. 561-15 CMF)",
        ],
    )
    facts = {"type": "circuit", "steps": steps, "pieces": pieces, "note": note}
    return report, facts


def _smurf_report(inv, s: dict) -> tuple[AnomalyReport, dict]:
    tx_ids = sorted(s["tx_ids"])
    names = [s["source_name"], *s["mule_names"], s["collector_name"]]
    note = (
        f"{s['source_name']} fractionne {_usd(s['total_in_usd'])} en {s['n_mules']} virements "
        f"sous le seuil de 10,000 USD vers {s['n_mules']} relais ({', '.join(s['mule_names'])}), "
        f"qui reversent {_usd(s['total_collected_usd'])} à {s['collector_name']}"
        + (f" en {s['span_days']} jours" if s["span_days"] >= 0 else "")
        + (
            f" ; les fonds repartent ensuite vers {', '.join(s['downstream_names'])}"
            if s["downstream_names"]
            else ""
        )
        + f". Pièces : {', '.join(s['pieces'])}."
    )
    report = AnomalyReport(
        infraction_type="FRACTIONNEMENT_SCHTROUMPFAGE",
        confidence_score=corroboration(inv, s["pieces"], names, tx_ids),
        entities_involved=names,
        total_amount_usd=s["total_in_usd"],
        pivot_intermediary=s["collector_name"],
        legal_basis=LEGAL_BASIS["FRACTIONNEMENT_SCHTROUMPFAGE"],
        chain_of_custody=_custody(inv, s["pieces"], tx_ids),
        summary_note=note,
        recommendations=[
            "Identifier les titulaires réels des comptes relais (KYC des banques teneuses)",
            "Rechercher d'autres éventails du même émetteur hors de la période",
            "Si confirmé : déclaration de soupçon (Art. L. 561-15 CMF)",
        ],
    )
    return report, {"type": "fractionnement", "finding": s, "note": note}


def _controller_report(inv, h: dict) -> tuple[AnomalyReport, dict]:
    money = next((m for m in inv.findings["money_ranking"] if m["id"] == h["id"]), None)
    received = money["received_usd"] if money else 0.0
    pieces = sorted(set(h["pieces"]) | set(money["pieces"] if money else []))
    tx_ids = [
        t["tx_id"]
        for u, v, e in inv.graph.edges(data=True)
        if v == h["id"]
        for t in e.get("transfers", [])
    ]
    note = (
        f"Les registres désignent {', '.join(h['nominees'])} (profil de prête-nom) pour "
        f"{', '.join(h['companies'])}. Une procuration non enregistrée donne à {h['name']} le "
        f"pouvoir d'opérer les comptes de ces sociétés"
        + (f" ; {h['name']} reçoit {_usd(received)} de flux attestés" if received else "")
        + f". Bénéficiaire effectif présumé, à confirmer. Pièces : {', '.join(pieces)}."
    )
    names = [h["name"], *h["companies"], *h["nominees"]]
    report = AnomalyReport(
        infraction_type="DISSIMULATION_UBO_PRETE_NOM",
        confidence_score=corroboration(inv, pieces, names, tx_ids),
        entities_involved=names,
        total_amount_usd=received,
        pivot_intermediary=", ".join(h["nominees"]),
        legal_basis=LEGAL_BASIS["DISSIMULATION_UBO_PRETE_NOM"],
        chain_of_custody=_custody(inv, pieces, tx_ids),
        summary_note=note,
        recommendations=[
            f"Confronter {h['name']} au registre des bénéficiaires effectifs des juridictions",
            "Requérir les mandats bancaires et les signatures des comptes des sociétés citées",
            "Rechercher les autres sociétés sur lesquelles ce mandataire détient une procuration",
        ],
    )
    return report, {"type": "beneficiaire_cache", "finding": h, "note": note}


def _common_front(inv, names: list[str]) -> str:
    """Acteur inscrit au registre du plus grand nombre de sociétés du constat."""
    wanted = set(names)
    counts: dict[str, int] = {}
    for row in inv.findings["ownership"]:
        if row["company"] in wanted:
            for h in row["holders"]:
                counts[h["name"]] = counts.get(h["name"], 0) + 1
    return max(counts, key=lambda k: (counts[k], k)) if counts else inv.detection.pivot_name


def _allowed_numbers(facts: dict, report: AnomalyReport) -> set[str]:
    text = json.dumps(facts, ensure_ascii=False, default=str) + report.summary_note
    return {re.sub(r"[^\d]", "", m) for m in re.findall(r"\d[\d,.\s]*\d|\d", text)}


def _narration_is_faithful(note: str, allowed: set[str]) -> bool:
    """Chaque nombre de 4 chiffres ou plus cité par le LLM doit exister dans les faits."""
    for m in re.findall(r"\d[\d,.\u202f\u00a0 ]*\d", note):
        digits = re.sub(r"[^\d]", "", m)
        if (
            len(digits) >= 4
            and digits not in allowed
            and digits.rstrip("0") not in {a.rstrip("0") for a in allowed}
        ):
            return False
    return True


def _llm_client() -> OpenAI | None:
    if settings.llm_backend == "mock":
        return None
    key = settings.get_effective_api_key()
    if settings.llm_backend != "local_gx10" and (not key or key == "EMPTY" or "your_" in key):
        return None
    return OpenAI(base_url=settings.get_effective_base_url(), api_key=key, timeout=60)


def _llm_note(
    client: OpenAI | None, model: str, payload: dict, cache_dir: Path | None
) -> str | None:
    """Note brute du LLM, scellée en cache (modèle + prompt + faits) pour un rejeu hors ligne."""
    user = json.dumps(payload, ensure_ascii=False)
    key = hashlib.sha256(f"{model}\n{NARRATION_PROMPT}\n{user}".encode()).hexdigest()[:24]
    cache = Path(cache_dir) / f"note_{key}.json" if cache_dir else None
    if cache and cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))["summary_note"]
    if client is None:
        return None
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": NARRATION_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content or ""
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        note = str(json.loads(match.group(0) if match else raw).get("summary_note", "")).strip()
    except (OpenAIError, json.JSONDecodeError, ValueError, AttributeError) as exc:
        logger.warning("Rédaction LLM indisponible (%s) : note déterministe conservée", exc)
        return None
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(
            json.dumps({"model": model, "summary_note": note}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return note


def _narrate(
    client: OpenAI | None,
    model: str,
    report: AnomalyReport,
    facts: dict,
    cache_dir: Path | None = None,
) -> tuple[str, str]:
    """Note rédigée par le LLM si elle est fidèle aux faits ; sinon la note déterministe."""
    payload = {
        "qualification_envisagee": report.infraction_type,
        "montant_usd": f"{report.total_amount_usd:,.0f}",
        "entites": report.entities_involved,
        "constat_deterministe": report.summary_note,
    }
    note = _llm_note(client, model, payload, cache_dir)
    if note is None:
        return report.summary_note, "deterministe"
    cited = set(re.findall(r"PIECE-\d{4}", note))
    if (
        not note
        or not _narration_is_faithful(note, _allowed_numbers(facts, report))
        or not cited <= set(re.findall(r"PIECE-\d{4}", report.summary_note))
    ):
        logger.warning("Note LLM rejetée (montant ou pièce hors des faits) : note déterministe")
        return report.summary_note, "deterministe (note LLM rejetée)"
    return note, f"llm:{model}"


def _nominee_hub_report(inv, p: dict) -> tuple[AnomalyReport, dict]:
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
        f"{p['name']} est inscrit comme administrateur ou actionnaire de {p['n_companies']} sociétés "
        f"du dossier (seuil prête-nom : {p['nominee_threshold']}). "
        f"Absence de bénéficiaire effectif personne physique identifié pour ces entités. "
        f"Profil de prête-nom institutionnel présumé aux fins de dissimulation d'avoirs. "
        f"Pièces : {', '.join(pieces[:6])}."
    )
    names = [p["name"], *p["companies"]]
    report = AnomalyReport(
        infraction_type="DISSIMULATION_UBO_PRETE_NOM",
        confidence_score=corroboration(inv, pieces, names, []),
        entities_involved=names,
        total_amount_usd=0.0,
        pivot_intermediary=p["name"],
        legal_basis=LEGAL_BASIS["DISSIMULATION_UBO_PRETE_NOM"],
        chain_of_custody=_custody(inv, pieces),
        summary_note=note,
        recommendations=[
            "Requérir le registre des bénéficiaires effectifs (RBE) pour chaque société administrée",
            "Confronter la structure aux déclarations fiscales et bancaires de l'administrateur",
            "Vérifier l'absence de convention de prête-nom occulte (nominee agreement)",
        ],
    )
    return report, {"type": "prete_nom_hub", "finding": p, "note": note}


def qualify_findings(
    inv, use_llm: bool = False, model: str | None = None, cache_dir: Path | None = None
) -> list[AnomalyReport]:
    """Un rapport par constat (circuit, fractionnement, bénéficiaire caché ou prête-nom)."""
    built = [_cycle_report(inv, c) for c in inv.findings["cycles"]]
    built += [_smurf_report(inv, s) for s in inv.findings["smurfing"]]
    if inv.findings["hidden_controllers"]:
        built += [_controller_report(inv, h) for h in inv.findings["hidden_controllers"]]
    else:
        nominees = [p for p in inv.findings.get("portfolios", []) if p.get("nominee_profile")]
        if nominees:
            built += [_nominee_hub_report(inv, nominees[0])]
    client = _llm_client() if use_llm else None
    model = model or settings.llm_model
    reports = []
    for report, facts in built:
        author = "deterministe"
        if use_llm:
            note, author = _narrate(client, model, report, facts, cache_dir)
            report = report.model_copy(update={"summary_note": note})
        inv.findings.setdefault("report_authors", []).append(author)
        reports.append(report)
    return reports
