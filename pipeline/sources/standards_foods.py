"""
Food crosswalk: which printed food name in each rule-book is "rice", "dried
chilli", "tea" ...  so a limit in India's FSSAI regulations can be compared
with the EU, Codex and US limit for the same food.

Code-owned and reviewable on purpose: every mapping below was read off the
printed names in the four rule-books (FSSAI compendium Version IX, EU Annex I
product codes, Codex commodity codes, 40 CFR 180 commodity names) — nothing is
fuzzy-matched at run time.

Two kinds of match, kept apart because they mean different things:
  specific  the row names this food ('Rice', EU 0500060, Codex GC 0649, US 'Rice, grain')
  group     the row names a group that legally covers this food ('Food grains',
            Codex 'Cereal grains (group)' GC 0080, US 'Grain, cereal, group 15').
A comparison prefers a specific row and falls back to a group row, and says
which one it used. Group memberships are only listed where the rule-book's own
group definition plainly includes the food; uncertain ones are left out (an
unmapped row is still stored, it just isn't compared).
"""

from __future__ import annotations

import re
from typing import Optional

CEREALS = ["rice", "wheat", "maize", "sorghum", "millet"]
PULSES = ["chickpea", "lentil", "pigeon_pea", "black_gram", "green_gram", "dry_beans", "dry_peas"]
OILSEEDS = ["groundnut", "mustard_seed", "sesame", "cottonseed", "sunflower_seed", "soybean"]
SPICES = ["chilli_dried", "black_pepper", "cardamom", "cumin", "coriander_seed", "turmeric", "ginger"]
FRUITS = ["mango", "banana", "grapes", "pomegranate", "apple", "orange", "lemon_lime", "papaya", "guava", "pineapple"]
VEGETABLES = ["tomato", "potato", "onion", "brinjal", "okra", "cabbage", "cauliflower", "chilli_fresh", "cucumber",
              "spinach"]

# key: (display name, food group)
FOODS: dict[str, tuple[str, str]] = {
    "rice": ("Rice", "cereal"), "wheat": ("Wheat", "cereal"), "maize": ("Maize", "cereal"),
    "sorghum": ("Sorghum (jowar)", "cereal"), "millet": ("Millets (bajra etc.)", "cereal"),
    "chickpea": ("Chickpea (Bengal gram)", "pulse"), "lentil": ("Lentil (masoor)", "pulse"),
    "pigeon_pea": ("Pigeon pea (red gram, tur)", "pulse"), "black_gram": ("Black gram (urad)", "pulse"),
    "green_gram": ("Green gram (mung)", "pulse"), "dry_beans": ("Dry beans", "pulse"), "dry_peas": ("Dry peas", "pulse"),
    "soybean": ("Soybean", "oilseed"), "groundnut": ("Groundnut (peanut)", "oilseed"),
    "mustard_seed": ("Mustard seed", "oilseed"), "sesame": ("Sesame seed", "oilseed"),
    "cottonseed": ("Cottonseed", "oilseed"), "sunflower_seed": ("Sunflower seed", "oilseed"),
    "tea": ("Tea", "beverage"), "coffee": ("Coffee beans", "beverage"),
    "chilli_dried": ("Dried chilli", "spice"), "black_pepper": ("Black pepper", "spice"),
    "cardamom": ("Cardamom", "spice"), "cumin": ("Cumin", "spice"), "coriander_seed": ("Coriander seed", "spice"),
    "turmeric": ("Turmeric", "spice"), "ginger": ("Ginger", "spice"),
    "mango": ("Mango", "fruit"), "banana": ("Banana", "fruit"), "grapes": ("Grapes", "fruit"),
    "pomegranate": ("Pomegranate", "fruit"), "apple": ("Apple", "fruit"), "orange": ("Orange", "fruit"),
    "lemon_lime": ("Lemon / lime", "fruit"), "papaya": ("Papaya", "fruit"), "guava": ("Guava", "fruit"),
    "pineapple": ("Pineapple", "fruit"),
    "tomato": ("Tomato", "vegetable"), "potato": ("Potato", "vegetable"), "onion": ("Onion", "vegetable"),
    "brinjal": ("Brinjal (eggplant)", "vegetable"), "okra": ("Okra (bhindi)", "vegetable"),
    "cabbage": ("Cabbage", "vegetable"), "cauliflower": ("Cauliflower", "vegetable"),
    "chilli_fresh": ("Green chilli / peppers", "vegetable"), "cucumber": ("Cucumber", "vegetable"),
    "spinach": ("Spinach", "vegetable"),
    "sugarcane": ("Sugarcane", "other"), "milk": ("Milk", "animal"), "eggs": ("Eggs", "animal"),
    "poultry_meat": ("Poultry meat", "animal"), "bovine_meat": ("Bovine meat", "animal"), "honey": ("Honey", "animal"),
    "fish": ("Fish", "animal"), "coconut": ("Coconut", "other"),
}

