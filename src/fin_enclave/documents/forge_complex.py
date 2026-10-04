"""
Générateur de dossier complexe (motifs étiquetés IBM AMLworld + relevés bancaires difficiles).

Ce générateur combine :
1. La structure de détention / gouvernance issue du cas ICIJ anonymisé.
2. Les flux financiers issus directement des motifs de blanchiment étiquetés
   d'IBM AMLworld (CYCLE, FAN-OUT, FAN-IN, SCATTER-GATHER, GATHER-SCATTER, STACK, BIPARTITE).
3. Des relevés bancaires multi-pages reprenant les pièges réels documentés
   (colonnes Débit/Crédit séparées, soldes reportés, formats européens, multilingue EN/FR/ES,
   bruit légitime de 20 à 40 mouvements par compte).

Les paramètres de difficulté sont gelés en tête de fichier avant les mesures.
"""

import json
import math
import random
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .forge import (
    _ANON_CO_A,
    _ANON_CO_B,
    _ANON_CO_SFX,
    _ANON_FIRST,
    _ANON_LAST,
    _FAKE_FIRST,
    _FAKE_PEOPLE,
    _FAKE_SECOND,
    QUALITIES,
    Piece,
    _degrade,
    _render,
    _save,
    _variant,
    anonymize_case,
    scenario_path,
    truth_path,
)

# ==============================================================================
# PARAMÈTRES DE DIFFICULTÉ DU DOSSIER COMPLEXE (GELÉS AVANT MESURE)
# ==============================================================================


@dataclass(frozen=True)
class Difficulty:
    """Paramètres de difficulté d'un dossier complexe (relevés bancaires et motifs IBM AML)."""

    name: str
    lines_per_page: int
    min_noise: int
    max_noise: int
    statement_qualities: tuple[str, ...]
    statement_font_size: int
    typologies: list[str] | None
    fix_noise_labels: bool = False


# PRESET STRESS : reproduction à l'identique du dossier complexe de résistance
# (34 lignes par page, bruit de 20 à 40 mouvements, qualité uniforme incluant photos,
# 7 typologies IBM AMLworld). Le dossier data/demo/complexe doit être reproduit octet pour octet.
STRESS = Difficulty(
    name="stress",
    lines_per_page=34,
    min_noise=20,
    max_noise=40,
    statement_qualities=QUALITIES,  # ("clean", "scan", "photo")
    statement_font_size=18,
    typologies=None,
    fix_noise_labels=False,
)

# PRESET REALISTE : calibré sur un vrai dossier judiciaire PNF / TRACFIN
# Justification a priori de chaque paramètre :
# - Relevés en PDF ou scan seulement : une banque répond aux réquisitions judiciaires
#   par un PDF ou un scan certifié, jamais par une photo prise au smartphone.
#   Les autres pièces (factures, registres saisis) conservent des photos.
# - 20 lignes par page, police 20 pt (au lieu de 18 pt) : aération standard des extraits bancaires officiels.
# - Bruit de 3 à 12 mouvements par compte : une société écran de blanchiment a une
#   activité économique réelle très faible, contrairement à une entreprise commerciale active.
# - 3 typologies ciblées (CYCLE, FAN-OUT, SCATTER-GATHER) : une enquête préliminaire ou
#   information judiciaire vise un réseau précis (circuits fermés, dispersion, regroupement),
#   qui correspondent directement aux détecteurs de circuit et d'éventail.
# - Vraie difficulté de lecture conservée : colonnes Débit / Crédit distinctes, soldes reportés,
#   formats numériques et dates européens, pièces en FR et ES, pagination multiple.
# - Correction du défaut de vérité terrain (fix_noise_labels=True) : les modèles de libellé
#   salaires et loyers impriment explicitement le nom de la contrepartie, conformément à ce
#   qu'attend truth.json.
REALISTE = Difficulty(
    name="realiste",
    lines_per_page=20,
    min_noise=3,
    max_noise=12,
    statement_qualities=("clean", "scan"),
    statement_font_size=20,
    typologies=["CYCLE", "FAN-OUT", "SCATTER-GATHER"],
    fix_noise_labels=True,
)

