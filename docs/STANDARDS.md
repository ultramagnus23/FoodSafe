# Food standards: India vs EU vs Codex vs US

What FoodSafe holds about **legal limits** for hazards in food, how each rule-book is
read, how they are compared, and what the comparison can and cannot say.

A legal limit (a pesticide maximum residue limit, MRL, or a contaminant maximum
level, ML) is a **regulatory line**. It is set from agricultural practice and
checked against health-based guidance values. A higher limit is not proof that
food is unsafe, and a lower one is not proof that it is safe. The health-based
guidance values (ADI, ARfD, tolerable intakes) are stored next to the limits,
with their source, so a reader can see *why* a limit exists.

## The four rule-books

| Rule-book | What is read | How | Parser | Confidence |
|---|---|---|---|---|
| **India** — FSS (Contaminants, Toxins and Residues) Regulations, 2011 | the regulator's consolidated compendium, Version IX (03.02.2026): pesticide MRLs (213 pesticides), metals, mycotoxins, naturally occurring toxins, PCBs/BaP, marine biotoxins, melamine, histamine, antibiotics in seafood, drugs banned in food animals | ruled-table extraction from the PDF (pdfplumber) | `pipeline/sources/standards_fssai.py` | medium |
| **EU** — Reg. (EC) 396/2005 (pesticide MRLs) | every *applicable* MRL for ~50 India-relevant foods (cereals, pulses, oilseeds, tea, coffee, spices, tropical fruit, vegetables, milk, eggs, meat, honey); approval status and ADI/ARfD/AOEL of every active substance | EU Pesticides Database public API (DG SANTE, v3.0) | `standards_eu.py` | high |
| **EU** — Reg. (EU) 2023/915 (contaminants) | all of Annex I, latest consolidated version on EUR-Lex | EUR-Lex consolidated HTML tables | `standards_eu_contaminants.py` | high |
| **Codex** — pesticide MRLs | every adopted Codex MRL (CXL) for the 240 pesticides in the Codex online database, with JMPR ADIs | the database's own JSON feed | `standards_codex.py` | high |
| **Codex** — CXS 193-1995 (contaminants), amended 2025 | every maximum level, plus each contaminant's *toxicological guidance value* text from JECFA | FAO's official PDF | `standards_codex_contaminants.py` | low (PDF, no total-row check) |
| **US** — 40 CFR Part 180 Subpart C | every pesticide tolerance (general, regional, time-limited, indirect) | eCFR versioner API (XML) | `standards_us.py` | high |

Confidence levels come from the project-wide rubric in `api/source_registry.py`
(`standards_fssai`, `standards_eu`, `standards_codex`, `standards_us`).

### How each is read, and what makes a value trustworthy

* **Every printed cell is kept** (`hazard_raw`, `food_raw`, `limit_raw`). A number is
  stored only when the cell is one unambiguous number (`parse_status = exact`).
  Everything else keeps its text and says why it has no value: `compound` (several
  foods in one cell that could not be split exactly), `reference` (FSSAI's `$`: the
  copper metal limit applies), `not_numeric`, `prohibited`.
* **FSSAI compendium:** amendment brackets (`16[ ... ]`) are removed; the legend is
  decoded (`*` = MRL at the limit of quantification, `(F)` = fat basis, `$` = copper
  limit). A cell such as `Wheat-0.05, Rice-2.0 and other food grains 0.1` is split
  into one row per food **only if every number in it is accounted for**. Integrity
  check: the pesticide table's serial numbers must run 1..N with no gap or repeat,
  and N must equal the last serial printed in the text. A dropped page fails the run.
* **EU pesticides API:** the API repeats records across pages; exactly one
  applicable MRL per residue and product is kept (the one applying from the latest
  date). `0.01*` = set at the limit of quantification (no authorised use).
* **EU contaminants:** EU number format (`5,0`, `1 250`) is parsed exactly; a value
  printed with a dated replacement (`100 50 as from 1 July 2024`) takes the later
  value once the date has passed and records both.
* **Codex pesticides:** the feed is template-generated JSON with trailing commas,
  raw line breaks and unescaped quotes inside values; it is repaired line by line,
  only when a plain parse fails. Draft-step MRLs are ignored (only `CXL` is law).
* **Codex CXS 193:** the standard's own index (Table A1) gives each contaminant's
  pages; only tables with a *Commodity* and a *Maximum level* column are read, so
  the sampling-plan annexes are never mistaken for limits.