# ---- specific matches -------------------------------------------------------
# India: normalised printed names (lower case, single spaces)
IN_SPECIFIC = {
    "rice": ["rice", "paddy", "food grains (rice)", "rice, polished"],
    "wheat": ["wheat", "wheat grains", "food grains (wheat)"],
    "maize": ["maize", "corn", "food grains (maize)", "maize cob (kernels)"],
    "sorghum": ["sorghum", "food grains (sorghum)", "jowar"],
    "millet": ["pearl millet (bajra)", "bajra", "millets"],
    "chickpea": ["bengal gram", "gram", "chickpea", "chick pea"],
    "pigeon_pea": ["red gram", "pigeon pea", "pigeonpea", "arhar"],
    "black_gram": ["black gram", "blackgram", "urd", "urad"],
    "green_gram": ["green gram", "greengram", "moong", "mung"],
    "soybean": ["soya bean", "soybean", "soyabean", "soya bean seed", "soyabean seed"],
    "groundnut": ["groundnut", "ground nut", "groundnut seed", "groundnut seeds", "ground nut seed", "peanut"],
    "mustard_seed": ["mustard seed", "mustard"],
    "sesame": ["sesamum", "sesame", "sesame seed", "til"],
    "cottonseed": ["cotton seed", "cottonseed", "cotton seed (whole)"],
    "sunflower_seed": ["sunflower seed", "sunflower"],
    "tea": ["tea", "green tea"],
    "coffee": ["coffee", "coffee beans"],
    "chilli_dried": ["dried chilli", "dry chilli", "dried chillies", "chilli powder"],
    "black_pepper": ["black pepper", "pepper"],
    "cardamom": ["cardamom", "cardamom (large)", "small cardamom"],
    "cumin": ["cumin", "cumin seed"],
    "coriander_seed": ["coriander", "coriander seed"],
    "turmeric": ["turmeric", "turmeric whole and powder"],
    "ginger": ["ginger"],
    "mango": ["mango"], "banana": ["banana", "banana (whole)"], "grapes": ["grapes", "grape"],
    "pomegranate": ["pomegranate"], "apple": ["apple"], "orange": ["citrus (orange)", "citrus (sweet orange)", "orange"],
    "lemon_lime": ["citrus (acid lime)", "lime", "lemon"], "papaya": ["papaya"], "guava": ["guava"],
    "pineapple": ["pineapple", "pine apple"],
    "tomato": ["tomato"], "potato": ["potato", "potatoes and onions (potato)", "potato, peeled"],
    "onion": ["onion", "potatoes and onions (onions)"], "brinjal": ["brinjal", "eggplant"], "okra": ["okra", "bhindi"],
    "cabbage": ["cabbage"], "cauliflower": ["cauliflower"], "chilli_fresh": ["chilli", "chilly", "green chilli"],
    "cucumber": ["cucumber", "gherkin"], "spinach": ["spinach"],
    "sugarcane": ["sugarcane", "sugar cane"], "milk": ["milk and milk products", "milk", "milks", "milk (liquid)"],
    "eggs": ["eggs", "egg"], "fish": ["fish"], "coconut": ["coconut"],
}
EU_SPECIFIC = {
    "rice": ["0500060"], "wheat": ["0500090"], "maize": ["0500030"], "sorghum": ["0500080"], "millet": ["0500040"],
    "dry_beans": ["0300010"], "lentil": ["0300020"], "dry_peas": ["0300030"],
    "groundnut": ["0401020"], "sesame": ["0401040"], "soybean": ["0401070"], "mustard_seed": ["0401080"],
    "cottonseed": ["0401090"], "tea": ["0610000"], "coffee": ["0620000"],
    "coriander_seed": ["0810040"], "cumin": ["0810050"], "cardamom": ["0820040"], "black_pepper": ["0820060"],
    "ginger": ["0840020"], "turmeric": ["0840030"],
    "orange": ["0110020"], "lemon_lime": ["0110030", "0110040"], "apple": ["0130010"], "grapes": ["0151010"],
    "banana": ["0163020"], "mango": ["0163030"], "papaya": ["0163040"], "pomegranate": ["0163050"],
    "guava": ["0163070"], "pineapple": ["0163080"], "coconut": ["0120050"],
    "potato": ["0211000"], "onion": ["0220020"], "tomato": ["0231010"], "chilli_fresh": ["0231020"],
    "brinjal": ["0231030"], "okra": ["0231040"], "cucumber": ["0232010"], "cauliflower": ["0241020"],
    "cabbage": ["0242020"], "spinach": ["0252010"],
    "sugarcane": ["0900020"], "bovine_meat": ["1012010"], "poultry_meat": ["1016010"], "milk": ["1020010"],
    "eggs": ["1030010"], "honey": ["1040000"],
}
CODEX_SPECIFIC = {
    "rice": ["GC 0649", "CM 0649", "CM 1205"], "wheat": ["GC 0654"], "maize": ["GC 0645"], "sorghum": ["GC 0651"],
    "millet": ["GC 0646"], "chickpea": ["VD 0524"], "lentil": ["VD 0533"], "dry_peas": ["VD 0072"],
    "dry_beans": ["VD 0071"], "pigeon_pea": ["VD 0537"], "soybean": ["VD 0541"], "groundnut": ["SO 0697"],
    "mustard_seed": ["SO 0485"], "sesame": ["SO 0700"], "cottonseed": ["SO 0691"], "sunflower_seed": ["SO 0702"],
    "tea": ["DT 1114"], "coffee": ["SB 0716"], "chilli_dried": ["HS 0444"], "black_pepper": ["HS 0790"],
    "cardamom": ["HS 0775"], "cumin": ["HS 0780"], "coriander_seed": ["HS 0779"], "turmeric": ["HS 0794"],
    "ginger": ["HS 0784"],
    "mango": ["FI 0345"], "banana": ["FI 0327"], "grapes": ["FB 0269"], "pomegranate": ["FI 0355"],
    "apple": ["FP 0226"], "papaya": ["FI 0350"], "guava": ["FT 0336"], "pineapple": ["FI 0353"],
    "tomato": ["VO 0448"], "potato": ["VR 0589"], "onion": ["VA 0385"], "brinjal": ["VO 0440"], "okra": ["VO 0442"],
    "cabbage": ["VB 0041"], "cauliflower": ["VB 0404"], "chilli_fresh": ["VO 0444"], "cucumber": ["VC 0424"],
    "spinach": ["VL 0502"], "sugarcane": ["GS 0659"], "milk": ["ML 0812"], "eggs": ["PE 0840"],
    "bovine_meat": ["MM 0812"], "poultry_meat": ["PM 0110"],
}
US_SPECIFIC = {
    "rice": ["rice, grain"], "wheat": ["wheat, grain"], "maize": ["corn, field, grain", "corn, pop, grain"],
    "sorghum": ["sorghum, grain, grain", "sorghum, grain"], "millet": ["millet, grain", "millet, proso, grain"],
    "chickpea": ["chickpea, dry seed"], "lentil": ["lentil, seed", "lentil, dry seed"], "dry_peas": ["pea, dry, seed", "pea, dry"],
    "dry_beans": ["bean, dry, seed", "bean, dry seed", "bean, dry"], "soybean": ["soybean, seed"],
    "groundnut": ["peanut"], "mustard_seed": ["mustard, seed"], "sesame": ["sesame, seed"],
    "cottonseed": ["cotton, undelinted seed"], "sunflower_seed": ["sunflower, seed"],
    "tea": ["tea, dried", "tea"], "coffee": ["coffee, green bean", "coffee, bean, green"],
    "black_pepper": ["pepper, black"], "coriander_seed": ["coriander, seed"], "ginger": ["ginger"],
    "mango": ["mango"], "banana": ["banana"], "grapes": ["grape"], "pomegranate": ["pomegranate"], "apple": ["apple"],
    "orange": ["orange", "orange, sweet"], "lemon_lime": ["lemon", "lime"], "papaya": ["papaya"], "guava": ["guava"],
    "pineapple": ["pineapple"], "tomato": ["tomato"], "potato": ["potato"], "onion": ["onion, bulb"],
    "brinjal": ["eggplant"], "okra": ["okra"], "cabbage": ["cabbage"], "cauliflower": ["cauliflower"],
    "chilli_fresh": ["pepper, nonbell", "pepper"], "cucumber": ["cucumber"], "spinach": ["spinach"],
    "sugarcane": ["sugarcane, cane"], "milk": ["milk"], "eggs": ["egg"], "poultry_meat": ["poultry, meat"],
    "bovine_meat": ["cattle, meat"], "honey": ["honey"],
}