PRESETS: dict[str, Difficulty] = {
    "stress": STRESS,
    "realiste": REALISTE,
}

LINES_PER_PAGE: int = STRESS.lines_per_page
MIN_NOISE_PER_STATEMENT: int = STRESS.min_noise
MAX_NOISE_PER_STATEMENT: int = STRESS.max_noise
NON_EN_RATIO: float = 0.34  # ~1/3 des relevés en français ou en espagnol

STATEMENT_COLS = (100, 240, 720, 880, 1040)  # Date, Description, Débit, Crédit, Solde
HEADER_COLS_2 = (100, 320)
HEADER_COLS_3 = (100, 320, 880)

STATEMENT_I18N = {
    "en": {
        "title": "STATEMENT OF ACCOUNT",
        "holder": "Account holder:",
        "account": "Account number:",
        "period": "Period:",
        "page": "Page {} of {}",
        "headers": "Date\tDescription\tDebit\tCredit\tBalance",
        "opening": "Opening balance",
        "carried": "Balance carried forward",
        "brought": "Balance brought forward",
        "closing": "Closing balance",
        "prefix_debit": "SEPA CT REF {ref} {name}",
        "prefix_credit": "SEPA CR REF {ref} {name}",
        "noise_debits": [
            "Office supplies - {vendor}",
            "Consulting fees - {vendor}",
            "Telecom and network services - {vendor}",
            "Software license subscription - {vendor}",
            "Legal & statutory audit fees - {vendor}",
            "Monthly staff payroll REF {ref}",
            "Commercial premises lease REF {ref}",
            "Logistics & transport services - {vendor}",
        ],
        "noise_credits": [
            "Customer invoice settlement - {client}",
            "Settlement payment REF {ref} - {client}",
            "Commercial trade receivable - {client}",
        ],
    },
    "fr": {
        "title": "RELEVÉ DE COMPTE",
        "holder": "Titulaire du compte :",
        "account": "Numéro de compte :",
        "period": "Période :",
        "page": "Page {} sur {}",
        "headers": "Date\tLibellé de l'opération\tDébit\tCrédit\tSolde",
        "opening": "Solde initial",
        "carried": "Solde à reporter",
        "brought": "Solde reporté",
        "closing": "Solde de clôture",
        "prefix_debit": "VIR SEPA REF {ref} {name}",
        "prefix_credit": "VIR SEPA REF {ref} {name}",
        "noise_debits": [
            "Fournitures de bureau - {vendor}",
            "Honoraires de conseil - {vendor}",
            "Abonnement télécoms et réseaux - {vendor}",
            "Licences logiciels et hébergement - {vendor}",
            "Frais d'audit et assistance juridique - {vendor}",
            "Virement salaires mensuels REF {ref}",
            "Règlement loyer commercial REF {ref}",
            "Prestations logistiques et fret - {vendor}",
        ],
        "noise_credits": [
            "Règlement facture client - {client}",
            "Encaissement commercial REF {ref} - {client}",
            "Virement reçu prestation - {client}",
        ],
    },
    "es": {
        "title": "EXTRACTO DE CUENTA",
        "holder": "Titular de la cuenta:",
        "account": "Número de cuenta:",
        "period": "Periodo:",
        "page": "Página {} de {}",
        "headers": "Fecha\tConcepto / Descripción\tDebe\tHaber\tSaldo",
        "opening": "Saldo inicial",
        "carried": "Saldo a transportar",
        "brought": "Saldo anterior traído",
        "closing": "Saldo final",
        "prefix_debit": "TRANSF SEPA REF {ref} {name}",
        "prefix_credit": "TRANSF SEPA REF {ref} {name}",
        "noise_debits": [
            "Material de oficina y fungibles - {vendor}",
            "Honorarios de asesoría técnica - {vendor}",
            "Servicios de telecomunicaciones - {vendor}",
            "Suscripción servicios nube y software - {vendor}",
            "Gastos legales y auditoría externa - {vendor}",
            "Abono nóminas plantilla REF {ref}",
            "Pago arrendamiento comercial REF {ref}",
            "Servicios de transporte y distribución - {vendor}",
        ],
        "noise_credits": [
            "Abono de factura cliente - {client}",
            "Cobro comercial REF {ref} - {client}",
            "Transferencia recibida servicios - {client}",
        ],
    },
}


