"""
Générateur de pièces scannées réalistes à partir d'un sous-réseau ICIJ anonymisé.

Les documents bruts des Panama Papers ne sont pas publics ; la base ICIJ, elle, est le résultat
du travail manuel de leur exploitation. On fait donc le chemin inverse pour mesurer la méthode :
topologie ICIJ réelle -> noms fictifs (aucune identité réelle sur les pièces) -> pièces
dégradées (scans, photos, PDF image) + leurres -> extraction -> graphe reconstruit.

Le volet financier (virements, relevés, procurations, bénéficiaire caché) est SIMULÉ : la base
ICIJ ne contient aucun montant. Les flux sont posés sur la structure topologique pour mesurer
la méthode. Les noms affichés sont fictifs : aucun fait n'est imputé à une personne ou société
réelle.

Limite assumée : des pièces générées restent plus propres que de vraies archives.
"""

import copy
import json
import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import networkx as nx
from PIL import Image, ImageDraw, ImageFilter, ImageFont

PAGE = (1240, 1754)  # A4 à 150 DPI
QUALITIES = ("clean", "scan", "photo")
_FAKE_FIRST = ["Paper", "Harbour", "Summit", "Pinewood", "Bluefin", "Crescent", "Redwood"]
_FAKE_SECOND = ["Supplies", "Couriers", "Printing", "Catering", "Cleaning", "Telecom"]
_FAKE_PEOPLE = ["John Carter", "Maria Lopez", "Peter Hughes", "Anna Novak", "Luis Ortega"]
_FAKE_UBO = ["Viktor Haldane", "Elena Marchetti", "Rafael Quintero", "Oskar Lindqvist"]
_FAKE_MULES = [
    "Daniel Moreau",
    "Sofia Brandt",
    "Tomas Vidal",
    "Irene Kowalski",
    "Marco Fiore",
    "Lena Hartmann",
    "Pablo Serrano",
    "Nadia Petrova",
]
# Réserves pour anonymiser les noms ICIJ (jamais réutilisées telles quelles hors génération)
_ANON_CO_A = [
    "Northwind",
    "Silverpine",
    "Oakridge",
    "Amberfield",
    "Cobalt",
    "Ironwood",
    "Seaglass",
    "Stonehaven",
    "Willowmere",
    "Ashcroft",
    "Glenbrook",
    "Fairhaven",
    "Copperfield",
    "Mistvale",
    "Brightwater",
    "Thornfield",
]
_ANON_CO_B = [
    "Holdings",
    "Ventures",
    "Trading",
    "Partners",
    "Investments",
    "Management",
    "Capital",
    "Assets",
    "Group",
    "Enterprises",
]
_ANON_CO_SFX = ["S.A.", "Ltd.", "Corp.", "Limited", "Inc."]
_ANON_FIRST = [
    "Adrian",
    "Clara",
    "Dimitri",
    "Helena",
    "Julian",
    "Karin",
    "Mateo",
    "Nora",
    "Owen",
    "Priya",
    "Quentin",
    "Sigrid",
    "Theo",
    "Uma",
    "Vincent",
    "Yara",
]
_ANON_LAST = [
    "Bergstrom",
    "Castille",
    "Davenport",
    "Ellsworth",
    "Fujimoto",
    "Garrido",
    "Holmgren",
    "Ibarra",
    "Jansen",
    "Keller",
    "Lindholm",
    "Morales",
    "Nielsen",
    "Ortega",
    "Pavlov",
    "Reynaud",
]
_ANON_AGENTS = [
    "Coral Fiduciary Services Ltd.",
    "Harbour Corporate Services S.A.",
    "Maple Register Agents Ltd.",
    "Sterling Company Services Inc.",
    "Atlas Nominees Bureau Ltd.",
]
_PURPOSES = ["Consultancy agreement", "Loan repayment", "Management fees", "Advance on contract"]
_WIRE_COLS = (110, 440)
_STATEMENT_COLS = (110, 300, 960)


def truth_path(out_dir: Path) -> Path:
    """Vérité terrain stockée HORS du dossier de pièces (l'extracteur ne doit jamais la voir)."""
    return out_dir.parent / f"{out_dir.name}.truth.json"


