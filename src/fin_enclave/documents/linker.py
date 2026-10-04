"""
Mise en relation inter-pièces : les entités extraites de pièces sans lien entre elles sont
résolues (Record Linkage) puis assemblées en un graphe orienté de détention / contrôle.

Orientation identique au connecteur ICIJ (dirigeant/intermédiaire -> société, société -> adresse)
pour que les mêmes détecteurs structurels s'appliquent au graphe reconstruit. Les virements
forment la couche 'flow' (payeur -> bénéficiaire, montant en USD), sur laquelle tournent les
détecteurs de circuits et de fractionnement.
"""

import logging

import networkx as nx

from ..graph.resolver import EntityResolver, jaro_winkler_similarity, normalize_entity_name
from ..schemas import ProofPoint
from .models import OWNERSHIP_ROLES, PieceExtraction

# Les sociétés-prête-noms apparaissent comme 'Shareholder' ou 'Director' : on résout donc
# sociétés et personnes ensemble ; intermédiaires et adresses restent des catégories à part.
_RESOLUTION_CLASS = {
    "Societe": "Acteur",
    "PersonnePhysique": "Acteur",
    "Intermediaire": "Intermediaire",
    "Adresse": "Adresse",
}
# Taux de référence fixes (approximation documentée dans le rapport, pas un cours du jour)
FX_TO_USD = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "CHF": 1.10}
PAYMENT_DOC_TYPES = {"wire_transfer", "bank_statement", "invoice"}

logger = logging.getLogger("fin_enclave.documents")


def _match_in_piece(name: str, piece: PieceExtraction) -> str | None:
    """Rattache un nom cité dans une relation à une entité extraite de la même pièce."""
    norm = normalize_entity_name(name)
    best, best_score = None, 0.0
    for ent in piece.entities:
        score = jaro_winkler_similarity(norm, normalize_entity_name(ent.name))
        if score > best_score:
            best, best_score = ent.name, score
    return best if best_score >= 0.9 else None