# ---- group matches ------------------------------------------------------------
IN_GROUPS = {
    "food grains": CEREALS, "food grains (other food grains)": CEREALS, "food grains (food grains)": CEREALS,
    "cereal and cereal products": CEREALS, "cereal grains, except buckwheat, canihua and quinoa": CEREALS,
    "pulses": PULSES, "pulses, excluding soybean dry": [p for p in PULSES],
    "oil seeds": OILSEEDS, "spices/spice mix": SPICES,
    "fruits": FRUITS, "fruit": FRUITS, "vegetables": VEGETABLES,
    "fruits and vegetables": FRUITS + VEGETABLES, "fruits & vegetables": FRUITS + VEGETABLES,
    "citrus": ["orange", "lemon_lime"], "citrus fruits": ["orange", "lemon_lime"],
    "meat and meat products": ["bovine_meat", "poultry_meat"], "meat and poultry": ["bovine_meat", "poultry_meat"],
    "meat & poultry": ["bovine_meat", "poultry_meat"],
    "cauliflower and cabbage": ["cauliflower", "cabbage"], "okra and leafy vegetables": ["okra", "spinach"],
    "leafy vegetables": ["spinach"],
    # metal / mycotoxin tables (FSS CTR 2.1, 2.2): group names follow the Codex classification
    "cereal grains, except buckwheat, canihua and quinoa (excluding wheat and rice; and bran and germ)":
        ["maize", "sorghum", "millet"],
    "fruiting vegetables other than cucurbits(excluding mushrooms)": ["tomato", "brinjal", "chilli_fresh", "okra"],
    "fruiting vegetables other than cucurbits (excluding tomatoes and edible fungi)": ["brinjal", "chilli_fresh", "okra"],
    "fruiting vegetables, cucurbits": ["cucumber"],
    "brassica vegetables excluding kale": ["cabbage", "cauliflower"], "brassica vegetables": ["cabbage", "cauliflower"],
    "bulb vegetables": ["onion"], "root and tuber vegetables": ["potato"], "pome fruits": ["apple"],
    "berries and other small fruits": ["grapes"],
    "assorted subtropical fruits, edible peel": ["guava"],
    "assorted subtropical fruits, inedible peel": ["banana", "mango", "papaya", "pineapple", "pomegranate"],
    "meat of cattle, sheep and pig (also applies to fat from meat)": ["bovine_meat"],
    "oilseeds or oil: ready to eat": OILSEEDS, "oilseeds or oil: oilseeds for further processing": OILSEEDS,
    "dehydrated onions, dried herbs and spices, curry powder and mix masalas, flavourings, alginic acid, alignates, "
    "agar, carrageen and similar products derived from seaweed": SPICES,
}
# Catch-all rows ('Other vegetables', 'Foods not specified'): used for a food only
# when no specific or named-group row covers it.
IN_RESIDUAL = {
    "other fruits": FRUITS, "fruits (other fruits)": FRUITS, "other vegetables": VEGETABLES,
    "fruit and vegetables (other fruits & other vegetables)": FRUITS + VEGETABLES,
    "foods not specified": list(FOODS),
}
IN_SPECIFIC_EXTRA = {   # contaminant-table names that name foods directly
    "milks (concentration factor shall be applied to partially or wholly dehydrated milks)": ["milk"],
    "poultry meat": ["poultry_meat"],
    "wheat, wheat bran, rye, barley, coffee": ["wheat", "coffee"],
    "wheat, wheat bran, barley": ["wheat"],
}

