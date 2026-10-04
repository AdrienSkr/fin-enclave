import time
from dataclasses import dataclass, field
from datetime import date

import networkx as nx

BRANDES_SAMPLING_THRESHOLD = 5_000
BRANDES_SAMPLE_SIZE = 500


@dataclass
class DetectionResult:
    """Résultat complet de l'analyse topologique déterministe."""

    scc_components: list[list[str]]
    closed_cycles: list[list[str]]
    pivot_node: str
    pivot_name: str
    pivot_intermediary_node: str
    pivot_intermediary_name: str
    betweenness_scores: dict[str, float]
    suspicious_nodes: set[str]
    total_cycle_volume_usd: float
    tarjan_execution_ms: float
    brandes_execution_ms: float
    cycle_details: list[dict] = field(default_factory=list)
    rejected_cycles_count: int = 0
    params: dict = field(default_factory=dict)
    smurfing_findings: list[dict] = field(default_factory=list)


def flow_view(G: nx.DiGraph) -> nx.DiGraph:
    """
    Sous-graphe des seuls flux financiers réels (couche 'flow', montant > 0).
    Les liens de détention et de mandat ne transportent pas d'argent : ils ne peuvent pas
    former un circuit de blanchiment.
    """
    F = nx.DiGraph()
    F.add_nodes_from(G.nodes(data=True))
    for u, v, data in G.edges(data=True):
        layers = data.get("layers", ["flow"])
        amount = float(data.get("amount_usd", 0.0) or 0.0)
        if "flow" in layers and amount > 0:
            F.add_edge(u, v, **data)
    return F


