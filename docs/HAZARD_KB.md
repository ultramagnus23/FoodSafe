# Hazard → health knowledge base

The ground truth behind FoodSafe's **disease classification**: what each food
hazard does to people, how quickly, who is most at risk, and the authoritative
source for each statement.

## Why a knowledge base and not a trained disease model

No public dataset links contamination recorded in a place in India to disease
outcomes in that place. A model "trained to predict disease from contamination"
would have no real training data, so FoodSafe does not build one. Instead, each
contamination record is classified into the outcomes its hazard is **known** to
cause, using cited sources. This says what *can* happen, not how *likely* it is at
a given level; that needs exposure data (see the safe-intake calculator).

## Contents

`pipeline/sources/hazard_kb.py` loads:

* **IARC classifications** for all 1,128 agents (Volumes 1–142, list updated
  2026-07-23), read from the data embedded in IARC's own list-of-classifications
  page. Joined to pesticides by CAS number (from the EU active-substance records)
  and to curated hazards by agent name. Example corrections this enforced: inorganic
  lead is Group 2A (not 1); methylmercury 2B; Sudan I is Group 3 (its concern rests
  on EFSA's genotoxicity opinion, which is what the KB cites).
* **46 curated hazards**: mycotoxins (aflatoxins, ochratoxin A, patulin,
  fumonisins, DON), metals (lead, cadmium, inorganic arsenic, mercury,
  methylmercury, tin), process/environmental contaminants (benzo[a]pyrene, PCBs,
  dioxins, ethylene oxide), natural toxins (histamine, marine biotoxins, cyanogenic
  glycosides), India-specific adulterants and toxins (argemone oil → epidemic
  dropsy; khesari dal ODAP → neurolathyrism), banned veterinary drugs
  (chloramphenicol, nitrofurans, malachite green), illegal dyes (Sudan), undeclared
  allergens, and 15 pathogens (Salmonella, Typhi, Listeria, STEC, Campylobacter,
  Vibrio, S. aureus toxin, B. cereus, C. perfringens, C. botulinum, Shigella,
  norovirus, hepatitis A and E).
* **Pesticide chemical classes** (organophosphate, carbamate, organochlorine,
  pyrethroid, neonicotinoid), each with its mode-of-action syndrome (e.g.
  acetylcholinesterase inhibition → cholinergic poisoning). A regulated pesticide
  with no class gets a generic, explicitly labelled pesticide outcome. An EU record
  alone (a pheromone, a microorganism) never does.
* **Toxicological reference values**: EU ADI/ARfD/AOEL (EU Pesticides Database),
  JMPR ADIs (Codex database), and JECFA's toxicological guidance text for each
  CXS 193 contaminant, verbatim (e.g. why JECFA withdrew the lead PTWI).

Each outcome row: `outcome`, `icd10` where one fits, `organ_system`, `exposure`
(acute / chronic / both), `onset`, `vulnerable_groups`, `evidence`, `source_title`,
`source_url`.

## Sources

WHO fact sheets (food safety, mycotoxins, lead, arsenic, mercury, Salmonella,
listeriosis, E. coli, Campylobacter, cholera, typhoid, hepatitis A/E, botulism,
dioxins, pesticide residues); IARC; EFSA opinions (Sudan dyes 2005,
chloramphenicol 2014, nitrofurans 2015, malachite green 2016); US EPA
*Recognition and Management of Pesticide Poisonings*; CDC (staphylococcal,
C. perfringens, norovirus, Vibrio); FDA Bad Bug Book; FAO/WHO histamine (2013),
marine biotoxins (2004), allergens (2022); the WHO/FAO melamine expert meeting;
Indian J Med Res (neurolathyrism); Neurology India (1998 Delhi dropsy outbreak).

Every source URL was opened on 2026-10-03. WHO, IARC, FAO, PMC and EPA pages returned
200 to a script. CDC, EFSA (Wiley) and LWW pages block scripts (403), but are real:
two CDC pages were confirmed by reading them. Two first-draft URLs were wrong (404)
and were replaced before anything was loaded. The WHO statements quoted in the
`evidence` column were re-read on that date.

## API

`GET /v1/hazards` (filter `hazard_class`), `GET /v1/hazards/{hazard_key}`, and the
`hazard` block of `GET /v1/standards/hazard/{hazard_key}`.