# EU Regulation 2023/915 Annex I entries are free text; these anchored patterns
# map the entries that plainly cover a food (lower-cased, whitespace-normalised).
EU_CONTAMINANT_RULES: list[tuple[str, list[str], str]] = [
    (r"^maize and rice to be subjected to sorting", ["maize", "rice"], "specific"),
    (r"^unprocessed maize grains", ["maize"], "specific"),
    (r"^non-parboiled milled rice", ["rice"], "specific"),
    (r"^parboiled rice and husked rice", ["rice"], "specific"),
    (r"^rice, quinoa, wheat bran and wheat gluten", ["rice"], "specific"),
    (r"^cereals$", CEREALS, "group"),
    (r"^cereals except products listed", ["wheat", "maize", "sorghum", "millet"], "group"),
    (r"^cereals and products derived from cereals except", CEREALS, "group"),
    (r"^unprocessed cereal grains", CEREALS, "group"),
    (r"^pulses$", PULSES, "group"),
    (r"^pulses except products listed", PULSES, "group"),
    (r"^peanuts and soy beans", ["groundnut", "soybean"], "specific"),
    (r"^mustard seeds$", ["mustard_seed"], "specific"),
    (r"^linseeds and sunflower seeds", ["sunflower_seed"], "specific"),
    (r"^groundnuts \(peanuts\) and other oilseeds", ["groundnut"], "specific"),
    (r"^following dried spices: capsicum", ["chilli_dried", "black_pepper", "turmeric"], "specific"),
    (r"^capsicum spp\. \(dried", ["chilli_dried"], "specific"),
    (r"^dried spices except products listed", ["black_pepper", "cardamom", "cumin", "coriander_seed", "turmeric",
                                               "ginger"], "group"),
    (r"^dried spices$", SPICES, "group"),
    (r"^seed spices$", ["cumin", "coriander_seed"], "group"),
    (r"^fruit spices$", ["black_pepper", "cardamom"], "group"),
    (r"^root and rhizome spices$", ["turmeric", "ginger"], "group"),
    (r"^ginger \( ?zingiber officinale ?\) \(dried\)", ["ginger"], "specific"),
    # 'Fresh ginger, fresh turmeric' (3.1.2.2) is deliberately not mapped: the foods
    # here are the dried spices India regulates ('Turmeric whole and powder'), which
    # fall under 'Root and rhizome spices' (3.1.12.4).
    (r"^raw milk", ["milk"], "specific"),
    (r"^roasted coffee beans", ["coffee"], "specific"),
    (r"^root and tuber vegetables except", ["potato"], "group"),
    (r"^bulb vegetables", ["onion"], "group"),
    (r"^fruiting vegetables except products listed in 3\.1\.4\.2", ["tomato", "brinjal", "chilli_fresh", "okra",
                                                                   "cucumber"], "group"),
    (r"^fruiting vegetables except products listed in 3\.2\.4\.2", ["tomato", "chilli_fresh", "okra", "cucumber"],
     "group"),
    (r"^aubergines$", ["brinjal"], "specific"),
    (r"^brassica vegetables other than", ["cabbage", "cauliflower"], "group"),
    (r"^brassica except products listed", ["cabbage", "cauliflower"], "group"),
    (r"^leaf vegetables excluding fresh herbs", ["spinach"], "group"),
    (r"^spinaches and similar leaves", ["spinach"], "specific"),
    (r"^fresh spinach", ["spinach"], "specific"),
    (r"^fruits other than cranberries", FRUITS, "group"),
    (r"^fruits except products listed in 3\.2\.1\.2", ["pomegranate", "guava"], "group"),
    (r"^citrus fruits, pome fruits, stone fruits, table olives, kiwi fruits, bananas, mangoes, papayas and pineapples",
     ["orange", "lemon_lime", "apple", "banana", "mango", "papaya", "pineapple"], "specific"),
    (r"^berries and small fruits, except", ["grapes"], "group"),
    (r"^meat of bovine animals, sheep, pig and poultry", ["bovine_meat", "poultry_meat"], "group"),
    (r"^muscle meat of fish except", ["fish"], "group"),
    (r"^honey$", ["honey"], "specific"),
]
_EU_CONT = [(re.compile(rx), keys, kind) for rx, keys, kind in EU_CONTAMINANT_RULES]

