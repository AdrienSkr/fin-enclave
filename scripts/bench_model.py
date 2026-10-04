import json
import sys
import time
from pathlib import Path

from fin_enclave.documents.evaluation import evaluate_pieces, evaluate_scenario, evaluate_typologies
from fin_enclave.documents.extractor import VLMEngine, extract_dossier
from fin_enclave.documents.forge import scenario_path, truth_path
from fin_enclave.investigation import analyse


def main():
    model_name = sys.argv[1] if len(sys.argv) > 1 else "google/gemini-2.5-flash"
    dossier = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/demo/realiste")
    slug = model_name.replace("/", "_").replace(":", "_")
    dossier_name = dossier.name
    cache_dir = Path(f"data/cache/bench_{dossier_name}_{slug}")
    cache_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"=== TEST COMPLET SUR DOSSIER '{dossier_name}' ({len(list(dossier.iterdir()))} fichiers) : {model_name} ===",
        flush=True,
    )
    t0 = time.time()
    engine = VLMEngine(model=model_name)
    pieces = extract_dossier(dossier, engine, workers=6, use_cache=True, cache_dir=cache_dir)
    t1 = time.time()
    print(f"Extraction terminée en {t1 - t0:.2f} s ({len(pieces)} pièces)", flush=True)

    truth = json.loads(truth_path(dossier).read_text("utf-8"))
    scenario = json.loads(scenario_path(dossier).read_text("utf-8"))

    ev = evaluate_pieces(pieces, truth)["all"]
    print("\n--- MESURE LECTURE DES PIÈCES ---", flush=True)
    print(
        f"  Entités : Précision = {ev['entities']['precision']:.2f}, Rappel = {ev['entities']['recall']:.2f}, F1 = {ev['entities']['f1']:.2f}"
    )
    print(
        f"  Relations : Précision = {ev['relations']['precision']:.2f}, Rappel = {ev['relations']['recall']:.2f}, F1 = {ev['relations']['f1']:.2f}"
    )
    print(
        f"  Virements : Précision = {ev['transfers']['precision']:.2f}, Rappel = {ev['transfers']['recall']:.2f}, F1 = {ev['transfers']['f1']:.2f}"
    )

    G, _resolver, _ledger, _detection, findings = analyse(pieces)
    sc = evaluate_scenario(findings, scenario)
    print("\n--- CONSTATS DU SCÉNARIO ---", flush=True)
    print(f"  Circuit fermé : {'OUI' if sc['cycle_found'] else 'NON'}")
    print(
        f"  Fractionnement : {'OUI' if sc['smurfing_found'] else 'NON'} ({sc['mules_found']}/{sc['mules_expected']} relais)"
    )
    print(f"  Bénéficiaire caché : {'OUI' if sc['hidden_beneficiary_found'] else 'NON'}")

    if "ibm_patterns" in scenario:
        print("\n--- RETROUVAILLES TYPOLOGIES IBM AML ---", flush=True)
        typos = evaluate_typologies(G, scenario)
        for name, stat in typos.items():
            print(f"  {name} : {stat['found']}/{stat['total']} ({stat['recall']:.1%})")


if __name__ == "__main__":
    main()
