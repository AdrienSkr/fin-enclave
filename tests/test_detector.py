import networkx as nx

from fin_enclave.graph.detector import GraphDetector


def _edge(G: nx.DiGraph, u: str, v: str, amount: float, layer: str = "flow", date: str = ""):
    G.add_edge(u, v, amount_usd=amount, layers=[layer], date=date, rel_type="fund_transfer")


# --- Seam 3: Détection Topologique des Cycles & Chronologie ---


def test_tarjan_finds_closed_cycle():
    G = nx.DiGraph()
    _edge(G, "A", "B", 100.0)
    _edge(G, "B", "C", 100.0)
    _edge(G, "C", "A", 100.0)
    _edge(G, "D", "A", 50.0)  # Hors cycle

    detector = GraphDetector(G)
    res = detector.run_detection()

    assert len(res.closed_cycles) == 1
    assert set(res.closed_cycles[0]) == {"A", "B", "C"}
    assert res.total_cycle_volume_usd == 100.0


def test_tarjan_ignores_acyclic_dag():
    G = nx.DiGraph()
    _edge(G, "A", "B", 100.0)
    _edge(G, "B", "C", 100.0)

    detector = GraphDetector(G)
    res = detector.run_detection()

    assert len(res.closed_cycles) == 0
    assert res.total_cycle_volume_usd == 0.0


def test_control_layer_cannot_form_laundering_cycle():
    G = nx.DiGraph()
    _edge(G, "A", "B", 100.0)
    _edge(G, "B", "C", 100.0)
    _edge(G, "C", "A", 0.0, layer="control")  # Mandat, pas de flux

    res = GraphDetector(G).run_detection()
    assert res.closed_cycles == []


def test_mass_dilution_is_rejected():
    G = nx.DiGraph()
    _edge(G, "A", "B", 1000.0)
    _edge(G, "B", "C", 100.0)  # Déperdition massive (90 %)
    _edge(G, "C", "A", 100.0)

    res = GraphDetector(G).run_detection()
    assert res.closed_cycles == []
    assert res.rejected_cycles_count == 1


def test_chronology_violation_is_rejected():
    G = nx.DiGraph()
    _edge(G, "A", "B", 100.0, date="2022-03-01")
    _edge(G, "B", "C", 100.0, date="2022-02-01")
    _edge(G, "C", "A", 100.0, date="2022-04-01")

    res = GraphDetector(G).run_detection()
    assert res.closed_cycles == []
    assert res.rejected_cycles_count == 1


def test_chronological_cycle_is_kept_whatever_the_rotation():
    G = nx.DiGraph()
    _edge(G, "A", "B", 100.0, date="2022-03-01")
    _edge(G, "B", "C", 100.0, date="2022-04-01")
    _edge(G, "C", "A", 100.0, date="2022-02-01")

    res = GraphDetector(G).run_detection()
    assert len(res.closed_cycles) == 1
    assert res.cycle_details[0]["steps"][0]["from"] == "C"


def test_overlapping_cycles_not_double_counted():
    G = nx.DiGraph()
    _edge(G, "A", "B", 100.0)
    _edge(G, "B", "C", 100.0)
    _edge(G, "C", "A", 100.0)
    _edge(G, "B", "D", 100.0)
    _edge(G, "D", "A", 100.0)

    res = GraphDetector(G).run_detection()
    assert len(res.closed_cycles) == 2
    assert res.total_cycle_volume_usd == 100.0


def test_brandes_betweenness_centrality():
    G = nx.DiGraph()
    G.add_edge("A", "HUB")
    G.add_edge("B", "HUB")
    G.add_edge("HUB", "C")
    G.add_edge("HUB", "D")

    detector = GraphDetector(G)
    res = detector.run_detection()

    assert res.pivot_node == "HUB"
    assert res.betweenness_scores["HUB"] > 0.0
