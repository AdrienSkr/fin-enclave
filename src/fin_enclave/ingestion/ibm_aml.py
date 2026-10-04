"""
Connecteur et sélecteur de motifs issus d'IBM AMLworld (NeurIPS 2023).

Parse les motifs de blanchiment étiquetés du fichier HI-Small_Patterns.txt
(ou équivalents) et sélectionne les tentatives représentatives pour chaque
typologie financière (CYCLE, FAN-OUT, FAN-IN, SCATTER-GATHER, GATHER-SCATTER,
STACK, BIPARTITE).
"""

import csv
import io
import random
import re
from pathlib import Path

CURRENCY_MAP = {
    "US Dollar": "USD",
    "Euro": "EUR",
    "USD": "USD",
    "EUR": "EUR",
}

SUPPORTED_TYPOLOGIES = [
    "CYCLE",
    "FAN-OUT",
    "FAN-IN",
    "SCATTER-GATHER",
    "GATHER-SCATTER",
    "STACK",
    "BIPARTITE",
]


def parse_ibm_patterns(source: Path | str) -> list[dict]:
    """
    Parse un fichier ou une chaîne de motifs IBM AML.
    Retourne la liste des tentatives de blanchiment avec leurs transactions.
    """
    if isinstance(source, Path) or (
        isinstance(source, str) and "\n" not in source and Path(source).exists()
    ):
        text = Path(source).read_text(encoding="utf-8", errors="replace")
    else:
        text = str(source)

    pattern = re.compile(
        r"BEGIN LAUNDERING ATTEMPT - ([^\n]+)\n(.*?)(?=END LAUNDERING ATTEMPT)",
        re.DOTALL,
    )
    attempts = []

    for match in pattern.finditer(text):
        header = match.group(1).strip()
        body = match.group(2).strip()
        typo = header.split(":")[0].strip()

        txs = []
        reader = csv.reader(io.StringIO(body))
        for row in reader:
            if not row or not any(row):
                continue
            if len(row) < 7:
                continue

            ts = row[0].strip()
            date_iso = ts.split()[0].replace("/", "-") if ts else ""
            from_bank = row[1].strip()
            from_acc = row[2].strip()
            to_bank = row[3].strip()
            to_acc = row[4].strip()
            try:
                amt = round(float(row[5].strip()), 2)
            except ValueError:
                continue

            raw_cur = row[6].strip()
            curr = CURRENCY_MAP.get(raw_cur, raw_cur)
            fmt = row[9].strip() if len(row) > 9 else "ACH"

            txs.append(
                {
                    "timestamp": ts,
                    "date": date_iso,
                    "from_bank": from_bank,
                    "from_account": from_acc,
                    "to_bank": to_bank,
                    "to_account": to_acc,
                    "amount": amt,
                    "currency": curr,
                    "format": fmt,
                }
            )

        if txs:
            attempts.append(
                {
                    "typology": typo,
                    "description": header,
                    "transactions": txs,
                }
            )

    return attempts


def select_attempts(
    attempts: list[dict],
    seed: int = 7,
    min_tx: int = 3,
    max_tx: int = 12,
    typologies: list[str] | None = None,
) -> list[dict]:
    """
    Sélectionne de manière déterministe une tentative par typologie,
    restreinte aux devises USD ou EUR et à la plage de taille souhaitée.
    """
    target_typos = typologies or SUPPORTED_TYPOLOGIES
    rng = random.Random(seed)

    # Filtrage des tentatives ayant uniquement des devises gérées (USD, EUR)
    valid_attempts = [
        a for a in attempts if all(t["currency"] in ("USD", "EUR") for t in a["transactions"])
    ]

    selected = []
    for typo in target_typos:
        # Recherche prioritaire dans la plage [min_tx, max_tx]
        candidates = [
            a
            for a in valid_attempts
            if a["typology"] == typo and min_tx <= len(a["transactions"]) <= max_tx
        ]

        # Repli si aucune tentative dans la plage exacte (notamment STACK qui peut faire 2 transactions)
        if not candidates:
            candidates = [
                a
                for a in valid_attempts
                if a["typology"] == typo and 2 <= len(a["transactions"]) <= max_tx
            ]

        # Dernier repli : n'importe quelle taille valide pour cette typologie
        if not candidates:
            candidates = [a for a in valid_attempts if a["typology"] == typo]

        if not candidates:
            raise ValueError(f"Aucune tentative trouvée pour la typologie '{typo}' en USD/EUR.")

        # Choix déterministe
        pick = rng.choice(candidates)
        selected.append(pick)

    return selected