def _get_noise_debits(lang: str, fix_noise_labels: bool) -> list[str]:
    raw = STATEMENT_I18N[lang]["noise_debits"]
    if not fix_noise_labels:
        return raw
    out = []
    for tmpl in raw:
        if "{vendor}" not in tmpl:
            out.append(f"{tmpl} - {{vendor}}")
        else:
            out.append(tmpl)
    return out


def _eur_money(amount: float) -> str:
    """Format européen : 1.250.000,00"""
    formatted = f"{abs(amount):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"-{formatted}" if amount < 0 else formatted


def _usd_money(amount: float) -> str:
    """Format anglo-saxon : 1,250,000.00"""
    return f"{amount:,.2f}"


def _format_money(amount: float, currency: str) -> str:
    return _eur_money(amount) if currency == "EUR" else _usd_money(amount)


def _format_date(d: date, currency: str) -> str:
    # Comptes EUR : dates en dd.mm.yyyy ; comptes USD : dd/mm/yyyy
    return f"{d:%d.%m.%Y}" if currency == "EUR" else f"{d:%d/%m/%Y}"


def _generate_entity_pool(count: int, rng: random.Random) -> list[dict]:
    """Génère un pool de raisons sociales ou personnes physiques fictives uniques."""
    used: set[str] = set()
    pool = []

    def _unique_co() -> str:
        for _ in range(500):
            n = f"{rng.choice(_ANON_CO_A)} {rng.choice(_ANON_CO_B)} {rng.choice(_ANON_CO_SFX)}"
            if n not in used:
                used.add(n)
                return n
        raise RuntimeError("Pool épuisé")

    def _unique_person() -> str:
        for _ in range(500):
            n = f"{rng.choice(_ANON_FIRST)} {rng.choice(_ANON_LAST)}"
            if n not in used:
                used.add(n)
                return n
        raise RuntimeError("Pool épuisé")

    for i in range(count):
        if i % 3 == 0:
            pool.append({"name": _unique_person(), "kind": "PersonnePhysique"})
        else:
            pool.append({"name": _unique_co(), "kind": "Societe"})
    return pool


def _map_accounts_to_entities(
    case: list[dict],
    ibm_attempts: list[dict],
    rng: random.Random,
) -> dict[str, dict]:
    """
    Associe chaque compte IBM à une entité :
    Priorité absolue aux sociétés du cas ICIJ (pour croiser détention et flux),
    puis entités fictives uniques.
    """
    counts: Counter[str] = Counter()
    currencies: dict[str, list[str]] = {}
    for a in ibm_attempts:
        for tx in a["transactions"]:
            fa = tx["from_account"]
            ta = tx["to_account"]
            counts[fa] += 1
            counts[ta] += 1
            currencies.setdefault(fa, []).append(tx["currency"])
            currencies.setdefault(ta, []).append(tx["currency"])

    sorted_accs = [acc for acc, _ in counts.most_common()]
    fictitious_pool = _generate_entity_pool(len(sorted_accs), rng)
    mapping: dict[str, dict] = {}

    for idx, acc in enumerate(sorted_accs):
        curs = currencies.get(acc, ["USD"])
        main_cur = "EUR" if curs.count("EUR") > curs.count("USD") else "USD"

        # Choix de la langue
        r_lang = rng.random()
        if r_lang < NON_EN_RATIO / 2:
            lang = "fr"
            iban = f"FR76 {rng.randint(10000, 99999)} {rng.randint(10000, 99999)} {acc[:10]}"
        elif r_lang < NON_EN_RATIO:
            lang = "es"
            iban = f"ES91 {rng.randint(1000, 9999)} {rng.randint(1000, 9999)} {acc[:10]}"
        else:
            lang = "en"
            iban = f"GB29 MIDL {rng.randint(100000, 999999)} {acc[:8]}"

        if idx < len(case):
            ent_name = case[idx]["name"]
            kind = "Societe"
        else:
            fict = fictitious_pool[idx]
            ent_name = fict["name"]
            kind = fict["kind"]

        mapping[acc] = {
            "account_id": acc,
            "name": ent_name,
            "kind": kind,
            "currency": main_cur,
            "lang": lang,
            "iban": iban,
        }

    return mapping