def build_document_graph(
    pieces: list[PieceExtraction],
    threshold: float = 0.9,
    require_grounding: bool = True,
) -> tuple[nx.DiGraph, EntityResolver, dict[str, ProofPoint]]:
    """
    Construit le graphe à partir des extractions. Si `require_grounding`, toute entité que la
    couche OCR indépendante ne retrouve pas sur la pièce est écartée (avec les liens associés).
    """
    # Le modèle ne voit qu'une pièce à la fois : un nom qu'il lit sur une pièce et que l'OCR
    # témoin confirme sur une AUTRE pièce du dossier ne peut pas être une invention.
    attested = [
        (p.piece_id, normalize_entity_name(e.name))
        for p in pieces
        for e in p.entities
        if e.grounded is True
    ]

    def attested_elsewhere(name: str, piece_id: str) -> bool:
        norm = normalize_entity_name(name)
        return bool(norm) and any(
            pid != piece_id and jaro_winkler_similarity(norm, other) >= threshold
            for pid, other in attested
        )

    candidates: list[dict[str, str]] = []
    kind_of: dict[str, str] = {}
    for piece in pieces:
        for i, ent in enumerate(piece.entities):
            if (
                require_grounding
                and ent.grounded is False
                and not attested_elsewhere(ent.name, piece.piece_id)
            ):
                continue
            cid = f"{piece.piece_id}#{i}"
            candidates.append(
                {"id": cid, "name": ent.name, "type": _RESOLUTION_CLASS[ent.kind], "country": ""}
            )
            kind_of[cid] = ent.kind

    resolver = EntityResolver(threshold=threshold)
    resolver.fit_resolve(candidates)

    G = nx.DiGraph()
    ledger: dict[str, ProofPoint] = {
        f"{p.piece_id}/piece": ProofPoint(
            document_sha256=p.file_sha256,
            page_sha256=p.file_sha256,
            cote_judiciaire=p.piece_id,
            page_number=1,
            extracted_value=f"{p.doc_type} ({len(p.entities)} entités, moteur {p.engine})",
            source_file=p.file,
        )
        for p in pieces
    }
    local_ids: dict[tuple[str, str], str] = {}
    for c in candidates:
        canon = resolver.resolve_id(c["id"])
        piece_id = c["id"].split("#")[0]
        local_ids[(piece_id, c["name"])] = canon
        if canon not in G:
            G.add_node(
                canon,
                name=resolver.resolve_name(c["name"]),
                entity_type=kind_of[c["id"]],
                mentions=[],
                country="",
            )
        if piece_id not in G.nodes[canon]["mentions"]:
            G.nodes[canon]["mentions"].append(piece_id)

    sha_of = {p.piece_id: p.file_sha256 for p in pieces}
    for _, data in G.nodes(data=True):
        data["doc_reference"] = ", ".join(data["mentions"][:4]) + (
            f" (+{len(data['mentions']) - 4})" if len(data["mentions"]) > 4 else ""
        )
        data["proof_sha256"] = sha_of[data["mentions"][0]]

    for piece in pieces:
        for k, rel in enumerate(piece.relations):
            if rel.role == "other":  # relation commerciale : hors couche détention / contrôle
                continue
            if piece.doc_type in PAYMENT_DOC_TYPES:  # un paiement n'établit aucune gouvernance
                continue
            src_name = _match_in_piece(rel.source, piece)
            dst_name = _match_in_piece(rel.target, piece)
            src = local_ids.get((piece.piece_id, src_name or ""))
            dst = local_ids.get((piece.piece_id, dst_name or ""))
            if not src or not dst or src == dst:
                continue
            if rel.role == "registered_address":
                src, dst = (dst, src) if G.nodes[src]["entity_type"] == "Adresse" else (src, dst)
            layer = "ownership" if rel.role in OWNERSHIP_ROLES else "control"
            proof = ProofPoint(
                document_sha256=piece.file_sha256,
                page_sha256=piece.file_sha256,
                cote_judiciaire=piece.piece_id,
                page_number=1,
                extracted_value=f"{rel.source} -> {rel.role} -> {rel.target}",
                source_file=piece.file,
                source_row=k + 1,
            )
            ledger[f"{piece.piece_id}/rel/{k + 1}"] = proof
            if G.has_edge(src, dst):
                e = G[src][dst]
                if not e["links"]:
                    e["rel_type"] = rel.role
                if rel.role not in e["links"]:
                    e["links"].append(rel.role)
                if layer not in e["layers"]:
                    e["layers"].append(layer)
                e["pieces"].append(piece.piece_id)
            else:
                G.add_edge(
                    src,
                    dst,
                    rel_type=rel.role,
                    links=[rel.role],
                    layers=[layer],
                    pieces=[piece.piece_id],
                    amount_usd=0.0,
                    doc_reference=piece.piece_id,
                    proof_sha256=piece.file_sha256,
                    transfers=[],
                    tx_ids=[],
                )

        for k, tr in enumerate(piece.transfers):
            src = local_ids.get((piece.piece_id, _match_in_piece(tr.payer, piece) or ""))
            dst = local_ids.get((piece.piece_id, _match_in_piece(tr.payee, piece) or ""))
            if not src or not dst or src == dst:
                continue
            rate = FX_TO_USD.get(tr.currency)
            if rate is None:
                logger.warning("Devise inconnue %s (%s) : virement écarté", tr.currency, piece.file)
                continue
            tx_id = f"{piece.piece_id}/tx/{k + 1}"
            ledger[tx_id] = ProofPoint(
                document_sha256=piece.file_sha256,
                page_sha256=piece.file_sha256,
                cote_judiciaire=piece.piece_id,
                page_number=1,
                extracted_value=(
                    f"{tr.payer} -> {tr.payee} : {tr.amount:,.2f} {tr.currency}"
                    f" ({tr.date.isoformat() if tr.date else 'date illisible'})"
                ),
                source_file=piece.file,
                source_row=k + 1,
            )
            detail = {
                "tx_id": tx_id,
                "piece": piece.piece_id,
                "amount": tr.amount,
                "currency": tr.currency,
                "amount_usd": round(tr.amount * rate, 2),
                "date": tr.date.isoformat() if tr.date else "",
                "amount_corroborated": tr.amount_grounded,
            }
            if not G.has_edge(src, dst):
                G.add_edge(
                    src,
                    dst,
                    rel_type="transfer",
                    links=[],
                    layers=[],
                    pieces=[],
                    amount_usd=0.0,
                    doc_reference=piece.piece_id,
                    proof_sha256=piece.file_sha256,
                    transfers=[],
                    tx_ids=[],
                )
            e = G[src][dst]
            same = next(
                (
                    d
                    for d in e["transfers"]
                    if d["amount"] == tr.amount
                    and d["currency"] == tr.currency
                    and d["date"] == detail["date"]
                ),
                None,
            )
            if same is not None:  # même mouvement attesté par une autre pièce : pas de doublon
                if piece.piece_id not in same["corroborated_by"]:
                    same["corroborated_by"].append(piece.piece_id)
                continue
            detail["corroborated_by"] = [piece.piece_id]
            e["transfers"].append(detail)
            e["tx_ids"].append(tx_id)
            e["amount_usd"] = round(e["amount_usd"] + detail["amount_usd"], 2)
            if "flow" not in e["layers"]:
                e["layers"].append("flow")
            if not e["links"]:
                e["rel_type"] = "transfer"
            if piece.piece_id not in e["pieces"]:
                e["pieces"].append(piece.piece_id)
            dates = [d["date"] for d in e["transfers"] if d["date"]]
            e["date"] = min(dates) if dates else ""
    return G, resolver, ledger