# Codex CXS 193 commodity names (contaminant rows carry no Codex commodity code).
CODEX_CONTAMINANT_NAMES: dict[str, tuple[list[str], str]] = {
    "peanuts": (["groundnut"], "specific"),
    "chili pepper, nutmeg": (["chilli_dried"], "specific"),
    "chili pepper, paprika, nutmeg": (["chilli_dried"], "specific"),
    "maize grain, destined for further processing": (["maize"], "specific"),
    "raw maize grain": (["maize"], "specific"),
    "husked rice": (["rice"], "specific"), "polished rice": (["rice"], "specific"),
    "rice, husked": (["rice"], "specific"), "rice, polished": (["rice"], "specific"),
    "sorghum grain, destined for further processing": (["sorghum"], "specific"),
    "cereal grains (wheat, maize and barley) destined for further processing": (["wheat", "maize"], "specific"),
    "wheat": (["wheat"], "specific"), "milks": (["milk"], "specific"), "milk": (["milk"], "specific"),
    "fish": (["fish"], "specific"),
    "meat and fat of poultry": (["poultry_meat"], "specific"),
    "meat of cattle, pigs and sheep": (["bovine_meat"], "group"),
    "cereal grains": (CEREALS, "group"), "pulses": (PULSES, "group"),
    "brassica vegetables": (["cabbage", "cauliflower"], "group"), "bulb vegetables": (["onion"], "group"),
    "fruiting vegetables": (["tomato", "brinjal", "chilli_fresh", "okra", "cucumber"], "group"),
    "leafy vegetables": (["spinach"], "group"), "root and tuber vegetables": (["potato"], "group"),
    "fruits": (FRUITS, "group"), "berries and other small fruits": (["grapes"], "group"),
    "spices, dried seeds": (["cumin", "coriander_seed"], "group"),
    "spices, dried fruit and berries": (["black_pepper", "cardamom"], "group"),
    "spices, dried rhizomes and roots": (["turmeric", "ginger"], "group"),
    "white and refined sugar, corn and maple syrups, honey": (["honey"], "group"),
}
CODEX_GROUPS = {
    "GC 0080": CEREALS, "VD 0070": PULSES + ["soybean"], "FC 0001": ["orange", "lemon_lime"],
    "FC 0004": ["orange"], "FC 0002": ["lemon_lime"], "VO 0051": ["chilli_fresh"], "VO 2046": ["brinjal"],
    "VO 2045": ["tomato"], "HS 0191": ["black_pepper", "cardamom"], "HS 0190": ["cumin", "coriander_seed"],
    "HS 0193": ["turmeric", "ginger"], "HS 0093": SPICES, "ML 0106": ["milk"], "PE 0112": ["eggs"],
    "FP 0009": ["apple"], "VB 0040": ["cabbage", "cauliflower"], "VC 0045": ["cucumber"], "VA 0035": ["onion"],
    "MM 0095": ["bovine_meat"],
}
US_GROUPS = {
    "grain, cereal, group 15": CEREALS,
    "fruit, citrus, group 10": ["orange", "lemon_lime"], "fruit, citrus, group 10-10": ["orange", "lemon_lime"],
    "fruit, pome, group 11": ["apple"], "fruit, pome, group 11-10": ["apple"],
    "vegetable, fruiting, group 8": ["tomato", "chilli_fresh", "brinjal"],
    "vegetable, fruiting, group 8-10": ["tomato", "chilli_fresh", "brinjal", "okra"],
    "vegetable, cucurbit, group 9": ["cucumber"],
    "vegetable, bulb, group 3-07": ["onion"], "onion, bulb, subgroup 3-07a": ["onion"],
    "vegetable, tuberous and corm, subgroup 1c": ["potato"],
    "brassica, head and stem, subgroup 5a": ["cabbage", "cauliflower"],
    "pea and bean, dried shelled, except soybean, subgroup 6c": PULSES,
    "fruit, small vine climbing, except fuzzy kiwifruit, subgroup 13-07f": ["grapes"],
}