* **US eCFR:** footnote markers (`<sup>1</sup>`) are dropped; `(N)` (negligible
  residue) is noted; unambiguous typographic variants in the official text (`.5`,
  `6. 0`, `0.01 ppm`, `1,000`) are normalised.
* **Provenance:** every load writes a `standards_snapshots` row with the document
  URL, version and sha256 of the exact file parsed. A load replaces one
  (jurisdiction, type) slice inside a transaction and refuses to replace a populated
  slice with an empty parse.

## Comparing them

Comparison keys are code, not run-time guesses:

* **Hazards** (`standards_common.hazard_key`): the printed name before its residue
  definition, lower-cased, with a reviewed alias table: spelling variants
  (`Chlorpyriphos` → chlorpyrifos), FSSAI misspellings checked against ISO names
  (`Penoxuslum` → penoxsulam), and *residue families* where the rule-books' residue
  definitions group substances (`Lambda-cyhalothrin` → cyhalothrin, as Codex's
  "Cyhalothrin (includes lambda-cyhalothrin)").
  Residue families are **never** used for anything that belongs to one substance:
  EU approval status and IARC group use `substance_key` (spelling fixes only). So
  lambda-cyhalothrin shows *Approved* in the EU while cyhalothrin's family limit
  is compared.
* **Foods** (`standards_foods.py`): every mapping was read off the printed names
  (FSSAI names, EU Annex I product codes, Codex commodity codes, 40 CFR commodity
  names, EU 2023/915 entry text, CXS 193 commodity names). Three tiers, kept apart:
  `specific` (names this food), `group` (a group that legally covers it, e.g. Codex
  *Cereal grains*), `residual` (catch-alls such as FSSAI *Foods not specified*).
  The comparison uses the most specific tier available and records which.

`models/standards_compare.py` writes `standards_comparison`: one row per (hazard,
food) India regulates, with each rule-book's value and **basis**:

| basis | meaning |
|---|---|
| `specific` / `group` / `residual` | the row the value came from (see above) |
| `eu_default` | the substance has no EU residue definition, so Reg. 396/2005 Art. 18(1)(b)'s general default of 0.01 mg/kg applies |
| `none` | the rule-book sets nothing: no Codex standard; **no US tolerance, i.e. no residue is legal in the US**; no EU maximum level for that contaminant/food |
| `not_loaded` | not compared (e.g. an EU product outside the India-relevant set; US contaminants) |

Guards: a ratio is computed only between two numeric mass fractions (mg/kg).
Dithiocarbamates are expressed on different chemical bases across rule-books (as
CS2 in India/EU/Codex, as the parent compound in some US tolerances); those pairs
are flagged `basis_mismatch` and get no ratio. When India prints two different
limits for the same pair, the pair is flagged `india_internal_conflict` and the
**lower** (stricter) value is used, so an "India is more permissive" flag is never
inflated by it.

## Why limits differ, and the reason recorded for each gap