def scenario_path(out_dir: Path) -> Path:
    """Scénario financier simulé (circuit, fractionnement, bénéficiaire caché), hors dossier."""
    return out_dir.parent / f"{out_dir.name}.scenario.json"


def link_to_role(link: str) -> str:
    link = link.lower()
    if "beneficial" in link or "beneficiary" in link:
        return "beneficial_owner"
    if "shareholder" in link or "member" in link:
        return "shareholder"
    if "secretary" in link:
        return "secretary"
    if "director" in link or "officer" in link:
        return "director"
    return "other"


@dataclass
class Piece:
    piece_id: str
    file: str
    doc_type: str
    quality: str
    entities: list[dict] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)
    transfers: list[dict] = field(default_factory=list)


def select_case(G: nx.DiGraph, hub: str, n_companies: int = 12, seed: int = 7) -> list[dict]:
    """Sous-réseau réel : n sociétés d'un dirigeant-hub, leurs dirigeants et leur intermédiaire."""
    rng = random.Random(seed)
    companies = sorted(v for v in G.successors(hub) if G.nodes[v]["entity_type"] == "Societe")
    rng.shuffle(companies)
    case = []
    for c in companies[:n_companies]:
        officers = []
        for p in sorted(G.predecessors(c)):
            if G.nodes[p]["entity_type"] != "PersonnePhysique":
                continue
            role = link_to_role(" ".join(G[p][c].get("links", [])))
            if role != "other":
                officers.append({"name": G.nodes[p]["name"], "role": role})
        officers = sorted(officers, key=lambda o: o["name"] != G.nodes[hub]["name"])[:4]
        inters = [
            G.nodes[p]["name"]
            for p in sorted(G.predecessors(c))
            if G.nodes[p]["entity_type"] == "Intermediaire"
        ]
        case.append(
            {
                "node": c,
                "name": G.nodes[c]["name"],
                "jurisdiction": G.nodes[c].get("jurisdiction", "") or "British Virgin Islands",
                "incorporated": G.nodes[c].get("incorporation_date", "") or "unknown date",
                "intermediary": inters[0] if inters else "",
                "officers": officers,
            }
        )
    return case


def anonymize_case(case: list[dict], seed: int = 7) -> list[dict]:
    """
    Remplace chaque nom ICIJ par un nom fictif stable (même graine → mêmes alias).
    La topologie (qui détient / dirige quoi) est préservée ; les noms d'origine sont jetés
    (aucune table de correspondance écrite sur disque).
    """
    rng = random.Random(seed * 917 + 31)
    mapping: dict[str, str] = {}
    used: set[str] = set()

    def _unique(factory) -> str:
        for _ in range(500):
            name = factory()
            if name not in used:
                used.add(name)
                return name
        raise RuntimeError("Réserve de noms fictifs épuisée")

    def alias(real: str, kind: str) -> str:
        if not real:
            return ""
        if real in mapping:
            return mapping[real]
        if kind == "Intermediaire":
            fake = _unique(lambda: rng.choice(_ANON_AGENTS))
        elif kind == "PersonnePhysique":
            fake = _unique(lambda: f"{rng.choice(_ANON_FIRST)} {rng.choice(_ANON_LAST)}")
        else:
            fake = _unique(
                lambda: (
                    f"{rng.choice(_ANON_CO_A)} {rng.choice(_ANON_CO_B)} {rng.choice(_ANON_CO_SFX)}"
                )
            )
        mapping[real] = fake
        return fake

    def officer_kind(name: str) -> str:
        upper = name.upper()
        if any(tok in upper for tok in (" LTD", " S.A", " INC", " CORP", " LIMITED", " LLC")):
            return "Societe"
        return "PersonnePhysique"

    out = copy.deepcopy(case)
    for c in out:
        c["name"] = alias(c["name"], "Societe")
        c["intermediary"] = alias(c["intermediary"], "Intermediaire")
        for o in c["officers"]:
            o["name"] = alias(o["name"], officer_kind(o["name"]))
    return out


