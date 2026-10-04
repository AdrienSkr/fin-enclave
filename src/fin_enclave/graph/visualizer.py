"""
Générateur de Visualisation de Graphe Forensic — Forensic Workbench Interactif.
Interface sobre, claire et épurée (style station d'investigation judiciaire),
conçue pour une analyse topologique directe, la vérification des montages d'infraction,
la navigation fluide entre entités et l'accès direct aux pièces scellées (ISO/IEC 27037).
"""

from __future__ import annotations

import html
import json
import os
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Any

import networkx as nx

if TYPE_CHECKING:
    from ..schemas import AnomalyReport, ProofPoint
    from .detector import DetectionResult


def _load_embedded_asset(asset_rel_path: str) -> str:
    """Charge un asset local depuis le dossier lib/ pour un fonctionnement 100 % hors-ligne."""
    current_dir = Path(__file__).resolve()
    candidates = [
        current_dir.parents[3] / "lib" / asset_rel_path,
        current_dir.parents[2] / "lib" / asset_rel_path,
        Path("lib") / asset_rel_path,
        Path("fin-enclave/lib") / asset_rel_path,
    ]
    for p in candidates:
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                pass
    return ""


def _compute_forensic_positions(
    G: nx.DiGraph,
    detection: DetectionResult,
) -> dict[str, dict[str, Any]]:
    """Calcule des coordonnées (x, y) et un niveau hiérarchique en fallback."""
    positions: dict[str, dict[str, Any]] = {}
    for i, (node_id, data) in enumerate(G.nodes(data=True)):
        if "x" in data and "y" in data:
            positions[node_id] = {"x": data["x"], "y": data["y"], "level": data.get("level", 1)}
        else:
            ent_type = str(data.get("entity_type", "Societe"))
            is_pivot = (node_id == detection.pivot_node) or (
                node_id == detection.pivot_intermediary_node
            )
            is_cycle = node_id in detection.suspicious_nodes

            if ent_type == "PersonnePhysique" or node_id.startswith(("PEP_", "NOM_")):
                lvl = 0
                x = -400 + (i % 3) * 280
                y = -260 + (i // 3) * 60
            elif is_pivot and ent_type == "Intermediaire":
                lvl = 4
                x = 120
                y = 230
            elif is_cycle:
                lvl = 2
                x = -100 + (i % 3) * 300
                y = -40 + (i // 3) * 80
            else:
                lvl = 1
                x = -300 + (i % 3) * 260
                y = 80 + (i // 3) * 80

            positions[node_id] = {"x": x, "y": y, "level": lvl}

    return positions


def export_interactive_graph(
    G: nx.DiGraph,
    detection: DetectionResult,
    output_path: Path | str = "data/outputs/fin_enclave_graph.html",
    auto_open: bool = False,
    report: AnomalyReport | None = None,
    reports: list[AnomalyReport] | None = None,
    findings: dict | None = None,
    pieces: list[Any] | None = None,
    ledger: dict[str, ProofPoint] | None = None,
    dossier_path: Path | str | None = None,
    case_label: str = "Dossier d'investigation",
) -> Path:
    """
    Génère le Forensic Workbench interactif :
    - Sélecteur d'infractions multi-constats dans le header (montage isolé par infraction)
    - Masquage strict des arêtes non pertinentes pour supprimer tout effet spaghetti
    - Navigation directe par clic entre cartes / entités
    - Mode Libre aéré (physique Obsidian sans chevauchement)
    - Volet Rapport d'Investigation intégré avec liens cliquables
    - Visionneuse de pièces justificatives scellées (scan / photo / SHA-256)
    """
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    vis_css_content = _load_embedded_asset("vis-9.1.2/vis-network.css")
    vis_js_content = _load_embedded_asset("vis-9.1.2/vis-network.min.js")

    forensic_positions = _compute_forensic_positions(G, detection)

    # Dictionnaire de correspondance Nom -> ID
    name_to_node_id = {G.nodes[n].get("name", n): n for n in G.nodes()}

    node_transactions: dict[str, list[dict[str, Any]]] = {n: [] for n in G.nodes()}

    edge_pairs: set[tuple[str, str]] = set()
    for u_e, v_e in G.edges():
        if G.has_edge(v_e, u_e):
            edge_pairs.add(tuple(sorted([str(u_e), str(v_e)])))

    edges_data: list[dict[str, Any]] = []
    for u, v, data in G.edges(data=True):
        amount = float(data.get("amount_usd", 0.0) or 0.0)
        rel_type = str(data.get("rel_type", "transfers_to"))
        doc_ref = str(data.get("doc_reference", "N/A"))
        proof_sha = str(data.get("proof_sha256", ""))
        edge_pieces = list(data.get("pieces", []))
        is_suspicious = u in detection.suspicious_nodes and v in detection.suspicious_nodes

        is_financial = amount > 0
        edge_label = f"${amount:,.0f}" if is_financial else rel_type.replace("_", " ")

        pair_key = tuple(sorted([str(u), str(v)]))
        has_reverse = pair_key in edge_pairs
        is_cycle_loop_return = (
            u == detection.pivot_intermediary_node or u == detection.pivot_node
        ) and is_suspicious

        if is_cycle_loop_return:
            smooth_cfg = {"enabled": True, "type": "curvedCW", "roundness": 0.38}
        elif has_reverse:
            roundness = 0.22 if str(u) < str(v) else 0.36
            smooth_cfg = {"enabled": True, "type": "curvedCW", "roundness": roundness}
        else:
            smooth_cfg = {"enabled": True, "type": "curvedCW", "roundness": 0.14}

        edge_color = "#dc2626" if is_suspicious else ("#2563eb" if is_financial else "#64748b")
        edge_width = 2.6 if is_suspicious else (1.8 if is_financial else 1.3)
        edge_dashes = False if is_financial else [5, 5]

        rel_clean = rel_type.replace("_", " ")
        if is_financial:
            type_desc = f"Flux financier ({rel_clean})"
            amount_html = f"<div>Montant : <strong>${amount:,.0f} USD</strong></div>"
        else:
            type_desc = f"Lien corporatif ({rel_clean})"
            amount_html = ""

        pieces_html = ", ".join(edge_pieces) if edge_pieces else doc_ref
        edge_tooltip = (
            f"<div style='font-family:system-ui,sans-serif;font-size:12px;color:#0f172a;line-height:1.4;padding:4px;'>"
            f"<div><strong>{type_desc}</strong></div>"
            f"{amount_html}"
            f"<div style='font-size:11px;color:#475569;'>Pièces : {pieces_html}</div>"
            f"<div style='font-size:10px;font-family:monospace;color:#64748b;'>SHA-256 : {proof_sha[:16]}...</div>"
            f"</div>"
        )

        edge_id = f"{u}->{v}"
        edges_data.append(
            {
                "id": edge_id,
                "from": u,
                "to": v,
                "label": edge_label,
                "title": edge_tooltip,
                "amount_usd": amount,
                "rel_type": rel_type,
                "doc_reference": doc_ref,
                "pieces": edge_pieces,
                "proof_sha256": proof_sha,
                "color": edge_color,
                "width": edge_width,
                "dashes": edge_dashes,
                "smooth": smooth_cfg,
                "is_suspicious": is_suspicious,
            }
        )

        u_name = G.nodes[u].get("name", u) if G.has_node(u) else u
        v_name = G.nodes[v].get("name", v) if G.has_node(v) else v
        if u in node_transactions:
            node_transactions[u].append(
                {
                    "dir": "out",
                    "counterparty": v_name,
                    "counterparty_id": v,
                    "amount": amount,
                    "rel_type": rel_type,
                    "doc_ref": doc_ref,
                    "pieces": edge_pieces,
                }
            )
        if v in node_transactions:
            node_transactions[v].append(
                {
                    "dir": "in",
                    "counterparty": u_name,
                    "counterparty_id": u,
                    "amount": amount,
                    "rel_type": rel_type,
                    "doc_ref": doc_ref,
                    "pieces": edge_pieces,
                }
            )

    nodes_data: list[dict[str, Any]] = []
    for node_id, data in G.nodes(data=True):
        name = str(data.get("name", node_id))
        ent_type = str(data.get("entity_type", "Societe"))
        country = str(data.get("country", "N/A"))
        proof_sha = str(data.get("proof_sha256", ""))
        doc_ref = str(data.get("doc_reference", "N/A"))
        node_pieces = list(data.get("mentions", [])) or list(data.get("pieces", []))
        betweenness = float(detection.betweenness_scores.get(node_id, 0.0))

        is_in_cycle = node_id in detection.suspicious_nodes
        is_pivot = (node_id == detection.pivot_node) or (
            node_id == detection.pivot_intermediary_node
        )

        if is_pivot:
            color = {
                "background": "#fffbeb",
                "border": "#b45309",
                "highlight": {"background": "#fef3c7", "border": "#78350f"},
            }
            status_text = "Entité pivot"
            category = "pivot"
            tag = "PIVOT"
        elif is_in_cycle:
            color = {
                "background": "#fef2f2",
                "border": "#dc2626",
                "highlight": {"background": "#fee2e2", "border": "#991b1b"},
            }
            status_text = "Circuit suspect"
            category = "suspicious"
            tag = "SUSPECT"
        elif ent_type == "PersonnePhysique":
            color = {
                "background": "#f5f3ff",
                "border": "#7c3aed",
                "highlight": {"background": "#ede9fe", "border": "#5b21b6"},
            }
            status_text = "Personne physique"
            category = "person"
            tag = "UBO" if "PEP" in node_id else "PERSONNE"
        elif ent_type == "Intermediaire":
            color = {
                "background": "#f0f9ff",
                "border": "#0284c7",
                "highlight": {"background": "#e0f2fe", "border": "#0369a1"},
            }
            status_text = "Intermédiaire fiduciaire"
            category = "intermediary"
            tag = "INTERMÉDIAIRE"
        else:
            color = {
                "background": "#eff6ff",
                "border": "#2563eb",
                "highlight": {"background": "#dbeafe", "border": "#1d4ed8"},
            }
            status_text = "Société"
            category = "company"
            tag = "SOCIÉTÉ"

        pos = forensic_positions.get(node_id, {"x": 0, "y": 0, "level": 1})
        label = f"<b>{name}</b>\n[{tag}] • {country}"

        nodes_data.append(
            {
                "id": node_id,
                "label": label,
                "name": name,
                "country": country,
                "entity_type": ent_type,
                "category": category,
                "status_text": status_text,
                "doc_ref": doc_ref,
                "pieces": node_pieces,
                "proof_sha": proof_sha,
                "betweenness": betweenness,
                "is_in_cycle": is_in_cycle,
                "is_pivot": is_pivot,
                "color": color,
                "shape": "box",
                "shapeProperties": {"borderRadius": 0},
                "margin": {"top": 8, "bottom": 8, "left": 12, "right": 12},
                "x": pos["x"],
                "y": pos["y"],
                "level": pos["level"],
                "transactions": node_transactions.get(node_id, []),
            }
        )

    # -------------------------------------------------------------------------
    # Construction des infractions
    # -------------------------------------------------------------------------
    infractions_data: list[dict[str, Any]] = []
    raw_reports = reports if reports is not None else ([report] if report else [])

    for idx, r in enumerate(raw_reports):
        infr_id = f"infr_{idx}"
        core_node_ids = set()
        for ent in r.entities_involved:
            if ent in G:
                core_node_ids.add(ent)
            elif ent in name_to_node_id:
                core_node_ids.add(name_to_node_id[ent])

        core_names = {G.nodes[n].get("name", n) for n in core_node_ids}
        core_radicals = {
            G.nodes[n].get("name", "").split()[0].lower()
            for n in core_node_ids
            if G.nodes[n].get("name")
        }

        core_nodes_list = [
            {
                "id": nid,
                "name": G.nodes[nid].get("name", nid),
                "entity_type": G.nodes[nid].get("entity_type", "Societe"),
            }
            for nid in sorted(core_node_ids)
        ]

        # Recherche exhaustive des personnes physiques, prête-noms et intermédiaires liés
        controllers: dict[str, dict[str, Any]] = {}

        # 1. Depuis ownership table (détenteurs, mandataires, fiduciaires)
        for row in findings.get("ownership", []) if findings else []:
            c_name = row.get("company", "")
            c_id = row.get("id")
            if c_name in core_names or c_id in core_node_ids:
                for h in row.get("holders", []):
                    controllers[h["id"]] = {
                        "id": h["id"],
                        "name": h["name"],
                        "role": f"Actionnaire / Prête-nom ({h.get('role', 'actionnaire')})",
                        "entity_type": G.nodes.get(h["id"], {}).get("entity_type", "Societe"),
                        "target": c_name,
                    }
                for att in row.get("attorneys", []):
                    controllers[att["id"]] = {
                        "id": att["id"],
                        "name": att["name"],
                        "role": "Mandataire (procuration)",
                        "entity_type": G.nodes.get(att["id"], {}).get(
                            "entity_type", "PersonnePhysique"
                        ),
                        "target": c_name,
                    }
                for inter in row.get("intermediaries", []):
                    controllers[inter["id"]] = {
                        "id": inter["id"],
                        "name": inter["name"],
                        "role": "Cabinet fiduciaire / Domiciliation",
                        "entity_type": G.nodes.get(inter["id"], {}).get(
                            "entity_type", "Intermediaire"
                        ),
                        "target": c_name,
                    }

        # 2. Prédécesseurs directs dans G avec liens structurels
        for nid in list(core_node_ids):
            c_name = G.nodes[nid].get("name", nid)
            for p in G.predecessors(nid):
                links = G[p][nid].get("links", [])
                if links and p not in controllers:
                    p_data = G.nodes[p]
                    controllers[p] = {
                        "id": p,
                        "name": p_data.get("name", p),
                        "role": f"Lien structurel ({links[0]})",
                        "entity_type": p_data.get("entity_type", "Societe"),
                        "target": c_name,
                    }

        # 3. Sociétés affiliées (même radical de nom de groupe)
        sister_nodes = set()
        for nid, data in G.nodes(data=True):
            if nid not in core_node_ids:
                name = data.get("name", "")
                rad = name.split()[0].lower() if name else ""
                if rad and rad in core_radicals and data.get("entity_type") == "Societe":
                    sister_nodes.add(nid)

        # 4. UBO personnes physiques rattachées
        relevant_targets = core_node_ids | set(controllers.keys()) | sister_nodes
        for nid, data in G.nodes(data=True):
            if data.get("entity_type") == "PersonnePhysique":
                p_name = data.get("name", nid)
                for s in G.successors(nid):
                    s_links = G[nid][s].get("links", [])
                    if s in relevant_targets and s_links:
                        is_ubo = "beneficial_owner" in s_links
                        controllers[nid] = {
                            "id": nid,
                            "name": p_name,
                            "role": "Bénéficiaire effectif (UBO)"
                            if is_ubo
                            else "Dirigeant / Actionnaire physique",
                            "entity_type": "PersonnePhysique",
                            "target": G.nodes[s].get("name", s),
                        }
                        if s in sister_nodes and s not in controllers:
                            s_data = G.nodes[s]
                            controllers[s] = {
                                "id": s,
                                "name": s_data.get("name", s),
                                "role": f"Société affiliée au groupe ({s_data.get('name', s)})",
                                "entity_type": "Societe",
                                "target": s_data.get("name", s),
                            }

        all_node_ids = sorted(core_node_ids | set(controllers.keys()))
        all_node_set = set(all_node_ids)
        involved_edges = [
            f"{u_e}->{v_e}" for u_e, v_e in G.edges if u_e in all_node_set and v_e in all_node_set
        ]

        pieces_cited: list[str] = []
        if r.chain_of_custody:
            pieces_cited = sorted(
                {p.cote_judiciaire.split("/")[0] for p in r.chain_of_custody if p.cote_judiciaire}
            )

        steps: list[dict[str, Any]] = []
        if findings and "cycles" in findings:
            for c in findings["cycles"]:
                c_nodes = set(c.get("cycle_nodes", []))
                if c_nodes and (c_nodes & set(r.entities_involved)):
                    steps = c.get("steps", [])
                    break

        label_fr = r.infraction_type.replace("_", " ")
        badge_label = f"#{idx + 1} {label_fr} (${r.total_amount_usd:,.0f})"

        infractions_data.append(
            {
                "id": infr_id,
                "index": idx + 1,
                "type": r.infraction_type,
                "title": label_fr,
                "badge": badge_label,
                "amount_usd": r.total_amount_usd,
                "confidence_score": r.confidence_score,
                "summary_note": r.summary_note,
                "legal_basis": r.legal_basis,
                "recommendations": r.recommendations,
                "entities_involved": r.entities_involved,
                "core_nodes": core_nodes_list,
                "controllers": list(controllers.values()),
                "node_ids": all_node_ids,
                "edge_ids": involved_edges,
                "pieces": pieces_cited,
                "steps": steps,
            }
        )

    # Fallback si reports était vide mais que findings a des anomalies
    if not infractions_data and findings:
        for idx, c in enumerate(findings.get("cycles", [])):
            nodes = c.get("cycle_nodes", [])
            node_ids = [name_to_node_id.get(n, n) for n in nodes if n in name_to_node_id or n in G]
            involved_edges = [
                f"{name_to_node_id.get(s['from'], s['from'])}->{name_to_node_id.get(s['to'], s['to'])}"
                for s in c.get("steps", [])
            ]
            pieces_list = sorted({p for s in c.get("steps", []) for p in s.get("pieces", [])})
            infractions_data.append(
                {
                    "id": f"cycle_{idx}",
                    "index": len(infractions_data) + 1,
                    "type": "BLANCHIMENT_CYCLE_FERME",
                    "title": f"Circuit fermé : {' ➔ '.join(nodes)}",
                    "badge": f"#{len(infractions_data) + 1} Circuit fermé (${c.get('entry_amount_usd', 0):,.0f})",
                    "amount_usd": c.get("entry_amount_usd", 0.0),
                    "confidence_score": 1.0,
                    "summary_note": f"Circuit fermé détecté de {len(nodes)} sociétés avec flux circulaire.",
                    "legal_basis": [
                        "Art. 324-1 Code pénal : blanchiment",
                        "Art. L. 561-15 CMF : déclaration TRACFIN",
                    ],
                    "recommendations": [
                        "Confronter les pièces citées aux originaux scellés.",
                        "Requérir les relevés complets des comptes.",
                    ],
                    "entities_involved": nodes,
                    "node_ids": node_ids,
                    "edge_ids": involved_edges,
                    "pieces": pieces_list,
                    "steps": c.get("steps", []),
                }
            )

        for idx, s in enumerate(findings.get("smurfing", [])):
            source = s.get("source_name", "")
            collector = s.get("collector_name", "")
            mules = s.get("mule_names", [])
            all_nodes = [source, collector] + mules
            node_ids = [
                name_to_node_id.get(n, n) for n in all_nodes if n in name_to_node_id or n in G
            ]
            infractions_data.append(
                {
                    "id": f"smurf_{idx}",
                    "index": len(infractions_data) + 1,
                    "type": "FRACTIONNEMENT_SCHTROUMPFAGE",
                    "title": f"Fractionnement : {source} ➔ {len(mules)} relais ➔ {collector}",
                    "badge": f"#{len(infractions_data) + 1} Fractionnement (${s.get('total_collected_usd', 0):,.0f})",
                    "amount_usd": s.get("total_collected_usd", 0.0),
                    "confidence_score": 1.0,
                    "summary_note": f"Fractionnement suspect de {s.get('total_collected_usd', 0):,.0f} USD via {len(mules)} mules.",
                    "legal_basis": ["Art. 324-1 Code pénal", "Art. L. 561-15 CMF"],
                    "recommendations": ["Identifier les comptes collecteurs."],
                    "entities_involved": all_nodes,
                    "node_ids": node_ids,
                    "edge_ids": [],
                    "pieces": s.get("pieces", []),
                    "steps": [],
                }
            )

        for idx, h in enumerate(findings.get("hidden_controllers", [])):
            name = h.get("name", "")
            companies = h.get("companies", [])
            all_nodes = [name] + companies
            node_ids = [
                name_to_node_id.get(n, n) for n in all_nodes if n in name_to_node_id or n in G
            ]
            infractions_data.append(
                {
                    "id": f"ctrl_{idx}",
                    "index": len(infractions_data) + 1,
                    "type": "DISSIMULATION_UBO_PRETE_NOM",
                    "title": f"Bénéficiaire caché : {name} sur {len(companies)} sociétés",
                    "badge": f"#{len(infractions_data) + 1} UBO : {name}",
                    "amount_usd": 0.0,
                    "confidence_score": 1.0,
                    "summary_note": f"Procuration non enregistrée conférant le contrôle effectif de {len(companies)} sociétés à {name}.",
                    "legal_basis": [
                        "Art. L. 561-2-2 CMF (Bénéficiaire effectif)",
                        "Recommandation 24 GAFI",
                    ],
                    "recommendations": ["Vérifier la validité de la procuration."],
                    "entities_involved": all_nodes,
                    "node_ids": node_ids,
                    "edge_ids": [],
                    "pieces": h.get("pieces", []),
                    "steps": [],
                }
            )

    # -------------------------------------------------------------------------
    # Référentiel des pièces scellées (ISO/IEC 27037)
    # -------------------------------------------------------------------------
    pieces_dict: dict[str, dict[str, Any]] = {}
    if pieces and dossier_path:
        dossier_p = Path(dossier_path)
        for p in pieces:
            rel_p = os.path.relpath(dossier_p / p.file, out_file.parent).replace("\\", "/")
            pieces_dict[p.piece_id] = {
                "id": p.piece_id,
                "file": p.file,
                "doc_type": p.doc_type,
                "sha256": p.file_sha256,
                "rel_path": rel_p,
                "is_image": Path(p.file).suffix.lower() in {".png", ".jpg", ".jpeg"},
                "is_pdf": Path(p.file).suffix.lower() == ".pdf",
                "entities": [e.name for e in p.entities],
                "transfers": [
                    {
                        "payer": t.payer,
                        "payee": t.payee,
                        "amount": t.amount,
                        "currency": t.currency,
                        "date": t.date,
                    }
                    for t in p.transfers
                ],
            }

    max_amount = max([e.get("amount_usd", 0.0) for e in edges_data], default=1_000_000.0)
    financial_flows_count = sum(1 for e in edges_data if e["amount_usd"] > 0)
    structural_links_count = len(edges_data) - financial_flows_count

    meta = {
        "closed_cycles": len(detection.closed_cycles),
        "total_volume_usd": detection.total_cycle_volume_usd,
        "pivot_name": detection.pivot_name or detection.pivot_intermediary_name or "N/A",
        "nodes_count": len(nodes_data),
        "edges_count": len(edges_data),
        "financial_flows_count": financial_flows_count,
        "structural_links_count": structural_links_count,
        "infractions_count": len(infractions_data),
        "max_amount_usd": max_amount,
    }

    nodes_json = json.dumps(nodes_data, ensure_ascii=False, default=str)
    edges_json = json.dumps(edges_data, ensure_ascii=False, default=str)
    infractions_json = json.dumps(infractions_data, ensure_ascii=False, default=str)
    pieces_json = json.dumps(pieces_dict, ensure_ascii=False, default=str)
    findings_json = json.dumps(findings or {}, ensure_ascii=False, default=str)

    if vis_css_content:
        vis_css_tag = f"<style id='vis-embedded-css'>\n{vis_css_content}\n</style>"
    else:
        vis_css_tag = '<link rel="stylesheet" href="../../lib/vis-9.1.2/vis-network.css" />'

    if vis_js_content:
        vis_js_tag = f"<script id='vis-embedded-js'>\n{vis_js_content}\n</script>"
    else:
        vis_js_tag = '<script src="../../lib/vis-9.1.2/vis-network.min.js"></script>'

    html_content = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>FinEnclave — Forensic Workbench Interactif</title>
  {vis_css_tag}
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --bg: #f8fafc;
      --surface: #ffffff;
      --border: #cbd5e1;
      --text: #0f172a;
      --muted: #64748b;
      --primary: #2563eb;
      --danger: #b91c1c;
      --danger-bg: #fef2f2;
      --danger-border: #fecaca;
    }}
    body {{
      width: 100vw; height: 100vh; overflow: hidden;
      background: var(--bg); color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 12px; line-height: 1.4;
    }}
    /* Barres d'outils */
    .toolstrip, .substrip {{
      position: fixed; left: 0; right: 0; z-index: 100;
      display: flex; align-items: center; justify-content: space-between;
      padding: 0 14px; background: var(--surface); border-bottom: 1px solid var(--border);
    }}
    .toolstrip {{ top: 0; height: 40px; }}
    .substrip {{ top: 40px; height: 34px; background: var(--bg); z-index: 99; }}
    .toolstrip-left, .toolstrip-right, .substrip-left, .substrip-right {{
      display: flex; align-items: center; gap: 8px; white-space: nowrap;
    }}
    .app-title {{ font-weight: 800; font-size: 13px; display: flex; align-items: center; gap: 6px; }}
    .status-summary {{ font-size: 11px; color: var(--muted); padding-left: 10px; border-left: 1px solid var(--border); display: flex; gap: 10px; }}
    .status-summary strong {{ color: var(--text); font-variant-numeric: tabular-nums; }}

    /* Boutons et filtres */
    .btn {{
      background: var(--surface); border: 1px solid var(--border); color: var(--text);
      padding: 3px 8px; font-size: 11px; font-weight: 500; cursor: pointer; user-select: none;
      line-height: 1.2;
    }}
    .btn:hover {{ background: #f1f5f9; }}
    .btn.active {{ background: var(--primary); color: #fff; border-color: var(--primary); }}
    .btn-report {{ background: var(--text); color: #fff; border-color: var(--text); font-weight: 600; }}
    .btn-report:hover {{ background: #1e293b; }}
    .btn-report.active {{ background: var(--primary); border-color: var(--primary); }}
    .group-label {{ color: var(--muted); font-size: 10px; font-weight: 700; text-transform: uppercase; }}
    .sep {{ height: 14px; width: 1px; background: var(--border); margin: 0 2px; }}
    .search-input {{ background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 3px 7px; font-size: 11px; width: 140px; outline: none; }}
    .search-input:focus {{ border-color: var(--primary); }}
    .slider-control {{ width: 80px; cursor: pointer; height: 14px; vertical-align: middle; }}

    /* Sélecteur d'infractions */
    .infr-selector-bar {{ display: flex; align-items: center; gap: 6px; overflow-x: auto; max-width: 55vw; }}
    .infr-selector-label {{ font-size: 10px; font-weight: 700; text-transform: uppercase; color: var(--muted); white-space: nowrap; }}
    .infr-pill {{
      background: var(--surface); border: 1px solid var(--border); color: var(--text);
      padding: 3px 8px; font-size: 11px; cursor: pointer; font-weight: 600; white-space: nowrap;
    }}
    .infr-pill:hover {{ background: #f1f5f9; }}
    .infr-pill.active {{ background: var(--danger); color: #fff; border-color: #991b1b; }}
    .infr-pill.pill-all.active {{ background: var(--primary); color: #fff; border-color: var(--primary); }}

    /* Bandeau de montage actif */
    .montage-banner {{
      position: fixed; top: 78px; left: 14px; z-index: 120;
      background: var(--surface); border: 1px solid var(--danger); border-left: 4px solid var(--danger);
      padding: 6px 12px; display: none; align-items: center; gap: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }}
    .montage-banner.active {{ display: flex; }}
    .montage-title {{ font-weight: 700; font-size: 12px; color: var(--danger); }}
    .montage-sub {{ font-size: 11px; color: var(--muted); }}

    /* Canvas */
    #network {{ position: fixed; top: 74px; left: 0; right: 0; bottom: 0; width: 100vw; height: calc(100vh - 74px); background: var(--bg); }}

    /* Boutons flottants bas-droite */
    .floating-nav {{ position: fixed; bottom: 14px; right: 14px; display: flex; flex-direction: column; gap: 5px; z-index: 150; }}
    .retro-tool-btn {{ width: 32px; height: 32px; background: var(--surface); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; cursor: pointer; }}
    .retro-tool-btn:hover {{ background: #f1f5f9; }}

    /* Inspecteur latéral */
    .inspector {{
      position: fixed; top: 80px; right: 14px; width: 340px; max-height: calc(100vh - 110px);
      background: var(--surface); border: 1px solid var(--border); padding: 12px 14px;
      display: flex; flex-direction: column; gap: 8px; overflow-y: auto; z-index: 200; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
    }}
    .inspector[hidden] {{ display: none !important; }}
    .inspector-header {{ display: flex; justify-content: space-between; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; }}
    .inspector-title {{ font-weight: 700; font-size: 13px; color: var(--text); }}
    .inspector-close {{ background: none; border: none; font-size: 14px; color: var(--muted); cursor: pointer; padding: 0 4px; }}
    .inspector-row {{ display: flex; justify-content: space-between; font-size: 12px; padding: 2px 0; }}
    .inspector-row .label {{ color: var(--muted); }}
    .inspector-row .val {{ font-weight: 600; font-variant-numeric: tabular-nums; }}
    .inspector-hash {{ background: #f1f5f9; border: 1px solid var(--border); padding: 5px 8px; font-family: monospace; font-size: 10px; word-break: break-all; }}
    .copy-btn {{ width: 100%; margin-top: 4px; padding: 3px; font-size: 11px; }}

    /* Transactions & navigation */
    .trans-list {{ list-style: none; max-height: 240px; overflow-y: auto; border: 1px solid var(--border); }}
    .trans-item {{ padding: 5px 8px; border-bottom: 1px solid #f1f5f9; font-size: 11px; display: flex; flex-direction: column; gap: 2px; }}
    .trans-top {{ display: flex; justify-content: space-between; align-items: center; }}
    .nav-node-btn {{ background: none; border: none; font-size: 11px; font-weight: 600; color: var(--primary); cursor: pointer; padding: 0; text-decoration: underline; }}
    .piece-tag {{ display: inline-block; background: #f1f5f9; border: 1px solid var(--border); padding: 1px 5px; font-size: 10px; cursor: pointer; font-weight: 600; margin-top: 2px; }}
    .piece-tag:hover {{ background: #e2e8f0; }}
    .trans-group-header {{ padding: 4px 6px; background: #f8fafc; border-bottom: 1px solid var(--border); font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }}
    .badge-role {{ font-size: 9px; padding: 1px 5px; font-weight: 700; border-radius: 2px; }}
    .badge-role-core {{ background: #fee2e2; color: #991b1b; }}
    .badge-role-ubo {{ background: #dcfce7; color: #166534; }}
    .badge-role-nominee {{ background: #fef3c7; color: #92400e; }}
    .badge-role-trust {{ background: #e0f2fe; color: #0369a1; }}

    /* Fiche infraction dans inspecteur */
    .infr-card {{ background: var(--danger-bg); border: 1px solid var(--danger-border); padding: 8px 10px; margin-top: 6px; display: flex; flex-direction: column; gap: 6px; }}
    .infr-card-title {{ font-weight: 700; color: var(--danger); font-size: 12px; }}
    .infr-card-legal {{ font-size: 10px; color: #7f1d1d; line-height: 1.3; }}
    .infr-step-row {{ background: var(--surface); border: 1px solid var(--danger-border); padding: 4px 6px; font-size: 11px; margin-top: 3px; }}

    /* Tiroir Rapport */
    .report-drawer {{
      position: fixed; top: 40px; right: 0; bottom: 0; width: 440px;
      background: var(--surface); border-left: 1px solid var(--border); z-index: 250;
      display: flex; flex-direction: column; box-shadow: -4px 0 10px rgba(0,0,0,0.08);
      transform: translateX(100%);
    }}
    .report-drawer.open {{ transform: translateX(0); }}
    .report-header {{ height: 40px; padding: 0 14px; background: var(--bg); border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; }}
    .report-header-title {{ font-weight: 700; font-size: 13px; }}
    .report-content {{ padding: 14px; overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: 14px; font-size: 12px; line-height: 1.5; }}
    .report-section {{ border-bottom: 1px solid #f1f5f9; padding-bottom: 12px; }}
    .report-section-title {{ font-weight: 700; font-size: 12px; color: #1e293b; margin-bottom: 6px; text-transform: uppercase; }}
    .report-entity-link {{ color: var(--primary); font-weight: 600; cursor: pointer; text-decoration: underline; }}

    /* Modale Pièce */
    .modal-backdrop {{ position: fixed; inset: 0; background: rgba(15, 23, 42, 0.6); z-index: 500; display: none; align-items: center; justify-content: center; padding: 20px; }}
    .modal-backdrop.open {{ display: flex; }}
    .modal-window {{ background: var(--surface); width: 780px; max-width: 95vw; max-height: 90vh; border: 1px solid var(--border); display: flex; flex-direction: column; }}
    .modal-header {{ padding: 10px 14px; border-bottom: 1px solid var(--border); background: var(--bg); display: flex; justify-content: space-between; }}
    .modal-body {{ padding: 14px; overflow-y: auto; display: flex; gap: 16px; flex: 1; }}
    .modal-preview-box {{ flex: 1.2; background: #f1f5f9; border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; min-height: 380px; max-height: 520px; overflow: auto; padding: 10px; }}
    .modal-preview-img {{ max-width: 100%; max-height: 500px; object-fit: contain; background: #fff; }}
    .modal-meta-box {{ flex: 0.8; display: flex; flex-direction: column; gap: 10px; font-size: 12px; }}

    .status-toast {{ position: fixed; bottom: 14px; left: 14px; background: #0f172a; color: #fff; padding: 4px 10px; font-size: 11px; display: none; z-index: 600; }}
    div.vis-tooltip {{ background: #fff !important; border: 1px solid var(--border) !important; color: var(--text) !important; font-size: 12px !important; padding: 8px 10px !important; z-index: 1000 !important; max-width: 320px; }}
  </style>
</head>
<body>

  <!-- Barre 1 : Synthèse du dossier & Sélecteur d'infractions -->
  <header class="toolstrip">
    <div class="toolstrip-left">
      <span class="app-title">FinEnclave</span>
      <div class="status-summary">
        <span>Affaire : <strong>{html.escape(case_label)}</strong></span>
        <span>Entités : <strong>{meta["nodes_count"]}</strong></span>
        <span>Liens : <strong>{meta["edges_count"]}</strong></span>
        <span>Pivot : <strong>{meta["pivot_name"]}</strong></span>
      </div>
    </div>

    <!-- Sélecteur d'infractions au centre -->
    <div class="infr-selector-bar" id="infrSelectorBar">
      <span class="infr-selector-label">Infractions :</span>
      <button class="infr-pill pill-all active" id="btnInfrAll">Vue globale</button>
      <!-- Pills injectées en JS -->
    </div>

    <div class="toolstrip-right">
      <button class="btn btn-report" id="btnToggleReport">Rapport d'enquête</button>
    </div>
  </header>

  <!-- Barre 2 : Outils d'investigation et filtres -->
  <div class="substrip">
    <div class="substrip-left">
      <div class="filter-group">
        <span class="group-label">Type :</span>
        <button class="btn btn-type active" data-type="all">Tous</button>
        <button class="btn btn-type" data-type="Societe">Sociétés</button>
        <button class="btn btn-type" data-type="PersonnePhysique">Personnes</button>
        <button class="btn btn-type" data-type="Intermediaire">Intermédiaires</button>
      </div>

      <div class="sep"></div>

      <div class="filter-group">
        <span class="group-label">Statut :</span>
        <button class="btn btn-status active" data-status="all">Tous</button>
        <button class="btn btn-status" data-status="suspicious" title="Isoler les circuits et nœuds suspects">Suspects / Circuits</button>
        <button class="btn btn-status" data-status="pivot">Pivot</button>
      </div>
    </div>

    <div class="substrip-right">
      <div class="filter-group">
        <label for="amountSlider" class="group-label">Seuil financier ≥ <span id="cutoffVal" style="font-weight:700; color:#0f172a; font-variant-numeric:tabular-nums;">$0</span></label>
        <input type="range" id="amountSlider" min="0" max="{int(meta["max_amount_usd"])}" step="{max(5000, int(meta["max_amount_usd"] // 20))}" value="0" class="slider-control" aria-label="Seuil financier des flux" />
      </div>

      <div class="sep"></div>

      <input type="search" id="searchBox" class="search-input" placeholder="Rechercher entité..." aria-label="Rechercher une entité" />
    </div>
  </div>

  <!-- Bandeau d'infraction active en mode montage -->
  <div class="montage-banner" id="montageBanner">
    <div>
      <div class="montage-title" id="montageBannerTitle">Montage d'infraction</div>
      <div class="montage-sub" id="montageBannerSub">Circuit isolé</div>
    </div>
    <button class="btn" id="btnFitMontage">Cadrer le montage</button>
    <button class="btn" id="btnResetMontage">✕ Revenir à la vue globale</button>
  </div>

  <!-- Zone Canvas Vis.js -->
  <div id="network"></div>

  <!-- Commandes flottantes bas-droite -->
  <nav class="floating-nav" aria-label="Navigation">
    <button class="retro-tool-btn" id="btnRecenter" title="Recentrer le graphe">
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#334155" stroke-width="1.8">
        <circle cx="8" cy="8" r="4.5" />
        <line x1="8" y1="1" x2="8" y2="4.5" /><line x1="8" y1="11.5" x2="8" y2="15" />
        <line x1="1" y1="8" x2="4.5" y2="8" /><line x1="11.5" y1="8" x2="15" y2="8" />
      </svg>
    </button>
    <button class="retro-tool-btn" id="btnExport" title="Exporter une capture PNG pour la procédure">
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="#334155" stroke-width="1.8">
        <path d="M2 5h3l1-2h4l1 2h3v9H2z" /><circle cx="8" cy="9.5" r="2.5" />
      </svg>
    </button>
  </nav>

  <!-- Panneau latéral d'inspection (entité ou infraction) -->
  <aside class="inspector" id="inspector" hidden>
    <div class="inspector-header">
      <div>
        <div style="display:flex; align-items:center; gap:6px; margin-bottom:2px;">
          <span style="font-size:10px; text-transform:uppercase; font-weight:700; color:#64748b;" id="inspStatus">Statut</span>
          <span id="inspBadge" style="font-size:9px; padding:1px 5px; font-weight:600;"></span>
        </div>
        <div class="inspector-title" id="inspName">Nom de l'entité</div>
      </div>
      <button class="inspector-close" id="inspClose" title="Fermer">✕</button>
    </div>

    <!-- Conteneur d'infraction active si applicable -->
    <div id="inspInfrContainer"></div>

    <div class="inspector-row">
      <span class="label">Identifiant</span>
      <span class="val" id="inspId">-</span>
    </div>
    <div class="inspector-row">
      <span class="label">Type / Pays</span>
      <span class="val" id="inspTypeCountry">-</span>
    </div>
    <div class="inspector-row">
      <span class="label">Centralité Brandes</span>
      <span class="val" id="inspBrandes">-</span>
    </div>
    <div class="inspector-row">
      <span class="label">Pièces associées</span>
      <span class="val" id="inspPiecesTags"></span>
    </div>

    <div>
      <span class="label" style="font-size:11px;">Scellé ISO 27037 (SHA-256) :</span>
      <div class="inspector-hash" id="inspHash">-</div>
      <button class="btn copy-btn" id="btnCopyHash">Copier SHA-256</button>
    </div>

    <div>
      <span class="label" id="inspTransTitle" style="font-size:11px;">Liens & Transactions directs (clic pour naviguer) :</span>
      <ul class="trans-list" id="inspTrans"></ul>
    </div>
  </aside>

  <!-- Volet latéral Rapport d'investigation -->
  <aside class="report-drawer" id="reportDrawer">
    <div class="report-header">
      <span class="report-header-title">Rapport d'Investigation & Qualifications</span>
      <button class="inspector-close" id="btnReportClose">✕</button>
    </div>
    <div class="report-content" id="reportContent">
      <!-- Rempli dynamiquement en JS -->
    </div>
  </aside>

  <!-- Modale de Visualisation de Pièce (Preuve ISO/IEC 27037) -->
  <div class="modal-backdrop" id="pieceModal">
    <div class="modal-window">
      <div class="modal-header">
        <div>
          <span class="modal-title" id="modalPieceTitle">PIECE-0000</span>
          <span style="font-size:11px; color:#64748b; margin-left:8px;" id="modalPieceType">bank_statement</span>
        </div>
        <button class="inspector-close" id="btnModalClose">✕</button>
      </div>
      <div class="modal-body">
        <div class="modal-preview-box" id="modalPreviewBox">
          <!-- Image ou iframe injecté ici -->
        </div>
        <div class="modal-meta-box">
          <div>
            <span class="label" style="font-size:11px;">Scellé cryptographique (SHA-256) :</span>
            <div class="inspector-hash" id="modalPieceHash">-</div>
            <button class="btn copy-btn" id="btnCopyModalHash">Copier SHA-256</button>
          </div>
          <div>
            <span class="label" style="font-size:11px; font-weight:700;">Entités citées sur cette pièce :</span>
            <ul id="modalPieceEntities" style="margin-top:4px; padding-left:16px;"></ul>
          </div>
          <div>
            <span class="label" style="font-size:11px; font-weight:700;">Mouvements / Virements constatés :</span>
            <ul id="modalPieceTransfers" style="margin-top:4px; list-style:none;"></ul>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div class="status-toast" id="toast"></div>

  {vis_js_tag}

  <script>
    const NODES = {nodes_json};
    const EDGES = {edges_json};
    const INFRACTIONS = {infractions_json};
    const PIECES = {pieces_json};
    const FINDINGS = {findings_json};

    let network = null;
    let nodesDataSet = null;
    let edgesDataSet = null;
    let pinnedNodeId = null;

    let currentTypeFilter = 'all';
    let currentStatusFilter = 'all';
    let currentAmountCutoff = 0;
    let activeInfractionId = null;

    function showToast(text) {{
      const t = document.getElementById('toast');
      t.textContent = text;
      t.style.display = 'block';
      setTimeout(() => {{ t.style.display = 'none'; }}, 2200);
    }}

    function initGraph() {{
      const container = document.getElementById('network');

      EDGES.forEach(e => {{
        if (e.title && typeof e.title === 'string') {{
          const el = document.createElement('div');
          el.innerHTML = e.title;
          e.title = el;
        }}
      }});

      nodesDataSet = new vis.DataSet(NODES);
      edgesDataSet = new vis.DataSet(EDGES);

      const options = {{
        nodes: {{
          shape: 'box',
          shapeProperties: {{ borderRadius: 0 }},
          borderWidth: 1.5,
          borderWidthSelected: 2.8,
          margin: {{ top: 8, bottom: 8, left: 12, right: 12 }},
          font: {{
            multi: 'html',
            size: 12,
            face: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
            color: '#0f172a'
          }},
          shadow: false
        }},
        edges: {{
          arrowStrikethrough: false,
          arrows: {{
            to: {{ enabled: true, scaleFactor: 0.85, type: 'arrow' }}
          }},
          font: {{
            size: 11,
            face: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
            color: '#0f172a',
            background: '#ffffff',
            strokeWidth: 0,
            align: 'horizontal'
          }},
          smooth: {{
            type: 'curvedCW',
            roundness: 0.18
          }}
        }},
        physics: {{
          enabled: false
        }},
        interaction: {{
          hover: true,
          tooltipDelay: 40,
          navigationButtons: false,
          keyboard: true
        }}
      }};

      network = new vis.Network(container, {{ nodes: nodesDataSet, edges: edgesDataSet }}, options);

      network.on('hoverNode', function(params) {{
        if (!pinnedNodeId && !activeInfractionId) {{
          openInspector(params.node, false);
          highlightNeighbors(params.node);
        }}
      }});

      network.on('blurNode', function(params) {{
        if (!pinnedNodeId && !activeInfractionId) {{
          closeInspector();
          applyFilters();
        }}
      }});

      network.on('click', function(params) {{
        if (params.nodes.length > 0) {{
          pinnedNodeId = params.nodes[0];
          openInspector(pinnedNodeId, true);
          highlightNeighbors(pinnedNodeId);
        }} else {{
          pinnedNodeId = null;
          if (!activeInfractionId) {{
            closeInspector();
            applyFilters();
          }}
        }}
      }});

      setTimeout(function() {{
        network.fit({{ animation: false }});
      }}, 60);
    }}

    // -----------------------------------------------------------------------
    // Filtrage rigoureux : arêtes masquées si les deux nœuds ne sont pas visibles !
    // -----------------------------------------------------------------------
    function applyFilters() {{
      const activeInfraction = activeInfractionId ? INFRACTIONS.find(i => i.id === activeInfractionId) : null;
      const highlightedNodeIds = new Set();

      if (activeInfraction) {{
        activeInfraction.node_ids.forEach(id => highlightedNodeIds.add(id));
      }} else {{
        NODES.forEach(n => {{
          let matchType = (currentTypeFilter === 'all') || (n.entity_type === currentTypeFilter);
          let matchStatus = true;
          if (currentStatusFilter === 'suspicious' && !n.is_in_cycle) matchStatus = false;
          if (currentStatusFilter === 'pivot' && !n.is_pivot) matchStatus = false;

          let matchCutoff = true;
          if (currentAmountCutoff > 0) {{
            const hasQualifyingFlow = n.transactions && n.transactions.some(t => t.amount >= currentAmountCutoff);
            if (!hasQualifyingFlow) matchCutoff = false;
          }}

          if (matchType && matchStatus && matchCutoff) {{
            highlightedNodeIds.add(n.id);
          }}
        }});
      }}

      // 1. Mise à jour des Nœuds
      const nodeUpdates = NODES.map(n => {{
        const isSelected = highlightedNodeIds.has(n.id);
        const isMontage = !!activeInfraction;
        return {{
          id: n.id,
          hidden: isMontage ? !isSelected : false,
          opacity: isSelected ? 1.0 : (isMontage ? 0.0 : 0.12)
        }};
      }});
      nodesDataSet.update(nodeUpdates);

      // 2. Mise à jour des Arêtes : MASQUAGE STRICT DES ARÊTES HORS FILTRE
      const edgeUpdates = EDGES.map(e => {{
        let isEdgeVisible = false;
        let isEdgeHighlighted = false;

        if (activeInfraction) {{
          // Mode montage : seules les arêtes reliant les nœuds de l'infraction sont montrées
          const inMontage = activeInfraction.edge_ids && activeInfraction.edge_ids.includes(e.id);
          const connectsMontage = activeInfraction.node_ids.includes(e.from) && activeInfraction.node_ids.includes(e.to);
          isEdgeHighlighted = inMontage || connectsMontage;
          isEdgeVisible = isEdgeHighlighted;
        }} else {{
          const meetsCutoff = (e.amount_usd >= currentAmountCutoff) || (currentAmountCutoff === 0 && e.amount_usd === 0);
          const fromVisible = highlightedNodeIds.has(e.from);
          const toVisible = highlightedNodeIds.has(e.to);

          if (currentStatusFilter === 'suspicious') {{
            // Mode suspects : arêtes UNIQUEMENT entre suspects ! Fin du spaghetti bleu !
            isEdgeHighlighted = e.is_suspicious && fromVisible && toVisible;
            isEdgeVisible = isEdgeHighlighted;
          }} else {{
            isEdgeHighlighted = meetsCutoff && fromVisible && toVisible;
            isEdgeVisible = meetsCutoff && (fromVisible || toVisible);
          }}
        }}

        return {{
          id: e.id,
          hidden: !isEdgeVisible,
          opacity: isEdgeHighlighted ? 1.0 : 0.04
        }};
      }});
      edgesDataSet.update(edgeUpdates);
    }}

    function highlightNeighbors(selectedId) {{
      if (activeInfractionId) return; // Ne pas casser le mode montage

      const neighbors = new Set(network.getConnectedNodes(selectedId));
      neighbors.add(selectedId);

      nodesDataSet.update(NODES.map(n => ({{
        id: n.id,
        opacity: neighbors.has(n.id) ? 1.0 : 0.12
      }})));

      const connectedEdges = new Set(network.getConnectedEdges(selectedId));
      edgesDataSet.update(EDGES.map(e => ({{
        id: e.id,
        hidden: !connectedEdges.has(e.id),
        opacity: connectedEdges.has(e.id) ? 1.0 : 0.05
      }})));
    }}

    // -----------------------------------------------------------------------
    // Navigation interactive vers un nœud
    // -----------------------------------------------------------------------
    function navigateToNode(nodeId) {{
      if (!nodeId) return;
      // Si une infraction était sélectionnée et que le nœud n'est pas dedans, réinitialiser
      if (activeInfractionId) {{
        const infr = INFRACTIONS.find(i => i.id === activeInfractionId);
        if (infr && !infr.node_ids.includes(nodeId)) {{
          selectInfraction(null);
        }}
      }}
      network.focus(nodeId, {{
        scale: 1.3,
        animation: false
      }});
      pinnedNodeId = nodeId;
      openInspector(nodeId, true);
      highlightNeighbors(nodeId);
      showToast("Centré sur l'entité");
    }}

    // -----------------------------------------------------------------------
    // Sélection et focus sur une infraction (Mode Montage)
    // -----------------------------------------------------------------------
    function selectInfraction(infrId) {{
      activeInfractionId = infrId;

      document.querySelectorAll('.infr-pill').forEach(btn => {{
        btn.classList.toggle('active', btn.dataset.infrId === (infrId || 'all'));
      }});

      const banner = document.getElementById('montageBanner');
      if (infrId) {{
        const infr = INFRACTIONS.find(i => i.id === infrId);
        if (!infr) return;

        banner.classList.add('active');
        document.getElementById('montageBannerTitle').textContent = `Montage #${{infr.index}} : ${{infr.title}}`;
        document.getElementById('montageBannerSub').textContent =
          `Montant : $${{infr.amount_usd.toLocaleString()}} USD • Corroboration OCR : ${{Math.round(infr.confidence_score * 100)}}% • ${{infr.node_ids.length}} entités`;

        applyFilters();

        // Cadrer la caméra sur le montage sans animation
        network.fit({{
          nodes: infr.node_ids,
          animation: false
        }});

        // Ouvrir l'inspecteur d'infraction
        openInfractionInspector(infr);
        showToast(`Montage isolé : ${{infr.title}}`);
      }} else {{
        banner.classList.remove('active');
        applyFilters();
        closeInspector();
        network.fit({{ animation: false }});
        showToast("Vue d'ensemble rétablie");
      }}
    }}

    function openInfractionInspector(infr) {{
      document.getElementById('inspStatus').textContent = 'Infraction qualifiée';
      const badge = document.getElementById('inspBadge');
      badge.textContent = 'MONTAGE ISOLÉ';
      badge.style.background = '#fee2e2';
      badge.style.color = '#991b1b';

      document.getElementById('inspName').textContent = infr.title;
      document.getElementById('inspId').textContent = infr.type;
      document.getElementById('inspTypeCountry').textContent = `Montant : $${{infr.amount_usd.toLocaleString()}} USD`;
      document.getElementById('inspBrandes').textContent = `Confiance OCR : ${{Math.round(infr.confidence_score * 100)}}%`;

      const tagsContainer = document.getElementById('inspPiecesTags');
      tagsContainer.innerHTML = '';
      (infr.pieces || []).forEach(pId => {{
        const span = document.createElement('span');
        span.className = 'piece-tag';
        span.textContent = pId;
        span.onclick = () => openPieceModal(pId);
        tagsContainer.appendChild(span);
      }});

      document.getElementById('inspHash').textContent = `Base légale : ${{infr.legal_basis.join(' ; ')}}`;

      const container = document.getElementById('inspInfrContainer');
      let stepsHtml = '';
      if (infr.steps && infr.steps.length > 0) {{
        stepsHtml = '<div style="font-weight:700; font-size:11px; margin-top:4px;">Chronologie des flux :</div>';
        infr.steps.forEach(s => {{
          stepsHtml += `
            <div class="infr-step-row">
              <strong>${{s.date || 'Date non précisée'}}</strong> : ${{s.from}} ➔ ${{s.to}}
              <div style="color:#b91c1c; font-weight:700;">$${{s.amount_usd.toLocaleString()}} USD</div>
              <div style="font-size:10px; color:#64748b;">Pièces : ${{s.pieces.join(', ')}}</div>
            </div>
          `;
        }});
      }}

      container.innerHTML = `
        <div class="infr-card">
          <div class="infr-card-title">${{infr.title}}</div>
          <div style="font-size:11px; color:#1e293b;">${{infr.summary_note}}</div>
          ${{stepsHtml}}
          <div class="infr-card-legal">
            <strong>Recommandations judiciaires :</strong>
            <div>${{infr.recommendations.join('<br>')}}</div>
          </div>
        </div>
      `;

      // Afficher distinctement les opérateurs du circuit et les personnes/prête-noms derrière
      const titleElem = document.getElementById('inspTransTitle');
      if (titleElem) titleElem.textContent = 'Chaîne de contrôle & Opérateurs du montage :';

      const transList = document.getElementById('inspTrans');
      transList.innerHTML = '';

      // 1. Sociétés opératrices (circuit de façade)
      if (infr.core_nodes && infr.core_nodes.length > 0) {{
        const sepCore = document.createElement('li');
        sepCore.className = 'trans-group-header';
        sepCore.innerHTML = '<strong>SOCIÉTÉS DU CIRCUIT FINANCIER</strong>';
        transList.appendChild(sepCore);

        infr.core_nodes.forEach(cNode => {{
          const li = document.createElement('li');
          li.className = 'trans-item';
          li.innerHTML = `
            <div class="trans-top">
              <button class="nav-node-btn" onclick="navigateToNode('${{cNode.id}}')">${{cNode.name}}</button>
              <span class="badge-role badge-role-core">Opérateur flux</span>
            </div>
            <div style="font-size:10px; color:#64748b;">Société directement impliquée dans la transaction</div>
          `;
          transList.appendChild(li);
        }});
      }}

      // 2. Personnes physiques, prête-noms et fiduciaires derrière ces sociétés
      if (infr.controllers && infr.controllers.length > 0) {{
        const sepCtrl = document.createElement('li');
        sepCtrl.className = 'trans-group-header';
        sepCtrl.style.marginTop = '6px';
        sepCtrl.innerHTML = '<strong>PERSONNES & PRÊTE-NOMS DERRIÈRE CE CIRCUIT</strong>';
        transList.appendChild(sepCtrl);

        infr.controllers.forEach(ctrl => {{
          const isPerson = ctrl.entity_type === 'PersonnePhysique' || ctrl.role.includes('Bénéficiaire') || ctrl.role.includes('UBO');
          const isNominee = ctrl.role.includes('Prête-nom') || ctrl.role.includes('Actionnaire');
          const badgeClass = isPerson ? 'badge-role-ubo' : (isNominee ? 'badge-role-nominee' : 'badge-role-trust');

          const li = document.createElement('li');
          li.className = 'trans-item';
          li.innerHTML = `
            <div class="trans-top">
              <button class="nav-node-btn" onclick="navigateToNode('${{ctrl.id}}')">${{ctrl.name}}</button>
              <span class="badge-role ${{badgeClass}}">${{ctrl.entity_type}}</span>
            </div>
            <div style="font-size:11px; font-weight:600; color:#1e293b;">${{ctrl.role}}</div>
            <div style="font-size:10px; color:#64748b;">Lié à : ${{ctrl.target}}</div>
          `;
          transList.appendChild(li);
        }});
      }} else {{
        infr.node_ids.forEach(nId => {{
          const node = NODES.find(n => n.id === nId);
          if (!node) return;
          const li = document.createElement('li');
          li.className = 'trans-item';
          li.innerHTML = `
            <div class="trans-top">
              <button class="nav-node-btn" onclick="navigateToNode('${{node.id}}')">${{node.name}}</button>
              <span style="font-size:10px; color:#64748b;">${{node.entity_type}}</span>
            </div>
          `;
          transList.appendChild(li);
        }});
      }}

      document.getElementById('inspector').hidden = false;
    }}

    // -----------------------------------------------------------------------
    // Inspecteur d'entité
    // -----------------------------------------------------------------------
    function openInspector(nodeId, isPinned) {{
      const node = NODES.find(n => n.id === nodeId);
      if (!node) return;

      const titleElem = document.getElementById('inspTransTitle');
      if (titleElem) titleElem.textContent = 'Liens & Transactions directs (clic pour naviguer) :';

      document.getElementById('inspInfrContainer').innerHTML = '';
      document.getElementById('inspStatus').textContent = node.status_text;

      const badge = document.getElementById('inspBadge');
      if (isPinned) {{
        badge.textContent = 'FIGÉ';
        badge.style.background = '#dbeafe';
        badge.style.color = '#1e40af';
      }} else {{
        badge.textContent = 'APERÇU (clic pour figer)';
        badge.style.background = '#f1f5f9';
        badge.style.color = '#64748b';
      }}

      document.getElementById('inspName').textContent = node.name;
      document.getElementById('inspId').textContent = node.id;
      document.getElementById('inspTypeCountry').textContent = `${{node.entity_type}} (${{node.country}})`;
      document.getElementById('inspBrandes').textContent = node.betweenness.toFixed(4);

      const tagsContainer = document.getElementById('inspPiecesTags');
      tagsContainer.innerHTML = '';
      const piecesList = node.pieces && node.pieces.length > 0 ? node.pieces : node.doc_ref.split(', ');
      piecesList.forEach(pId => {{
        pId = pId.trim();
        if (pId && pId !== 'N/A') {{
          const span = document.createElement('span');
          span.className = 'piece-tag';
          span.textContent = pId;
          span.onclick = () => openPieceModal(pId);
          tagsContainer.appendChild(span);
        }}
      }});

      document.getElementById('inspHash').textContent = node.proof_sha || 'Empreinte conforme';

      const transList = document.getElementById('inspTrans');
      transList.innerHTML = '';
      if (!node.transactions || node.transactions.length === 0) {{
        transList.innerHTML = '<li class="trans-item" style="color:#64748b;">Aucun lien direct répertorié</li>';
      }} else {{
        node.transactions.forEach(t => {{
          const li = document.createElement('li');
          li.className = 'trans-item';
          const dirSymbol = t.dir === 'out' ? '➔' : '⬅';
          const color = t.dir === 'out' ? '#dc2626' : '#2563eb';

          let detailText = '';
          if (t.amount > 0) {{
            detailText = `$${{t.amount.toLocaleString()}} USD`;
          }} else {{
            const relMap = {{
              'uses_agent': 'Agent / fiduciaire',
              'director_of': 'Administrateur',
              'nominee_director_of': 'Prête-nom',
              'beneficial_owner_of': 'Bénéficiaire effectif (UBO)',
              'shareholder_of': 'Actionnaire',
              'registered_office': 'Domiciliation'
            }};
            detailText = relMap[t.rel_type] || t.rel_type.replace(/_/g, ' ');
          }}

          let pieceBadges = '';
          (t.pieces || []).forEach(p => {{
            pieceBadges += `<span class="piece-tag" onclick="openPieceModal('${{p}}')">${{p}}</span> `;
          }});

          li.innerHTML = `
            <div class="trans-top">
              <button class="nav-node-btn" onclick="navigateToNode('${{t.counterparty_id}}')">
                <span style="color:${{color}}">${{dirSymbol}}</span> ${{t.counterparty}}
              </button>
              <strong style="font-variant-numeric:tabular-nums;">${{detailText}}</strong>
            </div>
            <div>${{pieceBadges}}</div>
          `;
          transList.appendChild(li);
        }});
      }}

      document.getElementById('inspector').hidden = false;
    }}

    function closeInspector() {{
      pinnedNodeId = null;
      document.getElementById('inspector').hidden = true;
    }}

    // -----------------------------------------------------------------------
    // Visionneuse de document (ISO/IEC 27037)
    // -----------------------------------------------------------------------
    function openPieceModal(pieceId) {{
      const piece = PIECES[pieceId];
      const modal = document.getElementById('pieceModal');
      document.getElementById('modalPieceTitle').textContent = `Cote Judiciaire : ${{pieceId}}`;

      if (!piece) {{
        document.getElementById('modalPieceType').textContent = 'Document répertorié';
        document.getElementById('modalPreviewBox').innerHTML = `<p style="color:#64748b;">Fichier introuvable en cache local.</p>`;
        document.getElementById('modalPieceHash').textContent = '-';
        document.getElementById('modalPieceEntities').innerHTML = '';
        document.getElementById('modalPieceTransfers').innerHTML = '';
        modal.classList.add('open');
        return;
      }}

      document.getElementById('modalPieceType').textContent = `Nature : ${{piece.doc_type}}`;
      document.getElementById('modalPieceHash').textContent = piece.sha256;

      const previewBox = document.getElementById('modalPreviewBox');
      if (piece.is_image) {{
        previewBox.innerHTML = `
          <img src="${{piece.rel_path}}" class="modal-preview-img" alt="Scan de la pièce ${{pieceId}}"
               onerror="this.parentElement.innerHTML='<p style=\\'color:#64748b;\\'>Image inaccessible : ${{piece.rel_path}}</p>'">
        `;
      }} else if (piece.is_pdf) {{
        previewBox.innerHTML = `
          <iframe src="${{piece.rel_path}}" style="width:100%; height:480px; border:none;"
                  onerror="this.parentElement.innerHTML='<p>PDF téléchargeable.</p>'"></iframe>
        `;
      }} else {{
        previewBox.innerHTML = `<p style="color:#64748b;">Format de fichier non prévisualisable.</p>`;
      }}

      const entList = document.getElementById('modalPieceEntities');
      entList.innerHTML = '';
      (piece.entities || []).forEach(e => {{
        const li = document.createElement('li');
        li.textContent = e;
        entList.appendChild(li);
      }});

      const transList = document.getElementById('modalPieceTransfers');
      transList.innerHTML = '';
      (piece.transfers || []).forEach(t => {{
        const li = document.createElement('li');
        li.style.padding = '3px 0';
        li.innerHTML = `<strong>${{t.payer}}</strong> ➔ <strong>${{t.payee}}</strong> : $${{t.amount.toLocaleString()}} ${{t.currency}} (${{t.date || 'date ?'}})`;
        transList.appendChild(li);
      }});

      modal.classList.add('open');
    }}

    function closePieceModal() {{
      document.getElementById('pieceModal').classList.remove('open');
    }}

    // -----------------------------------------------------------------------
    // Volet Rapport d'investigation
    // -----------------------------------------------------------------------
    function renderReportDrawer() {{
      const container = document.getElementById('reportContent');
      let html = '';

      // Cadrage judiciaire
      html += `
        <div style="background:#eff6ff; border-left:3px solid #2563eb; padding:8px 10px; font-size:11px; color:#1e3a8a; line-height:1.4;">
          <strong>Cadrage de l'enquête :</strong><br>
          Le dossier rassemble l'ensemble des 42 pièces saisies. Ce volet sépare les <strong>infractions pénales qualifiées</strong> (circuits isolés) de la <strong>cartographie d'ensemble du réseau</strong> (organigramme global et soldes de tous les comptes saisis).
        </div>
      `;

      // Section 1 : Infractions
      html += `
        <div class="report-section">
          <div class="report-section-title">1. Infractions Financières Caractérisées</div>
      `;
      if (INFRACTIONS.length === 0) {{
        html += '<p style="color:#64748b;">Aucune anomalie topologique qualifiée.</p>';
      }} else {{
        INFRACTIONS.forEach(i => {{
          html += `
            <div style="background:#fef2f2; border:1px solid #fecaca; padding:8px; margin-bottom:8px;">
              <div style="font-weight:700; color:#991b1b; display:flex; justify-content:space-between;">
                <span>#${{i.index}} ${{i.title}}</span>
                <span>${{i.amount_usd > 0 ? '$' + i.amount_usd.toLocaleString() + ' USD' : 'UBO / Prête-nom'}}</span>
              </div>
              <div style="font-size:11px; margin:4px 0;">${{i.summary_note}}</div>
              <div style="font-size:10px; color:#7f1d1d; margin-bottom:6px;">
                <strong>Base légale :</strong> ${{i.legal_basis.join(' ; ')}}
              </div>
              <button class="btn" style="padding:2px 6px; font-size:10px;" onclick="selectInfraction('${{i.id}}')">
                Isoler ce montage sur le graphe
              </button>
            </div>
          `;
        }});
      }}
      html += '</div>';

      // Section 2 : Prête-noms du réseau
      html += `
        <div class="report-section">
          <div class="report-section-title">2. Prête-noms du Réseau Saisi (Cartographie Globale)</div>
          <div style="font-size:11px; color:#64748b; margin-bottom:6px;">
            Acteurs apparaissant comme prête-noms professionnels pour administrer des sociétés écrans en cascade.
          </div>
      `;
      (FINDINGS.portfolios || []).slice(0, 6).forEach(p => {{
        const node = NODES.find(n => n.name === p.name);
        const nodeId = node ? node.id : '';
        html += `
          <div style="display:flex; justify-content:space-between; padding:3px 0; border-bottom:1px solid #f1f5f9;">
            <span class="report-entity-link" onclick="navigateToNode('${{nodeId}}')">${{p.name}}</span>
            <span><strong>${{p.n_companies}}</strong> sociétés ${{p.nominee_profile ? '<span style="color:#b91c1c; font-weight:700;">(prête-nom)</span>' : ''}}</span>
          </div>
        `;
      }});
      html += '</div>';

      // Section 3 : Destination globale des fonds
      html += `
        <div class="report-section">
          <div class="report-section-title">3. Destination Globale des Fonds (Comptes Saisis)</div>
          <div style="font-size:11px; color:#64748b; margin-bottom:6px;">
            Solde net cumulé de tous les flux découverts dans le dossier (au-delà du seul circuit délictueux).
          </div>
      `;
      (FINDINGS.money_ranking || []).slice(0, 6).forEach(m => {{
        const node = NODES.find(n => n.name === m.name);
        const nodeId = node ? node.id : '';
        html += `
          <div style="display:flex; justify-content:space-between; padding:3px 0; border-bottom:1px solid #f1f5f9;">
            <span class="report-entity-link" onclick="navigateToNode('${{nodeId}}')">${{m.name}}</span>
            <strong style="color:${{m.net_usd > 0 ? '#15803d' : '#475569'}};">$${{m.net_usd.toLocaleString()}} USD</strong>
          </div>
        `;
      }});
      html += '</div>';

      // Section 4 : Vigilance Enquêteur
      if (FINDINGS.vigilance) {{
        const v = FINDINGS.vigilance;
        html += `
          <div class="report-section">
            <div class="report-section-title">4. Contrôles & Vigilance Enquêteur</div>
            <div>• Variantes de noms fusionnées : <strong>${{(v.name_merges || []).length}}</strong></div>
            <div>• Montants non corroborés OCR : <strong>${{(v.uncorroborated_amounts || []).length}}</strong></div>
            <div>• Entités écartées : <strong>${{(v.rejected_entities || []).length}}</strong></div>
          </div>
        `;
      }}

      container.innerHTML = html;
    }}

    // -----------------------------------------------------------------------
    // Initialisation
    // -----------------------------------------------------------------------
    document.addEventListener('DOMContentLoaded', () => {{
      initGraph();

      // Générer les pills d'infractions
      const bar = document.getElementById('infrSelectorBar');
      INFRACTIONS.forEach(infr => {{
        const btn = document.createElement('button');
        btn.className = 'infr-pill';
        btn.dataset.infrId = infr.id;
        btn.textContent = infr.badge;
        btn.onclick = () => selectInfraction(infr.id);
        bar.appendChild(btn);
      }});

      document.getElementById('btnInfrAll').onclick = () => selectInfraction(null);
      document.getElementById('btnResetMontage').onclick = () => selectInfraction(null);
      document.getElementById('btnFitMontage').onclick = () => {{
        if (activeInfractionId) {{
          const infr = INFRACTIONS.find(i => i.id === activeInfractionId);
          if (infr) network.fit({{ nodes: infr.node_ids, animation: false }});
        }}
      }};

      // Fermeture des tiroirs et modales
      document.getElementById('inspClose').onclick = closeInspector;
      document.getElementById('btnModalClose').onclick = closePieceModal;
      document.getElementById('pieceModal').onclick = (e) => {{
        if (e.target.id === 'pieceModal') closePieceModal();
      }};
      document.addEventListener('keydown', (e) => {{
        if (e.key === 'Escape') {{
          closePieceModal();
          closeInspector();
        }}
      }});

      document.getElementById('btnToggleReport').onclick = () => {{
        const drawer = document.getElementById('reportDrawer');
        drawer.classList.toggle('open');
        document.getElementById('btnToggleReport').classList.toggle('active', drawer.classList.contains('open'));
        if (drawer.classList.contains('open')) renderReportDrawer();
      }};
      document.getElementById('btnReportClose').onclick = () => {{
        document.getElementById('reportDrawer').classList.remove('open');
        document.getElementById('btnToggleReport').classList.remove('active');
      }};

      document.getElementById('btnCopyHash').onclick = () => {{
        const hash = document.getElementById('inspHash').textContent;
        navigator.clipboard.writeText(hash).then(() => showToast('Copié dans le presse-papiers'));
      }};
      document.getElementById('btnCopyModalHash').onclick = () => {{
        const hash = document.getElementById('modalPieceHash').textContent;
        navigator.clipboard.writeText(hash).then(() => showToast('SHA-256 copié'));
      }};

      // Recherche
      const searchBox = document.getElementById('searchBox');
      searchBox.addEventListener('input', (e) => {{
        const q = e.target.value.toLowerCase().trim();
        if (!q) {{
          applyFilters();
          return;
        }}
        let firstMatch = null;
        NODES.forEach(n => {{
          const match = n.name.toLowerCase().includes(q) || n.id.toLowerCase().includes(q) || n.country.toLowerCase().includes(q);
          if (match && !firstMatch) firstMatch = n.id;
        }});
        if (firstMatch) navigateToNode(firstMatch);
      }});

      // Filtres par type
      const typeBtns = document.querySelectorAll('.btn-type');
      typeBtns.forEach(btn => {{
        btn.addEventListener('click', () => {{
          typeBtns.forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          currentTypeFilter = btn.dataset.type;
          applyFilters();
        }});
      }});

      // Filtres par statut
      const statusBtns = document.querySelectorAll('.btn-status');
      statusBtns.forEach(btn => {{
        btn.addEventListener('click', () => {{
          statusBtns.forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          currentStatusFilter = btn.dataset.status;
          applyFilters();
        }});
      }});

      // Seuil financier slider
      const amountSlider = document.getElementById('amountSlider');
      const cutoffVal = document.getElementById('cutoffVal');
      amountSlider.addEventListener('input', (e) => {{
        currentAmountCutoff = parseFloat(e.target.value) || 0;
        cutoffVal.textContent = currentAmountCutoff > 0 ? '$' + currentAmountCutoff.toLocaleString() : '$0';
        applyFilters();
      }});

      document.getElementById('btnRecenter').onclick = () => network.fit({{ animation: false }});

      // Export PNG
      document.getElementById('btnExport').onclick = () => {{
        const canvas = document.querySelector('#network canvas');
        if (!canvas) return;
        const exportCanvas = document.createElement('canvas');
        exportCanvas.width = canvas.width;
        exportCanvas.height = canvas.height;
        const ctx = exportCanvas.getContext('2d');
        ctx.fillStyle = '#f8fafc';
        ctx.fillRect(0, 0, exportCanvas.width, exportCanvas.height);
        ctx.drawImage(canvas, 0, 0);

        const a = document.createElement('a');
        a.download = 'fin_enclave_montage.png';
        a.href = exportCanvas.toDataURL('image/png');
        a.click();
        showToast('Capture PNG exportée');
      }};
    }});
  </script>
</body>
</html>
"""

    out_file.write_text(html_content, encoding="utf-8")

    if auto_open:
        webbrowser.open(out_file.resolve().as_uri())

    return out_file