* **Pesticide limits follow authorised use.** JMPR (and national regulators the same
  way) estimate maximum residue levels from residue data on how a pesticide is used,
  and set acceptable intakes from the toxicology
  ([FAO/WHO JMPR](https://www.who.int/groups/joint-fao-who-meeting-on-pesticide-residues-(jmpr))).
  A country that permits a use on a crop sets a limit that allows for it.
* **Where the EU permits no use, its limit is the detection floor:** a limit at the
  limit of quantification (LOQ) for substances not approved, or not approved on that
  food, and 0.01 mg/kg wherever no specific limit exists
  ([Reg. (EC) 396/2005](http://data.europa.eu/eli/reg/2005/396/oj), Art. 18(1)(b)).
  Such a limit means "should not be found", not "safe up to here".
* **US:** no tolerance means no legal residue; a tolerance must give "a reasonable
  certainty of no harm", with an additional tenfold safety factor for children unless
  data support another
  ([FQPA summary, EPA](https://www.epa.gov/laws-regulations/summary-food-quality-protection-act)).
* **Codex** is the international reference: WTO members base their measures on it and
  may go further with scientific justification
  ([SPS Agreement](https://www.wto.org/english/tratop_e/sps_e/spsagr_e.htm), Art. 3).
* **Contaminants** are not used on purpose: levels "shall be as low as reasonably
  achievable through best practices such as good agricultural practice (GAP) and good
  manufacturing practice (GMP) following an appropriate risk assessment" (CXS 193), so
  maximum levels also reflect what a food supply can meet.

`models/standards_compare.eu_gap_reason` reads, for every pesticide pair where
India's limit is above the EU's, why the EU's is lower — from the EU value itself
(its basis and the printed `*` LOQ marker) and the substance's EU approval status:

| flag | the EU value is… |
|---|---|
| `eu_gap_not_approved` | at the LOQ, and the substance is not approved in the EU |
| `eu_gap_no_use_on_food` | at the LOQ for this food, though the substance is approved (no authorised EU use on it) |
| `eu_gap_never_assessed` | the 0.01 mg/kg default: no EU residue definition |
| `eu_gap_at_loq` | at the LOQ, approval status unknown or mixed |
| `eu_gap_above_loq` | above the LOQ: the EU sets a residue level (an authorised EU use, an import tolerance or a temporary limit — the latter two for the 29 of 76 not approved in the EU), and India's is higher |

On the first full run: of 759 pesticide pairs where India is higher, **683** are
pesticides the EU does not permit on that food (497 not approved, 94 approved but
not for that food, 92 never assessed; median India ÷ EU 10×, 40×, 20×). In only
**76** does the EU set a residue level above detection; there India's limit is a
median **3×** the EU's. The other
72 India-higher pairs are contaminants. `GET /v1/standards/summary` serves the
current breakdown (`india_higher_than_eu_why`); `/v1/standards/compare?flag=…`
filters by it.

## First full run (local verification, 2026-10-03)

All six parsers run against the live documents; loaded into a scratch Postgres built
by `scripts/bootstrap_db.py` (production loads run in CI, see below).

* Rows: India 1,573 (1,097 pesticide MRLs, 446 contaminant MLs, 16 antibiotic
  limits, 14 prohibited drugs); EU 35,351 pesticide MRLs (53 foods) + 403 contaminant
  MLs; Codex 6,490 pesticide MRLs + 134 contaminant MLs; US 12,668 tolerances.
* 1,711 (hazard, food) pairs compared: 1,297 pesticide, 414 contaminant.
* Pesticides: of 1,135 pairs with both an India and an EU value, India's limit is
  **higher in 759**, equal in 176, lower in 154 (183 of the EU values are the 0.01
  mg/kg default). India vs Codex: higher in 104, lower in 104 of 419. India vs US:
  higher in 88 of 387; for 867 pairs the US has no tolerance at all.
* Of the pesticides India sets limits for, **114 are not approved in the EU** and 71
  are approved; 28 have no EU record.
* Contaminants, examples (India vs EU vs Codex, from the stored rows):
  lead in dried spices 10 mg/kg vs 0.6–1.5 vs 0.6–2.0; total aflatoxins in spices
  30 µg/kg vs 10 (chilli, pepper, turmeric) vs 20 (chilli); aflatoxin M1 in milk
  0.5 µg/kg vs 0.05 vs 0.5. Where FSSAI has no food-specific limit its legal
  catch-all applies (e.g. cadmium "Foods not specified" 1.5 mg/kg) and the row says so.

These counts are from one run and will move as the rule-books are amended; the API
(`GET /v1/standards/summary`) always serves the current numbers.

## API

`GET /v1/standards/summary`, `/v1/standards/compare` (filters: `food`, `hazard`,
`flag`, `standard_type`; `with_rows=true` returns the printed rows behind each
value), `/v1/standards/foods`, `/v1/standards/food/{food_key}`,
`/v1/standards/hazard/{hazard_key}` (every limit, the safety thresholds and the
health effects for one hazard). All public, no auth.

## Refresh

`.github/workflows/standards.yml` runs weekly (and on demand): it applies the schema,
re-reads all six rule-books, refreshes the hazard knowledge base, and recomputes the
comparison. The FSSAI compendium URL is versioned by FSSAI and must be updated in
`standards_fssai.COMPENDIUM_URL` when a new version is published.

## Known gaps

* FSSAI's veterinary-drug MRL table (species x tissue) is not parsed yet.
* US contaminant action levels (FDA guidance) are not loaded; US contaminant cells
  read `not_loaded`.
* EU pesticide MRLs are loaded for ~50 foods, not all 381 EU products.
* US crop-group tolerances are mapped for the main groups only.