def _variant(name: str, rng: random.Random) -> str:
    """Variations d'écriture réalistes d'un même nom d'une pièce à l'autre."""
    r = rng.random()
    if r < 0.15:
        return name.title()
    if r < 0.25:
        return name.replace("LIMITED", "LTD.").replace("Limited", "Ltd.")
    return name


Line = tuple[str, int] | tuple[str, int, tuple[int, ...]]


def _render(lines: list[Line], rng: random.Random, stamp: str = "") -> Image.Image:
    """Chaque ligne : (texte, taille) ou (texte, taille, abscisses des colonnes séparées par \\t)."""
    img = Image.new("L", PAGE, 255)
    draw = ImageDraw.Draw(img)
    y = 140
    for line in lines:
        text, size = line[0], line[1]
        xs = line[2] if len(line) == 3 else tuple(110 + 640 * i for i in range(4))
        font = ImageFont.load_default(size=size)
        for col, part in enumerate(text.split("\t")):
            if part:
                draw.text((xs[col], y), part, fill=rng.randint(0, 40), font=font)
        y += int(size * 1.7)
    if stamp:
        x0, y0 = rng.randint(700, 850), rng.randint(1250, 1400)
        draw.ellipse((x0, y0, x0 + 300, y0 + 170), outline=90, width=5)
        draw.text((x0 + 40, y0 + 65), stamp, fill=90, font=ImageFont.load_default(size=26))
    for _ in range(3):  # signature manuscrite approximative
        pts = [(160 + i * 18, 1500 + rng.randint(-14, 14)) for i in range(14)]
        draw.line(pts, fill=30, width=3)
    return img


