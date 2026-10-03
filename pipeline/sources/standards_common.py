"""
Shared pieces for the food-standards connectors (India / EU / Codex / US).

Every connector turns one official rule-book into rows of `food_standards`:
one row = one legal limit for one hazard in one food, as the rule-book prints it.
This module holds what they share:

  * the normalisation keys that let rows from different rule-books be compared
    (`hazard_key`, see HAZARD_ALIASES) — the printed names are always kept too;
  * a strict limit parser (`parse_limit`): a number is stored only when the cell
    holds one unambiguous number; everything else keeps its raw text and a
    parse_status saying why it has no value;
  * the loader (`replace_snapshot`): each run replaces one (jurisdiction,
    standard_type) slice inside a single transaction and records the source
    document's sha256 in `standards_snapshots`, so it is idempotent and every
    row can be traced to the exact document version it came from.

Units: limits are stored as printed (`limit_value`, `limit_unit`) AND converted to
mg/kg (`limit_mg_per_kg`) when the unit is a mass fraction (mg/kg, ppm, µg/kg,
ppb). mg/L (waters, beverages) is never silently treated as mg/kg.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from decimal import Decimal, InvalidOperation
from typing import Optional

JURISDICTIONS = {
    "IN": "India — FSSAI",
    "EU": "European Union",
    "CODEX": "Codex Alimentarius (FAO/WHO)",
    "US": "United States — EPA/FDA",
}
STANDARD_TYPES = {"pesticide_mrl", "contaminant_ml", "vet_drug_mrl", "prohibited_substance"}
HAZARD_CLASSES = {
    "pesticide", "heavy_metal", "mycotoxin", "natural_toxin", "environmental_pollutant",
    "process_contaminant", "veterinary_drug", "radionuclide", "marine_biotoxin", "other",
}

# Spelling / naming variants between rule-books -> one comparison key. Only
# genuine synonyms belong here (same substance, same residue definition family);
# every entry was checked against the printed names in at least two rule-books.
HAZARD_ALIASES = {
    "chlorpyriphos": "chlorpyrifos",
    "chlorpyriphosmethyl": "chlorpyrifosmethyl",
    "profenophos": "profenofos",
    "ethofenprox": "etofenprox",
    "decamethrin": "deltamethrin",
    "ddvp": "dichlorvos",
    "methylparathion": "parathionmethyl",
    "kitazin": "iprobenfos",
    "bpmc": "fenobucarb",
    "chlothianidin": "clothianidin",
    "sumofbenomylandcarbendazimexpressedascarbendazim": "carbendazim",
    "benomyl": "carbendazim",          # EU/Codex express benomyl residues as carbendazim
    # isomer-enriched forms sit inside the parent's residue definition in the EU
    # ('sum of isomers') and Codex ('including alpha- and zeta-cypermethrin')
    "betacyfluthrin": "cyfluthrin",
    "zetacypermethrin": "cypermethrin",
    "alphacypermethrin": "cypermethrin",
    "cypermethrins": "cypermethrin",
    "lambdacyhalothrin": "cyhalothrin",     # Codex 'Cyhalothrin (includes lambda-cyhalothrin)'
    "gammacyhalothrin": "cyhalothrin",
    "24dichlorophenoxyaceticacid": "24d",
    "24daminesalt": "24d",
    # EU residue definitions named 'A and B (... expressed as A)'
    "carbendazimandbenomyl": "carbendazim",
    "carbendazimandthiophanatemethyl": "carbendazim",
    "mcpaandmcpb": "mcpa",
    "methylchlorophenoxyaceticacid": "mcpa",
    "metalaxylandmetalaxylm": "metalaxyl",
    "metalaxylm": "metalaxyl",
    "metolachlorandsmetolachlor": "metolachlor",
    "smetolachlor": "metolachlor",
    "sumofdiclofopmethyl": "diclofop",
    "diclofopmethyl": "diclofop",
    "cyanamideincludingsaltsexpressedascyanamide": "cyanamide",
    "hydrogencyanamide": "cyanamide",
    # salts / esters printed with the active ingredient's name
    "paraquatdichloride": "paraquat",
    "fosetylal": "fosetyl",
    "fosetylaluminium": "fosetyl",
    "aluminumtrisoethylphosphonate": "fosetyl",
    "cartaphydrochloride": "cartap",
    "thiocyclamhydrogenoxalate": "thiocyclam",
    "prohexadionecalcium": "prohexadione",
    "haloxyfoprmethyl": "haloxyfop",
    "fenoxaproppethyl": "fenoxapropp",
    "quizalofopptefuryl": "quizalofop",     # EU: 'Quizalofop (sum of quizalofop, its salts, its esters ...)'
    "quizalofopethyl": "quizalofop",
    "propaquizafop": "quizalofop",          # EU residue definition names propaquizafop explicitly
    # misspellings in the FSSAI compendium (checked against the substance's ISO name)
    "ametroctradin": "ametoctradin",
    "ametyrn": "ametryn",
    "cyantranilipole": "cyantraniliprole",
    "epoxyconazole": "epoxiconazole",
    "penoxuslum": "penoxsulam",
    "totalaflatoxins": "aflatoxins_total",
    "aflatoxins": "aflatoxins_total",        # Codex 'Aflatoxins, total', EU 'Aflatoxins (total)'
    "arsenictotal": "arsenic",
    "aflatoxinstotal": "aflatoxins_total",
    "aflatoxintotal": "aflatoxins_total",
    "aflatoxinm1": "aflatoxin_m1",
    "aflatoxinb1": "aflatoxin_b1",
    "ochratoxina": "ochratoxin_a",
    "deoxynivalenol": "deoxynivalenol",
    "deoxynivalenoldon": "deoxynivalenol",
    "methylmercury": "methylmercury",
    "methylmercurycalculatedastheelement": "methylmercury",
    "mercurycalculatedastheelement": "mercury",
    "leadcalculatedastheelement": "lead",
    "arsenicinorganic": "arsenic_inorganic",
    "inorganicarsenic": "arsenic_inorganic",
    "benzoapyrene": "benzo_a_pyrene",
    "benzo_a_pyrene": "benzo_a_pyrene",
    "polychlorinatedbiphenyls": "pcbs",
}

_AMENDMENT_RE = re.compile(r"^\s*\d{1,2}\s*\[\s*|\s*\]+\s*[\"”]?\s*\]*\s*$")


def strip_amendment_marks(s: Optional[str]) -> str:
    """FSSAI compendia mark amended text as '16[Wheat, barley' ... '5]'. Remove
    the leading 'NN[' and trailing ']'s/quotes; nothing else is touched."""
    t = (s or "").replace("”", "").replace("“", "").strip()
    t = re.sub(r"^\s*\d{1,2}\s*\[\s*", "", t)
    t = re.sub(r"[\]\"”]+\s*$", "", t)
    return t.strip()


def clean_text(s: Optional[str]) -> str:
    t = unicodedata.normalize("NFKC", s or "").replace("�", "'")
    t = re.sub(r"\s+", " ", t)
    return t.strip(" ;,")


def _squash(s: str) -> str:
    t = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", t)


# Aliases above that merge DIFFERENT active substances into one residue family
# (isomer-enriched forms, salts/esters covered by a combined residue definition).
# Right for comparing residue limits; wrong for anything that belongs to one
# substance — its EU approval status, its CAS number, its IARC group. Those use
# substance_key(), which applies only the spelling/synonym aliases.
RESIDUE_FAMILY_ALIASES = {
    "benomyl", "sumofbenomylandcarbendazimexpressedascarbendazim", "betacyfluthrin", "zetacypermethrin",
    "alphacypermethrin", "cypermethrins", "lambdacyhalothrin", "gammacyhalothrin", "24daminesalt",
    "carbendazimandbenomyl", "carbendazimandthiophanatemethyl", "mcpaandmcpb", "metalaxylandmetalaxylm",
    "metalaxylm", "metolachlorandsmetolachlor", "smetolachlor", "sumofdiclofopmethyl", "diclofopmethyl",
    "cyanamideincludingsaltsexpressedascyanamide", "haloxyfoprmethyl", "fenoxaproppethyl", "quizalofopptefuryl",
    "quizalofopethyl", "propaquizafop",
}
SUBSTANCE_ALIASES = {k: v for k, v in HAZARD_ALIASES.items() if k not in RESIDUE_FAMILY_ALIASES}


def hazard_key(name: Optional[str]) -> Optional[str]:
    """Residue-comparison key: 'Chlorpyriphos' / 'Chlorpyrifos (R)' -> 'chlorpyrifos';
    'Lambda cyhalothrin' -> 'cyhalothrin' (same residue family as Codex's
    'Cyhalothrin (includes lambda-cyhalothrin)')."""
    return _key(name, HAZARD_ALIASES)


def substance_key(name: Optional[str]) -> Optional[str]:
    """Single-substance key: spelling fixes only, no family merges.
    'Lambda cyhalothrin' -> 'lambdacyhalothrin'."""
    return _key(name, SUBSTANCE_ALIASES)


def _key(name: Optional[str], HAZARD_ALIASES: dict[str, str]) -> Optional[str]:
    """The name before the first parenthesis is the substance (a parenthetical is a
    residue definition or a synonym); a trailing synonym in parentheses is tried
    as well so 'Dichlorvos (DDVP)' and 'Ethofenprox (Etofenprox)' land on one key.
    """
    raw = clean_text(strip_amendment_marks(name))
    raw = re.sub(r"^\([a-z]\)\s*", "", raw)                              # '(c) Mancozeb' list markers
    raw = re.sub(r"\s+and its metabolites?\b.*$", "", raw, flags=re.I)  # 'Fluopyram and its metabolites'
    raw = re.sub(r"\s+as CS2$", "", raw, flags=re.I)                    # '(d) Metiram as CS2'
    if not raw:
        return None
    full = _squash(raw)
    if full in HAZARD_ALIASES:
        return HAZARD_ALIASES[full]
    head = raw.split("(")[0]
    if head.rstrip().endswith("-") or len(_squash(head)) < 3:
        # the parenthesis is part of the chemical name ('2-(Thiocyanomethylthio)...',
        # 'Beta-(4-Chlorophenoxy)...'), not a residue definition
        return HAZARD_ALIASES.get(full, full)
    # ', ' / '; ' / ' - ' end the name; a comma inside a chemical name ('2,4-D',
    # '1,4-Dimethylnaphthalene') has no space after it and is kept.
    head = re.split(r"\s*;\s*|,\s+|\s+-\s+", head)[0]
    k = _squash(head)
    if not k:
        return None
    if k.isdigit():                    # '2, 6-Diisopropylnaphthalene' split at a locant
        return HAZARD_ALIASES.get(full, full)
    if k in HAZARD_ALIASES:
        return HAZARD_ALIASES[k]
    paren = re.findall(r"\(([^()]{2,40})\)", raw)
    for p in paren:
        pk = _squash(p)
        if pk in HAZARD_ALIASES:
            return HAZARD_ALIASES[pk]
    return k


# ---------------------------------------------------------------- limits

_NUM = r"\d+(?:\.\d+)?"


@dataclass
class ParsedLimit:
    value: Optional[Decimal]
    unit: Optional[str]
    at_loq: bool = False
    basis: Optional[str] = None
    status: str = "exact"        # exact | not_numeric | compound | reference (| compound_split, prohibited set by callers)
    note: Optional[str] = None


def _dec(s: str) -> Optional[Decimal]:
    try:
        v = Decimal(s)
    except InvalidOperation:
        return None
    return v if v.is_finite() and v >= 0 else None


_BASIS_PATTERNS = [
    (re.compile(r"\(\s*F\s*\)|\bfat basis\b", re.I), "fat basis"),
    (re.compile(r"carcass fat basis", re.I), "carcass fat basis"),
    (re.compile(r"shell[- ]free basis", re.I), "shell-free basis"),
    (re.compile(r"dry matter basis", re.I), "dry matter basis"),
    (re.compile(r"dry colouring matter basis|colouring\s+matter basis", re.I), "dry colouring matter basis"),
    (re.compile(r"fat[- ]free substance basis|fat free\s+substance", re.I), "fat-free substance basis"),
    (re.compile(r"dried total solids", re.I), "dried total solids basis"),
    (re.compile(r"dried tomato solids", re.I), "dried tomato solids basis"),
    (re.compile(r"dry fat\s*free", re.I), "dry fat-free substance basis"),
]


def parse_limit(raw: Optional[str], default_unit: Optional[str]) -> ParsedLimit:
    """One printed limit cell -> value/unit. Strict: '0.05' / '0.02*' / '5.0 on dry
    matter basis' / '2.0 ppm' parse; 'Wheat-0.05, Rice-2.0 ...' is `compound` (the
    caller may split it); '$' and anything textual is `not_numeric`/`reference`."""
    t = clean_text(strip_amendment_marks(raw))
    if not t:
        return ParsedLimit(None, default_unit, status="not_numeric", note="empty cell")
    typo = re.fullmatch(r"(\d+)\.\s+(\d+)(\*?)", t)      # '0. 4' — a stray space inside one number
    if typo:
        return ParsedLimit(_dec(f"{typo.group(1)}.{typo.group(2)}"), default_unit, at_loq=bool(typo.group(3)),
                           note="printed with a space inside the number ('" + t + "')")
    if t.strip() == "$":
        return ParsedLimit(None, default_unit, status="reference",
                           note="limit is the copper metal-contaminant limit (FSSAI footnote $)")
    basis = None
    for rx, b in _BASIS_PATTERNS:
        if rx.search(t):
            basis = b
            break
    unit = default_unit
    m_unit = re.search(r"\b(ppm|ppb|mg/kg|µg/kg|ug/kg|μg/kg|mg/l|µg/l|ug/l)\b", t, re.I)
    if m_unit:
        u = m_unit.group(1).lower().replace("μ", "µ")
        unit = {"ppm": "mg/kg", "ppb": "µg/kg", "ug/kg": "µg/kg", "ug/l": "µg/l"}.get(u, u)
    nums = re.findall(_NUM, t)
    at_loq = "*" in t
    # one number, optionally with a basis/unit/asterisk around it
    stripped = re.sub(r"\(.*?\)|on\b.*$|ppm|ppb|mg/kg|µg/kg|ug/kg|mg/l|µg/l|\*", " ", t, flags=re.I)
    stripped = re.sub(r"\b(fat|basis|carcass|shell|free|dry|matter|substance|colouring)\b", " ", stripped, flags=re.I)
    if len(nums) == 1 and re.fullmatch(r"\s*" + _NUM + r"\s*", stripped.replace(",", " ")):
        return ParsedLimit(_dec(nums[0]), unit, at_loq=at_loq, basis=basis)
    if len(nums) >= 2 and re.search(r"[A-Za-z]\s*-\s*" + _NUM, t):
        return ParsedLimit(None, unit, at_loq=at_loq, basis=basis, status="compound",
                           note="several foods with their own limits in one cell")
    return ParsedLimit(None, unit, at_loq=at_loq, basis=basis, status="not_numeric",
                       note="not a single unambiguous number")


def split_compound(food: str, raw_limit: str) -> list[tuple[str, Decimal, bool]]:
    """'Food grains' + 'Wheat-0.05, Rice-2.0 and other food grains 0.1' ->
    [('Food grains (Wheat)', 0.05, False), ('Food grains (Rice)', 2.0, False),
     ('Food grains (other food grains)', 0.1, False)]. Returns [] unless every
    number in the cell is accounted for (otherwise the row stays `compound`)."""
    t = clean_text(strip_amendment_marks(raw_limit)).replace("–", "-")
    t = re.sub(r"(\d)(and\b)", r"\1 \2", t)
    # Every comma/'and'-separated segment must be exactly "<name> [-] <number>[*]";
    # one segment that is not (e.g. 'Fruit and Vegetables 5' splits into 'Fruit')
    # means the cell is left whole rather than guessed at.
    pairs = []
    for seg in re.split(r",|\band\b", t):
        seg = seg.strip()
        if not seg:
            continue
        m = re.fullmatch(r"([A-Za-z][A-Za-z /&()'.]*?)\s*-?\s*(" + _NUM + r")(\*?)", seg)
        if not m:
            return []
        pairs.append((m.group(1).strip(), m.group(2), m.group(3) == "*"))
    nums = re.findall(_NUM, t)
    if len(pairs) < 2 or len(pairs) != len(nums):
        return []
    base = clean_text(strip_amendment_marks(food))
    out = []
    for name, num, loq in pairs:
        v = _dec(num)
        if v is None:
            return []
        out.append((f"{base} ({name})", v, loq))
    return out


def to_mg_per_kg(value: Optional[Decimal], unit: Optional[str]) -> Optional[Decimal]:
    if value is None or not unit:
        return None
    u = unit.lower().replace("μ", "µ")
    if u in ("mg/kg", "ppm"):
        return value
    if u in ("µg/kg", "ug/kg", "ppb"):
        return value / Decimal(1000)
    return None


# ---------------------------------------------------------------- rows + loading

@dataclass
class StandardRow:
    jurisdiction: str
    standard_type: str
    hazard_raw: str
    hazard_class: str
    food_raw: str
    limit_raw: str
    limit_value: Optional[Decimal]
    limit_unit: Optional[str]
    parse_status: str
    legal_reference: str
    source_url: str
    hazard_key: Optional[str] = None
    food_code: Optional[str] = None
    at_loq: bool = False
    limit_basis: Optional[str] = None
    note: Optional[str] = None
    source_page: Optional[int] = None
    applicability: Optional[str] = None    # e.g. EU 'Applicable' / 'No longer applicable'
    food_keys: list = field(default_factory=list)
    food_match: Optional[str] = None       # 'specific' | 'group' (standards_foods)
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        assert self.jurisdiction in JURISDICTIONS, self.jurisdiction
        assert self.standard_type in STANDARD_TYPES, self.standard_type
        assert self.hazard_class in HAZARD_CLASSES, self.hazard_class
        if self.hazard_key is None:
            self.hazard_key = hazard_key(self.hazard_raw)

    @property
    def limit_mg_per_kg(self) -> Optional[Decimal]:
        return to_mg_per_kg(self.limit_value, self.limit_unit)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


_INSERT = """INSERT INTO food_standards
    (jurisdiction, standard_type, hazard_raw, hazard_key, hazard_class, food_raw, food_code, food_keys, food_match,
     limit_raw, limit_value, limit_unit, limit_mg_per_kg, at_loq, limit_basis, parse_status, note,
     applicability, legal_reference, source_url, source_page, snapshot_id, extra)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""


