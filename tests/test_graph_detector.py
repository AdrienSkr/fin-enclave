import networkx as nx

from fin_enclave.graph.detector import GraphDetector


def test_tarjan_finds_closed_cycle():
    G = nx.DiGraph()
    # Circuit A -> B -> C -> A (longueur 3)
    G.add_edge("A", "B", amount_usd=100.0)
    G.add_edge("B", "C", amount_usd=100.0)
    G.add_edge("C", "A", amount_usd=100.0)
    # Nœud hors cycle
    G.add_edge("D", "A", amount_usd=50.0)

    detector = GraphDetector(G)
    res = detector.run_detection()

    assert len(res.closed_cycles) == 1
    assert set(res.closed_cycles[0]) == {"A", "B", "C"}
    # Volume réel injecté dans le circuit (et non la somme des 3 étapes)
    assert res.total_cycle_volume_usd == 100.0


def test_tarjan_ignores_acyclic_dag():
    G = nx.DiGraph()
    # A -> B -> C (DAG sans boucle)
    G.add_edge("A", "B", amount_usd=100.0)
    G.add_edge("B", "C", amount_usd=100.0)

    detector = GraphDetector(G)
    res = detector.run_detection()

    assert len(res.closed_cycles) == 0
    assert res.total_cycle_volume_usd == 0.0


def test_brandes_betweenness_centrality():
    G = nx.DiGraph()
    # Nœud 'HUB' qui connecte deux branches
    G.add_edge("A", "HUB")
    G.add_edge("B", "HUB")
    G.add_edge("HUB", "C")
    G.add_edge("HUB", "D")

    detector = GraphDetector(G)
    res = detector.run_detection()

    assert res.pivot_node == "HUB"
    assert res.betweenness_scores["HUB"] > 0.0