def _degrade(img: Image.Image, quality: str, rng: random.Random) -> Image.Image:
    if quality == "clean":
        return img
    if quality == "scan":
        img = img.rotate(rng.uniform(-2, 2), expand=True, fillcolor=225, resample=Image.BICUBIC)
        img = Image.blend(img, Image.effect_noise(img.size, 30), 0.12)
        return img.filter(ImageFilter.GaussianBlur(0.7))

    # Photo prise au téléphone : page de travers sur un bureau, perspective, éclairage inégal
    w, h = img.size
    d = int(w * 0.07)
    img = img.transform(
        (w, h),
        Image.QUAD,
        (
            rng.randint(0, d),
            rng.randint(0, d),
            0,
            h,
            w,
            h - rng.randint(0, d),
            w - rng.randint(0, d),
            0,
        ),
        resample=Image.BICUBIC,
        fillcolor=255,
    )
    img = img.rotate(rng.uniform(-7, 7), expand=True, fillcolor=0, resample=Image.BICUBIC)
    desk = Image.new("L", (int(img.width * 1.12), int(img.height * 1.08)), rng.randint(60, 95))
    mask = img.point(lambda v: 255 if v > 0 else 0)
    desk.paste(img, ((desk.width - img.width) // 2, (desk.height - img.height) // 2), mask)
    shade = Image.radial_gradient("L").resize(desk.size).point(lambda v: 255 - int(v * 0.55))
    img = Image.composite(desk, Image.new("L", desk.size, 0), shade)
    img = Image.blend(img, Image.effect_noise(img.size, 50), 0.14)
    return img.filter(ImageFilter.GaussianBlur(1.2))


def _save(img: Image.Image, out_dir: Path, piece_id: str, quality: str) -> str:
    if quality == "scan":
        name = f"{piece_id}.pdf"  # PDF « image seule », sans couche texte
        img.convert("RGB").save(out_dir / name, "PDF", resolution=150)
    elif quality == "photo":
        name = f"{piece_id}.jpg"
        img.convert("RGB").save(out_dir / name, "JPEG", quality=45)
    else:
        name = f"{piece_id}.png"
        img.save(out_dir / name)
    return name


def _money(amount: float) -> str:
    return f"{amount:,.2f}"


def _transfer(payer: str, payee: str, amount: float, currency: str, day: date) -> dict:
    return {
        "payer": payer,
        "payee": payee,
        "amount": round(amount, 2),
        "currency": currency,
        "date": day.isoformat(),
    }


def _wire_job(t: dict, payer_kind: str, payee_kind: str, rng: random.Random) -> tuple:
    day = date.fromisoformat(t["date"])
    ref = f"FT{day:%y%j}{rng.choice('ABCDEFGHKLMNPRSTXZ')}{rng.randint(1000, 9999)}"
    lines: list[Line] = [
        ("PAYMENT ORDER - SWIFT MT103", 34),
        ("", 20),
        (f"Transaction reference:\t{ref}", 22, _WIRE_COLS),
        (f"Value date:\t{day:%d %B %Y}", 22, _WIRE_COLS),
        ("", 16),
        (f"Ordering customer:\t{_variant(t['payer'], rng)}", 22, _WIRE_COLS),
        (f"Account:\tCH{rng.randint(10, 99)} {rng.randint(1000, 9999)} ****", 22, _WIRE_COLS),
        ("", 16),
        (f"Beneficiary:\t{_variant(t['payee'], rng)}", 22, _WIRE_COLS),
        (f"Account:\tPA{rng.randint(10, 99)} {rng.randint(1000, 9999)} ****", 22, _WIRE_COLS),
        ("", 16),
        (f"Amount:\t{t['currency']} {_money(t['amount'])}", 26, _WIRE_COLS),
        (f"Details of payment:\t{rng.choice(_PURPOSES)}", 22, _WIRE_COLS),
        ("", 20),
        ("Charges: OUR", 20),
    ]
    ents = [{"name": t["payer"], "kind": payer_kind}, {"name": t["payee"], "kind": payee_kind}]
    return ("wire_transfer", lines, "EXECUTED", ents, [], [t])


def _statement_job(holder: str, moves: list[dict], kinds: dict, rng: random.Random) -> tuple:
    days = sorted(date.fromisoformat(t["date"]) for t in moves)
    balance = rng.randint(40_000, 90_000) + 0.0
    lines: list[Line] = [
        ("STATEMENT OF ACCOUNT", 36),
        (f"Account holder:\t{_variant(holder, rng)}", 22, _WIRE_COLS),
        (
            f"Account number:\tPA{rng.randint(10, 99)} {rng.randint(1000, 9999)} ****",
            22,
            _WIRE_COLS,
        ),
        (f"Period:\t{days[0]:%d/%m/%Y} - {days[-1] + timedelta(days=3):%d/%m/%Y}", 22, _WIRE_COLS),
        ("", 18),
        ("Date\tDescription\tAmount (USD)", 20, _STATEMENT_COLS),
        (f"\tOpening balance\t{_money(balance)}", 20, _STATEMENT_COLS),
    ]
    for t in sorted(moves, key=lambda m: m["date"]):
        day = date.fromisoformat(t["date"])
        if t["payer"] == holder:
            desc, signed = f"Transfer to {_variant(t['payee'], rng)}", -t["amount"]
        else:
            desc, signed = f"Transfer from {_variant(t['payer'], rng)}", t["amount"]
        balance += signed
        lines.append((f"{day:%d/%m/%Y}\t{desc}\t{_money(signed)}", 20, _STATEMENT_COLS))
    lines.append((f"\tClosing balance\t{_money(balance)}", 20, _STATEMENT_COLS))
    names = {holder} | {t["payer"] for t in moves} | {t["payee"] for t in moves}
    ents = [{"name": n, "kind": kinds[n]} for n in sorted(names)]
    return ("bank_statement", lines, "", ents, [], list(moves))


def _poa_job(company: str, grantor: dict, attorney: str, rng: random.Random) -> tuple:
    capacity = grantor["role"].replace("_", " ")
    lines: list[Line] = [
        ("GENERAL POWER OF ATTORNEY", 38),
        ("", 20),
        (_variant(company, rng), 30),
        ("", 20),
        (f"We, {_variant(grantor['name'], rng)}, acting as {capacity} of the", 22),
        ("above company, hereby irrevocably appoint", 22),
        ("", 16),
        (attorney, 30),
        ("", 16),
        ("as attorney of the company with full power to operate its bank", 22),
        ("accounts, to sign any contract and to receive any dividend.", 22),
        ("", 20),
        ("This power of attorney shall not be registered.", 22),
    ]
    ents = [
        {"name": company, "kind": "Societe"},
        {"name": grantor["name"], "kind": "PersonnePhysique"},
        {"name": attorney, "kind": "PersonnePhysique"},
    ]
    rels = [
        {"source": grantor["name"], "target": company, "role": grantor["role"]},
        {"source": attorney, "target": company, "role": "attorney"},
    ]
    return ("power_of_attorney", lines, "NOTARY", ents, rels, [])


def money_scenario(case: list[dict], seed: int = 7) -> dict:
    """
    Scénario financier SIMULÉ posé sur le réseau réel :
    - circuit fermé de 4 sociétés (round-tripping, commission de 1,5 à 3 % par étape) ;
    - fractionnement : 6 virements sous 10 000 USD vers des relais qui reversent à un collecteur ;
    - bénéficiaire caché : procuration non enregistrée sur la tête du circuit et le collecteur,
      qui reçoit la sortie de fonds ;
    - paiements fournisseurs légitimes (bruit) et virements entre sociétés sans lien (leurres).
    """
    rng = random.Random(seed * 1009 + 17)
    with_officers = [c for c in case if c["officers"]]
    if len(with_officers) < 6:
        raise ValueError("Le scénario financier requiert au moins 6 sociétés avec dirigeants")
    picked = rng.sample(with_officers, 6)
    loop, source, collector = picked[:4], picked[4], picked[5]
    ubo = rng.choice(_FAKE_UBO)
    mules = rng.sample(_FAKE_MULES, 6)
    start = date(2014, 2, 3) + timedelta(days=rng.randint(0, 120))

    cycle, amount, day = [], float(rng.randrange(1_800_000, 2_600_000, 2_500)), start
    for i, c in enumerate(loop):
        nxt = loop[(i + 1) % len(loop)]
        cycle.append(_transfer(c["name"], nxt["name"], amount, "USD", day))
        amount *= 1 - rng.uniform(0.015, 0.03)
        day += timedelta(days=rng.randint(3, 9))
    exit_head = _transfer(loop[0]["name"], ubo, cycle[-1]["amount"] * 0.18, "USD", day)

    smurf_day = start + timedelta(days=rng.randint(20, 40))
    fan_out, fan_in = [], []
    for k, m in enumerate(mules):
        sent = rng.randrange(9_100, 9_900, 25)
        fan_out.append(_transfer(source["name"], m, sent, "USD", smurf_day + timedelta(days=k % 2)))
        fan_in.append(
            _transfer(
                m,
                collector["name"],
                round(sent * rng.uniform(0.97, 0.99)),
                "USD",
                smurf_day + timedelta(days=2 + k % 3),
            )
        )
    exit_collector = _transfer(
        collector["name"],
        ubo,
        round(sum(t["amount"] for t in fan_in) * 0.9),
        "USD",
        smurf_day + timedelta(days=6),
    )

    nominee = Counter(o["name"] for c in case for o in c["officers"]).most_common(1)[0][0]
    grants = []
    for c in (loop[0], collector):
        grantor = next((o for o in c["officers"] if o["name"] == nominee), c["officers"][0])
        grants.append({"company": c["name"], "grantor": grantor, "attorney": ubo})

    legit = []
    for c in rng.sample(case, 3):
        vendor = f"{rng.choice(_FAKE_FIRST)} {rng.choice(_FAKE_SECOND)} Ltd"
        legit.append(
            _transfer(
                c["name"],
                vendor,
                rng.randrange(1_200, 6_500, 10),
                rng.choice(["USD", "EUR"]),
                start + timedelta(days=rng.randint(0, 60)),
            )
        )
    decoys = []
    for _ in range(2):
        a = f"{rng.choice(_FAKE_FIRST)} {rng.choice(_FAKE_SECOND)} Inc"
        b = f"{rng.choice(_FAKE_FIRST)} {rng.choice(_FAKE_SECOND)} Ltd"
        if a.split()[0] != b.split()[0]:
            decoys.append(
                _transfer(a, b, rng.randrange(800, 4_800, 5), "USD", start + timedelta(days=9))
            )
    return {
        "simulated": True,
        "beneficiary": ubo,
        "nominee": nominee,
        "cycle": [c["name"] for c in loop],
        "cycle_transfers": cycle,
        "exit_transfers": [exit_head, exit_collector],
        "smurfing": {
            "source": source["name"],
            "collector": collector["name"],
            "mules": mules,
            "fan_out": fan_out,
            "fan_in": fan_in,
        },
        "powers_of_attorney": grants,
        "legit_payments": legit,
        "decoy_transfers": decoys,
    }


def _money_jobs(scenario: dict, rng: random.Random) -> list[tuple]:
    sm = scenario["smurfing"]
    people = {scenario["beneficiary"], *sm["mules"]}

    def kind(name: str) -> str:
        return "PersonnePhysique" if name in people else "Societe"

    jobs = [
        _wire_job(t, kind(t["payer"]), kind(t["payee"]), rng)
        for t in [
            *scenario["cycle_transfers"],
            scenario["exit_transfers"][0],
            *scenario["legit_payments"],
            *scenario["decoy_transfers"],
        ]
    ]
    kinds = {n: kind(n) for t in sm["fan_out"] + sm["fan_in"] for n in (t["payer"], t["payee"])}
    kinds[scenario["beneficiary"]] = "PersonnePhysique"
    jobs.append(_statement_job(sm["source"], sm["fan_out"], kinds, rng))
    jobs.append(
        _statement_job(sm["collector"], [*sm["fan_in"], scenario["exit_transfers"][1]], kinds, rng)
    )
    for g in scenario["powers_of_attorney"]:
        jobs.append(_poa_job(g["company"], g["grantor"], g["attorney"], rng))
    return jobs


def forge_dossier(
    case: list[dict],
    out_dir: Path,
    n_distractors: int = 6,
    seed: int = 7,
    with_money: bool = True,
    anonymize: bool = True,
) -> list[Piece]:
    """
    Rend 2 pièces par société (certificat + registre), le volet financier simulé (virements,
    relevés, procurations) et des leurres ; vérité terrain et scénario stockés hors du dossier.

    Par défaut, les noms ICIJ sont remplacés par des noms fictifs avant rendu (anonymize=True).
    """
    if anonymize:
        case = anonymize_case(case, seed)
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
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
        if c["intermediary"]:
            lines += [("", 20), (f"Registered agent: {_variant(c['intermediary'], rng)}", 24)]
            ents.append({"name": c["intermediary"], "kind": "Intermediaire"})
            rels.append({"source": c["intermediary"], "target": c["name"], "role": "intermediary"})
        jobs.append(("certificate_of_incorporation", lines, "REGISTRAR", ents, rels, []))

        if c["officers"]:
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
                }[o["role"]]
                lines.append((f"{_variant(o['name'], rng)}\t{cap}", 22))
                ents.append({"name": o["name"], "kind": "PersonnePhysique"})
                rels.append({"source": o["name"], "target": c["name"], "role": o["role"]})
            lines += [("", 20), ("Certified true copy of the register.", 22)]
            jobs.append(("register_of_directors", lines, "CERTIFIED", ents, rels, []))

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

    scenario = money_scenario(case, seed) if with_money else None
    if scenario:
        jobs += _money_jobs(scenario, rng)

    rng.shuffle(jobs)  # un dossier réel n'arrive pas trié
    pieces = []
    for i, (doc_type, lines, stamp, ents, rels, transfers) in enumerate(jobs, start=1):
        piece_id = f"PIECE-{i:04d}"
        quality = rng.choice(QUALITIES)
        img = _degrade(_render(lines, rng, stamp), quality, rng)
        fname = _save(img, out_dir, piece_id, quality)
        pieces.append(Piece(piece_id, fname, doc_type, quality, ents, rels, transfers))

    truth_path(out_dir).write_text(
        json.dumps([p.__dict__ for p in pieces], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if scenario:
        scenario_path(out_dir).write_text(
            json.dumps(scenario, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return pieces