def _build_statement_pages(
    holder_acc: dict,
    laundering_moves: list[dict],
    noise_moves: list[dict],
    rng: random.Random,
    difficulty: Difficulty = STRESS,
) -> list[tuple]:
    """
    Construit les pages de relevé bancaire d'un compte avec colonnes séparées,
    soldes reportés cohérents d'une page à l'autre et découpage multi-pages.
    """
    lang = holder_acc["lang"]
    i18n = STATEMENT_I18N[lang]
    currency = holder_acc["currency"]
    holder_name = holder_acc["name"]
    iban = holder_acc["iban"]

    all_moves = sorted(laundering_moves + noise_moves, key=lambda m: m["date"])
    if not all_moves:
        return []

    dates = [date.fromisoformat(m["date"]) for m in all_moves]
    period_str = f"{_format_date(dates[0], currency)} - {_format_date(dates[-1] + timedelta(days=2), currency)}"

    # Solde initial calculé pour que le compte reste toujours positif
    running_balance = float(rng.randint(500_000, 1_200_000))
    for m in all_moves:
        signed = -m["amount"] if m["is_debit"] else m["amount"]
        running_balance += signed
        m["balance_after"] = round(running_balance, 2)

    lines_per_page = difficulty.lines_per_page
    font_size = difficulty.statement_font_size
    total_pages = max(1, math.ceil(len(all_moves) / lines_per_page))
    pages_jobs = []

    # Recalcul des soldes avec départ initial
    curr_balance = float(rng.randint(500_000, 1_200_000))

    for p_idx in range(total_pages):
        page_num = p_idx + 1
        chunk = all_moves[p_idx * lines_per_page : (p_idx + 1) * lines_per_page]
        page_str = i18n["page"].format(page_num, total_pages)

        lines = [
            (i18n["title"], 34),
            ("", 16),
            (f"{i18n['holder']}\t{_variant(holder_name, rng)}", 20, HEADER_COLS_2),
            (f"{i18n['account']}\t{iban}", font_size, HEADER_COLS_2),
            (f"{i18n['period']}\t{period_str}\t{page_str}", font_size, HEADER_COLS_3),
            ("", 14),
            (i18n["headers"], font_size, STATEMENT_COLS),
        ]

        # Ligne de solde initial ou reporté
        if page_num == 1:
            lines.append(
                (
                    f"\t{i18n['opening']}\t\t\t{_format_money(curr_balance, currency)}",
                    font_size,
                    STATEMENT_COLS,
                )
            )
        else:
            lines.append(
                (
                    f"\t{i18n['brought']}\t\t\t{_format_money(curr_balance, currency)}",
                    font_size,
                    STATEMENT_COLS,
                )
            )

        page_transfers = []
        page_entities = [{"name": holder_name, "kind": holder_acc["kind"]}]

        for m in chunk:
            d = date.fromisoformat(m["date"])
            date_str = _format_date(d, currency)
            desc = m["description"]
            amt_str = _format_money(m["amount"], currency)
            signed = -m["amount"] if m["is_debit"] else m["amount"]
            curr_balance = round(curr_balance + signed, 2)
            bal_str = _format_money(curr_balance, currency)

            if m["is_debit"]:
                lines.append(
                    (f"{date_str}\t{desc}\t{amt_str}\t\t{bal_str}", font_size, STATEMENT_COLS)
                )
                page_transfers.append(
                    {
                        "payer": holder_name,
                        "payee": m["counterparty"],
                        "amount": m["amount"],
                        "currency": currency,
                        "date": m["date"],
                    }
                )
            else:
                lines.append(
                    (f"{date_str}\t{desc}\t\t{amt_str}\t{bal_str}", font_size, STATEMENT_COLS)
                )
                page_transfers.append(
                    {
                        "payer": m["counterparty"],
                        "payee": holder_name,
                        "amount": m["amount"],
                        "currency": currency,
                        "date": m["date"],
                    }
                )

            page_entities.append({"name": m["counterparty"], "kind": m["counterparty_kind"]})

        # Ligne de clôture ou solde à reporter
        if page_num == total_pages:
            lines.append(
                (
                    f"\t{i18n['closing']}\t\t\t{_format_money(curr_balance, currency)}",
                    font_size,
                    STATEMENT_COLS,
                )
            )
        else:
            lines.append(
                (
                    f"\t{i18n['carried']}\t\t\t{_format_money(curr_balance, currency)}",
                    font_size,
                    STATEMENT_COLS,
                )
            )

        # Dédoublonnage des entités citées sur cette page
        unique_entities = []
        seen = set()
        for e in page_entities:
            if e["name"] not in seen:
                seen.add(e["name"])
                unique_entities.append(e)

        pages_jobs.append(
            ("bank_statement", lines, "", unique_entities, [], page_transfers, curr_balance)
        )

    return pages_jobs