def replace_snapshot(conn, jurisdiction: str, standard_types: set[str], rows: list[StandardRow], *,
                     document_title: str, document_url: str, document_version: Optional[str],
                     document_sha256: Optional[str], parser_version: str) -> dict:
    """Replace every row of (jurisdiction, standard_types) with `rows`, in one
    transaction, and record the snapshot. Refuses to replace a populated slice
    with nothing (a broken fetch must not wipe the table)."""
    assert all(r.jurisdiction == jurisdiction and r.standard_type in standard_types for r in rows)
    from pipeline.sources.standards_foods import match as match_food
    for r in rows:
        if not r.food_keys:
            r.food_keys, r.food_match = match_food(r.jurisdiction, r.food_raw, r.food_code)
    types = sorted(standard_types)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM food_standards WHERE jurisdiction=%s AND standard_type = ANY(%s)",
                    (jurisdiction, types))
        before = int(cur.fetchone()[0])
        if not rows and before:
            raise RuntimeError(f"refusing to replace {before} {jurisdiction} rows with an empty parse")
        cur.execute(
            """INSERT INTO standards_snapshots (jurisdiction, standard_types, document_title, document_url,
                   document_version, document_sha256, parser_version, rows_loaded)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (jurisdiction, types, document_title, document_url, document_version, document_sha256,
             parser_version, len(rows)))
        snap = cur.fetchone()[0]
        cur.execute("DELETE FROM food_standards WHERE jurisdiction=%s AND standard_type = ANY(%s)",
                    (jurisdiction, types))
        for r in rows:
            cur.execute(_INSERT, (
                r.jurisdiction, r.standard_type, r.hazard_raw, r.hazard_key, r.hazard_class, r.food_raw,
                r.food_code, list(r.food_keys), r.food_match, r.limit_raw, r.limit_value, r.limit_unit, r.limit_mg_per_kg, r.at_loq,
                r.limit_basis, r.parse_status, r.note, r.applicability, r.legal_reference, r.source_url,
                r.source_page, snap, json.dumps(r.extra, default=str) if r.extra else None))
    conn.commit()
    return {"snapshot_id": snap, "rows_before": before, "inserted": len(rows)}


def summarise(rows: list[StandardRow]) -> dict:
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r.parse_status] = by_status.get(r.parse_status, 0) + 1
    return {
        "rows": len(rows),
        "hazards": len({r.hazard_key for r in rows}),
        "foods": len({r.food_raw for r in rows}),
        "by_parse_status": by_status,
    }


def row_dict(r: StandardRow) -> dict:
    d = asdict(r)
    d["limit_mg_per_kg"] = r.limit_mg_per_kg
    return d
