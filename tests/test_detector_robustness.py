import networkx as nx

from fin_enclave.graph.detector import GraphDetector


def _edge(G: nx.DiGraph, u: str, v: str, amount: float, layer: str = "flow", date: str = ""):
    G.add_edge(u, v, amount_usd=amount, layers=[layer], date=date, rel_type="fund_transfer")


def test_control_layer_cannot_form_laundering_cycle():
    G = nx.DiGraph()
    _edge(G, "A", "B", 100.0)
    _edge(G, "B", "C", 100.0)
    _edge(G, "C", "A", 0.0, layer="control")  # lien de mandat, aucun flux
    res = GraphDetector(G).run_detection()
    assert res.closed_cycles == []


def test_two_node_round_trip_is_kept():
    G = nx.DiGraph()
    _edge(G, "A", "B", 100.0, date="2022-01-01")
    _edge(G, "B", "A", 95.0, date="2022-01-05")
    res = GraphDetector(G).run_detection()
    assert len(res.closed_cycles) == 1
    assert res.total_cycle_volume_usd == 100.0


def test_mass_dilution_is_rejected():
    G = nx.DiGraph()
    _edge(G, "A", "B", 1000.0)
    _edge(G, "B", "C", 100.0)  # 90 % dilués
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
    # Depuis l'arc le plus ancien (B->C) : 02-01, 04-01, 03-01 -> non chronologique
    assert res.closed_cycles == []
    assert res.rejected_cycles_count == 1


def test_chronological_cycle_is_kept_whatever_the_rotation():
    G = nx.DiGraph()
    _edge(G, "A", "B", 100.0, date="2022-03-01")
    _edge(G, "B", "C", 100.0, date="2022-04-01")
    _edge(G, "C", "A", 100.0, date="2022-02-01")  # arc le plus ancien = C->A
    res = GraphDetector(G).run_detection()
    assert len(res.closed_cycles) == 1
    assert res.cycle_details[0]["steps"][0]["from"] == "C"


def test_overlapping_cycles_not_double_counted():
    G = nx.DiGraph()
    # Deux cycles partageant l'arc A->B
    _edge(G, "A", "B", 100.0)
    _edge(G, "B", "C", 100.0)
    _edge(G, "C", "A", 100.0)
    _edge(G, "B", "D", 100.0)
    _edge(G, "D", "A", 100.0)
    res = GraphDetector(G).run_detection()
    assert len(res.closed_cycles) == 2
    assert res.total_cycle_volume_usd == 100.0


def test_cycle_length_is_bounded():
    G = nx.DiGraph()
    nodes = [f"N{i}" for i in range(10)]
    for i, n in enumerate(nodes):
        _edge(G, n, nodes[(i + 1) % 10], 100.0)
    res = GraphDetector(G).run_detection(max_cycle_len=8)
    assert res.closed_cycles == []