def forge_complex_dossier(
    case: list[dict],
    ibm_attempts: list[dict],
    out_dir: Path,
    n_distractors: int = 6,
    seed: int = 7,
    anonymize: bool = True,
    render_images: bool = True,
    difficulty: Difficulty = STRESS,
) -> list[Piece]:
    """
    Génère le dossier de pièces complexe :
    - 2 pièces par société ICIJ (certificat + registre)
    - Relevés bancaires multi-pages piégés couvrant 100% des flux IBM AML
    - Bruit légitime par relevé
    - Distracteurs (factures)
    - truth.json et scenario.json (avec ibm_patterns)
    """
    if difficulty.typologies is not None:
        ibm_attempts = [a for a in ibm_attempts if a["typology"] in difficulty.typologies]
    if anonymize:
        case = anonymize_case(case, seed)
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    acc_map = _map_accounts_to_entities(case, ibm_attempts, rng)

    # 1. Pièces de registre et certificats d'incorporation ICIJ
    jobs: list[tuple] = []
    for c in case:
        ents = [{"name": c["name"], "kind": "Societe"}]
        rels = []
        lines = [
            (c["jurisdiction"].upper(), 30),
            ("REGISTRAR OF CORPORATE AFFAIRS", 26),
            ("", 20),
            ("CERTIFICATE OF INCORPORATION", 40),
            ("", 20),
            ("I hereby certify that", 24),
            (_variant(c["name"], rng), 32),
            (f"was incorporated on {c['incorporated']} as a business company.", 24),
        ]
        if c.get("intermediary"):
            lines += [("", 20), (f"Registered agent: {_variant(c['intermediary'], rng)}", 24)]
            ents.append({"name": c["intermediary"], "kind": "Intermediaire"})
            rels.append({"source": c["intermediary"], "target": c["name"], "role": "intermediary"})
        jobs.append(("certificate_of_incorporation", lines, "REGISTRAR", ents, rels, []))

        if c.get("officers"):
            ents = [{"name": c["name"], "kind": "Societe"}]
            rels = []
            lines = [
                ("REGISTER OF DIRECTORS AND MEMBERS", 34),
                (_variant(c["name"], rng), 28),
                ("", 20),
                ("Name\tCapacity", 22),
            ]
            for o in c["officers"]:
                cap = {
                    "director": "Director",
                    "shareholder": "Shareholder",
                    "beneficial_owner": "Beneficial Owner",
                    "secretary": "Secretary",
                }.get(o["role"], "Director")
                lines.append((f"{_variant(o['name'], rng)}\t{cap}", 22))
                ents.append({"name": o["name"], "kind": "PersonnePhysique"})
                rels.append({"source": o["name"], "target": c["name"], "role": o["role"]})
            lines += [("", 20), ("Certified true copy of the register.", 22)]
            jobs.append(("register_of_directors", lines, "CERTIFIED", ents, rels, []))

    # 2. Factures de distraction
    for _ in range(n_distractors):
        vendor = f"{rng.choice(_FAKE_FIRST)} {rng.choice(_FAKE_SECOND)} Ltd"
        client = f"{rng.choice(_FAKE_FIRST)} {rng.choice(_FAKE_SECOND)} Inc"
        person = rng.choice(_FAKE_PEOPLE)
        lines = [
            ("INVOICE", 40),
            (vendor, 26),
            (f"Bill to: {client}", 24),
            (f"Attention: {person}", 22),
            ("", 20),
            (f"Services rendered ........ USD {rng.randint(120, 4800)}.00", 22),
            ("Payment due within 30 days.", 22),
        ]
        ents = [
            {"name": vendor, "kind": "Societe"},
            {"name": client, "kind": "Societe"},
            {"name": person, "kind": "PersonnePhysique"},
        ]
        jobs.append(("invoice", lines, "", ents, [], []))

    # 3. Préparation des transactions IBM AML
    # Pour garantir que 100% des transactions IBM sont dans les pièces,
    # on détermine l'ensemble minimal de comptes à saisir qui couvre toutes les transactions.
    all_ibm_tx = []
    edges_to_cover = []
    for a in ibm_attempts:
        for tx in a["transactions"]:
            all_ibm_tx.append(tx)
            edges_to_cover.append((tx["from_account"], tx["to_account"]))

    # Sélection des comptes titulaires :
    # a) Les sociétés du cas ICIJ
    # b) Un vertex cover glouton pour couvrir tous les arcs résiduels
    selected_statement_accs = {
        acc for acc in acc_map if acc_map[acc]["name"] in [c["name"] for c in case]
    }
    uncovered = {
        i
        for i, (u, v) in enumerate(edges_to_cover)
        if u not in selected_statement_accs and v not in selected_statement_accs
    }

    if uncovered:
        deg = Counter()
        for idx in uncovered:
            u, v = edges_to_cover[idx]
            deg[u] += 1
            deg[v] += 1
        for acc, _ in deg.most_common():
            selected_statement_accs.add(acc)
            uncovered = {
                i
                for i in uncovered
                if edges_to_cover[i][0] not in selected_statement_accs
                and edges_to_cover[i][1] not in selected_statement_accs
            }
            if not uncovered:
                break

    # Construction des relevés bancaires
    for acc in sorted(selected_statement_accs):
        holder_info = acc_map[acc]
        lang = holder_info["lang"]
        i18n = STATEMENT_I18N[lang]

        # Mouvements de blanchiment sur ce compte
        laundering_moves = []
        for tx in all_ibm_tx:
            ref = f"{rng.randint(10000, 99999)}"
            if tx["from_account"] == acc:
                counterparty = acc_map[tx["to_account"]]
                desc = i18n["prefix_debit"].format(
                    ref=ref, name=_variant(counterparty["name"], rng)
                )
                laundering_moves.append(
                    {
                        "date": tx["date"],
                        "description": desc,
                        "amount": tx["amount"],
                        "is_debit": True,
                        "counterparty": counterparty["name"],
                        "counterparty_kind": counterparty["kind"],
                    }
                )
            elif tx["to_account"] == acc:
                counterparty = acc_map[tx["from_account"]]
                desc = i18n["prefix_credit"].format(
                    ref=ref, name=_variant(counterparty["name"], rng)
                )
                laundering_moves.append(
                    {
                        "date": tx["date"],
                        "description": desc,
                        "amount": tx["amount"],
                        "is_debit": False,
                        "counterparty": counterparty["name"],
                        "counterparty_kind": counterparty["kind"],
                    }
                )

        # Génération du bruit légitime (20 à 40 mouvements)
        noise_moves = []
        base_date = (
            date.fromisoformat(laundering_moves[0]["date"])
            if laundering_moves
            else date(2022, 9, 1)
        )
        n_noise = rng.randint(difficulty.min_noise, difficulty.max_noise)

        for _ in range(n_noise):
            delta_days = rng.randint(-15, 60)
            m_date = base_date + timedelta(days=delta_days)
            is_deb = rng.random() < 0.72  # Majorité de paiements/charges ordinaires
            ref_noise = f"{rng.randint(10000, 99999)}"

            if is_deb:
                vendor_name = f"{rng.choice(_FAKE_FIRST)} {rng.choice(_FAKE_SECOND)} Ltd"
                noise_debits_pool = _get_noise_debits(lang, difficulty.fix_noise_labels)
                tmpl = rng.choice(noise_debits_pool)
                desc = tmpl.format(vendor=_variant(vendor_name, rng), ref=ref_noise)
                amt = float(rng.randrange(350, 9800, 25))
                noise_moves.append(
                    {
                        "date": m_date.isoformat(),
                        "description": desc,
                        "amount": amt,
                        "is_debit": True,
                        "counterparty": vendor_name,
                        "counterparty_kind": "Societe",
                    }
                )
            else:
                client_name = f"{rng.choice(_FAKE_FIRST)} {rng.choice(_FAKE_SECOND)} Inc"
                tmpl = rng.choice(i18n["noise_credits"])
                desc = tmpl.format(client=_variant(client_name, rng), ref=ref_noise)
                amt = float(rng.randrange(2500, 28000, 50))
                noise_moves.append(
                    {
                        "date": m_date.isoformat(),
                        "description": desc,
                        "amount": amt,
                        "is_debit": False,
                        "counterparty": client_name,
                        "counterparty_kind": "Societe",
                    }
                )

        pages = _build_statement_pages(holder_info, laundering_moves, noise_moves, rng, difficulty)
        for doc_type, lines, stamp, ents, rels, transfers, _ in pages:
            jobs.append((doc_type, lines, stamp, ents, rels, transfers))

    # Mélange des pièces
    rng.shuffle(jobs)

    pieces: list[Piece] = []
    for i, (doc_type, lines, stamp, ents, rels, transfers) in enumerate(jobs, start=1):
        piece_id = f"PIECE-{i:04d}"
        if doc_type == "bank_statement":
            quality = rng.choice(difficulty.statement_qualities)
        else:
            quality = rng.choice(QUALITIES)
        if render_images:
            img = _degrade(_render(lines, rng, stamp), quality, rng)
            fname = _save(img, out_dir, piece_id, quality)
        else:
            fname = f"{piece_id}.png"
            (out_dir / fname).write_bytes(b"")
        pieces.append(Piece(piece_id, fname, doc_type, quality, ents, rels, transfers))

    # Enregistrement de truth.json
    truth_path(out_dir).write_text(
        json.dumps([p.__dict__ for p in pieces], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Enregistrement de scenario.json avec ibm_patterns
    # Détection du cycle pour findings
    cycle_attempt = next((a for a in ibm_attempts if a["typology"] == "CYCLE"), None)
    cycle_nodes = []
    cycle_txs = []
    if cycle_attempt:
        for tx in cycle_attempt["transactions"]:
            p = acc_map[tx["from_account"]]["name"]
            c = acc_map[tx["to_account"]]["name"]
            if p not in cycle_nodes:
                cycle_nodes.append(p)
            cycle_txs.append(
                {
                    "payer": p,
                    "payee": c,
                    "amount": tx["amount"],
                    "currency": tx["currency"],
                    "date": tx["date"],
                }
            )

    scenario = {
        "simulated": True,
        "complex_ibm": True,
        "case_seed": seed,
        "cycle": cycle_nodes,
        "cycle_transfers": cycle_txs,
        "ibm_patterns": [
            {
                "typology": a["typology"],
                "description": a["description"],
                "tx": [
                    {
                        "payer": acc_map[t["from_account"]]["name"],
                        "payee": acc_map[t["to_account"]]["name"],
                        "amount": t["amount"],
                        "currency": t["currency"],
                        "date": t["date"],
                        "ibm_from_account": t["from_account"],
                        "ibm_to_account": t["to_account"],
                    }
                    for t in a["transactions"]
                ],
            }
            for a in ibm_attempts
        ],
    }

    scenario_path(out_dir).write_text(
        json.dumps(scenario, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return pieces