class GraphDetector:
    """
    Moteur d'analyse topologique déterministe sur CPU.
    - Tarjan (O(V+E)) : composantes fortement connexes, élagage des sommets hors boucle.
    - Johnson borné (length_bound) : énumération des cycles dans chaque SCC non triviale.
    - Filtre de conservation de masse par étape + cohérence chronologique.
    - Brandes : centralité d'intermédiarité (échantillonnée au-delà de 5 000 sommets).
    """

    def __init__(self, graph: nx.DiGraph):
        self.G = graph

    @staticmethod
    def _rotate_to_earliest(cycle: list[str], F: nx.DiGraph) -> list[str]:
        """Fait démarrer le cycle sur l'arc le plus ancien (et montant le plus élevé si même date)."""
        n = len(cycle)
        dates = [F[cycle[i]][cycle[(i + 1) % n]].get("date", "") or "" for i in range(n)]
        amounts = [
            float(F[cycle[i]][cycle[(i + 1) % n]].get("amount_usd", 0.0) or 0.0) for i in range(n)
        ]
        if any(dates):
            # Priorité à la date la plus ancienne ; en cas d'égalité (ou même date),
            # l'injection de départ est l'arc au montant le plus élevé (-amount).
            start = min(range(n), key=lambda i: (dates[i] or "9999", -amounts[i]))
            return cycle[start:] + cycle[:start]
        start = min(range(n), key=lambda i: -amounts[i])
        return cycle[start:] + cycle[:start]

    def _evaluate_cycle(
        self, cycle: list[str], F: nx.DiGraph, tolerance: float, enforce_dates: bool
    ) -> dict | None:
        """Retourne les métriques du cycle s'il est plausible, None s'il est rejeté."""
        n = len(cycle)
        edges = [F[cycle[i]][cycle[(i + 1) % n]] for i in range(n)]
        amounts = [float(e.get("amount_usd", 0.0)) for e in edges]
        dates = [e.get("date", "") or "" for e in edges]

        # Conservation de masse par étape (commission de transit ou marge, pas de dilution)
        step_dev = [
            abs(amounts[i] - amounts[i + 1]) / max(amounts[i], amounts[i + 1]) for i in range(n - 1)
        ]
        if any(d > tolerance for d in step_dev):
            return None

        # Cohérence chronologique : l'argent ne peut pas sortir avant d'être entré
        if enforce_dates and all(dates) and any(dates[i] > dates[i + 1] for i in range(n - 1)):
            return None

        steps = []
        for i in range(n):
            e = edges[i]
            steps.append(
                {
                    "from": self.G.nodes[cycle[i]].get("name", cycle[i]),
                    "to": self.G.nodes[cycle[(i + 1) % n]].get("name", cycle[(i + 1) % n]),
                    "amount_usd": amounts[i],
                    "rel_type": e.get("rel_type", "transfers_to"),
                    "date": dates[i],
                    "doc_reference": e.get("doc_reference", ""),
                    "tx_ids": list(e.get("tx_ids", [])),
                }
            )
        return {
            "cycle_nodes": [self.G.nodes[c].get("name", c) for c in cycle],
            "cycle_ids": list(cycle),
            "volume_usd": amounts[0],  # montant réellement injecté (entrée du circuit)
            "entry_amount_usd": amounts[0],
            "exit_amount_usd": amounts[-1],
            "leakage_pct": round((1.0 - amounts[-1] / amounts[0]) * 100, 2),
            "max_step_deviation_pct": round(max(step_dev, default=0.0) * 100, 2),
            "steps": steps,
        }

    def detect_smurfing(
        self,
        threshold_usd: float = 10_000.0,
        min_mules: int = 5,
        window_days: int = 7,
        F: nx.DiGraph | None = None,
    ) -> list[dict]:
        """
        Schtroumpfage (fan-out -> fan-in) : un émetteur fractionne des virements sous le seuil
        vers >= min_mules comptes relais qui convergent tous vers un même collecteur,
        dans une fenêtre de temps bornée. Déterministe, sans cycle requis.
        """
        F = F if F is not None else flow_view(self.G)
        findings: list[dict] = []
        for src in F.nodes:
            mules = {m for m in F.successors(src) if F[src][m]["amount_usd"] < threshold_usd}
            if len(mules) < min_mules:
                continue
            converge: dict[str, list[str]] = {}
            for m in mules:
                for c in F.successors(m):
                    if c != src and F[m][c]["amount_usd"] < threshold_usd:
                        converge.setdefault(c, []).append(m)
            for collector, relays in converge.items():
                if len(relays) < min_mules:
                    continue
                dates = [
                    d
                    for m in relays
                    for d in (F[src][m].get("date", ""), F[m][collector].get("date", ""))
                    if d
                ]
                if dates:
                    span = (date.fromisoformat(max(dates)) - date.fromisoformat(min(dates))).days
                    if span > window_days:
                        continue
                else:
                    span = -1
                total_in = sum(F[src][m]["amount_usd"] for m in relays)
                total_out = sum(F[m][collector]["amount_usd"] for m in relays)
                findings.append(
                    {
                        "source": src,
                        "collector": collector,
                        "mules": sorted(relays),
                        "n_mules": len(relays),
                        "total_in_usd": round(total_in, 2),
                        "total_collected_usd": round(total_out, 2),
                        "span_days": span,
                        "downstream": sorted(F.successors(collector)),
                        "tx_ids": sorted(
                            t
                            for m in relays
                            for t in (
                                *F[src][m].get("tx_ids", []),
                                *F[m][collector].get("tx_ids", []),
                            )
                        ),
                    }
                )
        return findings

    def run_detection(
        self,
        min_cycle_len: int = 2,
        max_cycle_len: int = 8,
        step_tolerance: float = 0.15,
        enforce_dates: bool = True,
        smurf_threshold_usd: float = 10_000.0,
        smurf_min_mules: int = 5,
        smurf_window_days: int = 7,
    ) -> DetectionResult:
        """Exécute l'ensemble des analyses topologiques avec chronométrage précis."""
        # 1. Tarjan sur la couche flux, puis Johnson borné dans chaque SCC non triviale
        t0 = time.perf_counter()
        F = flow_view(self.G)
        sccs = [c for c in nx.strongly_connected_components(F) if len(c) >= min_cycle_len]
        scc_components = [sorted(c) for c in sccs]
        scc_components.sort(key=lambda c: (-len(c), c[0] if c else ""))

        candidates: list[dict] = []
        rejected = 0
        seen_cycles: set[tuple[str, ...]] = set()
        for comp in scc_components:
            sub = F.subgraph(comp)
            for raw in nx.simple_cycles(sub, length_bound=max_cycle_len):
                if len(raw) < min_cycle_len:
                    continue
                cycle = self._rotate_to_earliest(list(raw), F)
                cycle_key = tuple(cycle)
                if cycle_key in seen_cycles:
                    continue
                seen_cycles.add(cycle_key)
                detail = self._evaluate_cycle(cycle, F, step_tolerance, enforce_dates)
                if detail is None:
                    rejected += 1
                else:
                    candidates.append(detail)
        tarjan_ms = (time.perf_counter() - t0) * 1000

        # 2. Volume sans double comptage : cycles retenus gloutonnement, disjoints en arcs
        candidates.sort(key=lambda d: (-d["volume_usd"], d["cycle_ids"]))
        used_edges: set[tuple[str, str]] = set()
        total_volume = 0.0
        closed_cycles: list[list[str]] = []
        cycle_details: list[dict] = []
        suspicious_nodes: set[str] = set()
        for d in candidates:
            ids = d["cycle_ids"]
            cyc_edges = {(ids[i], ids[(i + 1) % len(ids)]) for i in range(len(ids))}
            d["counted_in_volume"] = not (cyc_edges & used_edges)
            if d["counted_in_volume"]:
                used_edges |= cyc_edges
                total_volume += d["volume_usd"]
            closed_cycles.append(ids)
            cycle_details.append(d)
            suspicious_nodes.update(ids)

        # 2b. Éventails de schtroumpfage (fan-out -> fan-in sous le seuil déclaratif)
        smurfing = self.detect_smurfing(smurf_threshold_usd, smurf_min_mules, smurf_window_days, F)
        for s in smurfing:
            suspicious_nodes.update([s["source"], s["collector"], *s["mules"]])

        # 3. Brandes (échantillonné sur les très gros graphes, graine fixe = reproductible)
        t1 = time.perf_counter()
        n_nodes = self.G.number_of_nodes()
        if n_nodes > BRANDES_SAMPLING_THRESHOLD:
            betweenness = nx.betweenness_centrality(
                self.G, k=BRANDES_SAMPLE_SIZE, normalized=True, seed=42
            )
        else:
            betweenness = nx.betweenness_centrality(self.G, normalized=True)
        brandes_ms = (time.perf_counter() - t1) * 1000

        sorted_betweenness = sorted(betweenness.items(), key=lambda x: x[1], reverse=True)
        pivot_node = sorted_betweenness[0][0] if sorted_betweenness else ""
        pivot_name = self.G.nodes[pivot_node].get("name", pivot_node) if pivot_node else ""

        intermediaries = [
            (n, score)
            for n, score in sorted_betweenness
            if self.G.nodes[n].get("entity_type") == "Intermediaire"
        ]
        pivot_inter_node = intermediaries[0][0] if intermediaries else ""
        pivot_inter_name = (
            self.G.nodes[pivot_inter_node].get("name", pivot_inter_node) if pivot_inter_node else ""
        )

        return DetectionResult(
            scc_components=scc_components,
            closed_cycles=closed_cycles,
            pivot_node=pivot_node,
            pivot_name=pivot_name,
            pivot_intermediary_node=pivot_inter_node,
            pivot_intermediary_name=pivot_inter_name,
            betweenness_scores=betweenness,
            suspicious_nodes=suspicious_nodes,
            total_cycle_volume_usd=total_volume,
            tarjan_execution_ms=round(tarjan_ms, 2),
            brandes_execution_ms=round(brandes_ms, 2),
            cycle_details=cycle_details,
            rejected_cycles_count=rejected,
            smurfing_findings=smurfing,
            params={
                "min_cycle_len": min_cycle_len,
                "max_cycle_len": max_cycle_len,
                "step_tolerance": step_tolerance,
                "enforce_dates": enforce_dates,
                "brandes_sampled": n_nodes > BRANDES_SAMPLING_THRESHOLD,
            },
        )