def _norm(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower()).strip(" .;,")


def _invert(d: dict[str, list[str]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key, names in d.items():
        for n in names:
            out.setdefault(_norm(n), []).append(key)
    return out


_IN = _invert({**IN_SPECIFIC, **{}})
for _n, _keys in IN_SPECIFIC_EXTRA.items():
    _IN.setdefault(_norm(_n), []).extend(_keys)
_EU = _invert(EU_SPECIFIC)
_CX = _invert(CODEX_SPECIFIC)
_US = _invert(US_SPECIFIC)
_IN_G = {_norm(k): v for k, v in IN_GROUPS.items()}
_IN_R = {_norm(k): v for k, v in IN_RESIDUAL.items()}
_CX_G = {_norm(k): v for k, v in CODEX_GROUPS.items()}
_CX_CONT = {_norm(k): v for k, v in CODEX_CONTAMINANT_NAMES.items()}
_US_G = {_norm(k): v for k, v in US_GROUPS.items()}


def match(jurisdiction: str, food_raw: str, food_code: Optional[str] = None) -> tuple[list[str], Optional[str]]:
    """-> (food_keys, 'specific' | 'group' | 'residual' | None)."""
    name = _norm(food_raw)
    code = _norm(food_code)
    if jurisdiction == "IN":
        # the contaminant tables print 'Rice, polished' / 'Wheat' etc. as well
        if name in _IN:
            return list(dict.fromkeys(_IN[name])), "specific"
        if name in _IN_G:
            return list(_IN_G[name]), "group"
        if name in _IN_R:
            return list(_IN_R[name]), "residual"
    elif jurisdiction == "EU":
        if re.fullmatch(r"\d\.\d{1,2}(\.\d{1,2})*", code or ""):      # Reg. 2023/915 Annex I entry
            for rx, keys, kind in _EU_CONT:
                if rx.search(name):
                    return list(keys), kind
            return [], None
        if code in _EU:
            return _EU[code], "specific"
    elif jurisdiction == "CODEX":
        if not code and name in _CX_CONT:          # CXS 193 contaminant rows: name only
            keys, kind = _CX_CONT[name]
            return list(keys), kind
        if code in _CX:
            return _CX[code], "specific"
        if code in _CX_G:
            return list(_CX_G[code]), "group"
    elif jurisdiction == "US":
        if name in _US:
            return _US[name], "specific"
        if name in _US_G:
            return list(_US_G[name]), "group"
    return [], None


def food_keys_for(jurisdiction: str, food_raw: str, food_code: Optional[str] = None) -> list[str]:
    return match(jurisdiction, food_raw, food_code)[0]


def food_match_for(jurisdiction: str, food_raw: str, food_code: Optional[str] = None) -> Optional[str]:
    return match(jurisdiction, food_raw, food_code)[1]


def foods_table() -> list[dict]:
    return [{"food_key": k, "name": v[0], "food_group": v[1]} for k, v in FOODS.items()]


def _check():
    every = set(FOODS)
    for d in (IN_SPECIFIC, EU_SPECIFIC, CODEX_SPECIFIC, US_SPECIFIC):
        assert set(d) <= every, set(d) - every
    for d in (IN_GROUPS, IN_RESIDUAL, IN_SPECIFIC_EXTRA, CODEX_GROUPS, US_GROUPS):
        for v in d.values():
            assert set(v) <= every, set(v) - every
    for _, keys, kind in EU_CONTAMINANT_RULES:
        assert set(keys) <= every and kind in ("specific", "group"), keys
    for keys, kind in CODEX_CONTAMINANT_NAMES.values():
        assert set(keys) <= every and kind in ("specific", "group"), keys


_check()
