"""
Hazard -> health knowledge base: what each food hazard does to people, and how
sure science is about it. This is the ground truth behind FoodSafe's disease
classification: a contamination record (an EU border rejection for aflatoxin, a
pesticide residue above the limit, a Salmonella finding) is classified into the
health outcomes its hazard is known to cause.

Two inputs, both cited:
  1. IARC's list of classifications (all agents, Volumes 1-N), read from the
     data embedded in IARC's own list-of-classifications page
     (https://monographs.iarc.who.int/list-of-classifications). It gives the
     carcinogen group (1 / 2A / 2B / 3) and is joined to hazards by CAS number
     (EU active substances carry CAS) or by an explicit agent name below.
  2. A curated table (HAZARDS, PESTICIDE_CLASSES) written from authoritative
     sources only — WHO fact sheets, IARC, EFSA opinions, CDC, FAO/WHO expert
     meetings, peer-reviewed reviews for India-specific adulterants. Every
     outcome row carries the source it was taken from; the WHO statements used
     were re-read on 2026-10-03.

What this is NOT: a dose-response model. It says which outcomes a hazard can
cause and for whom, not how likely any outcome is at a given contamination
level (that needs exposure data; see models/safe_intake.py for the part that
can be computed — how much of a food reaches a health-based guidance value).

-> hazards (upsert: class, aliases, IARC group/agent, summary, sources)
-> hazard_health_effects (replaced on every run: the table is code-owned)

Run: python -m pipeline.sources.hazard_kb [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import urllib.request
from typing import Optional

logger = logging.getLogger("foodsafe.hazard_kb")

USER_AGENT = "FoodSafe-India/1.0 (public-interest research; +https://github.com/ultramagnus23/FoodSafe)"
IARC_BUNDLE = "https://webapi.iarc.who.int/loc/loc.app.js"
IARC_PAGE = "https://monographs.iarc.who.int/list-of-classifications"

# ---------------------------------------------------------------- sources
WHO = "https://www.who.int/news-room/fact-sheets/detail/"
SRC = {
    "who_food_safety": ("WHO fact sheet: Food safety", WHO + "food-safety"),
    "who_mycotoxins": ("WHO fact sheet: Mycotoxins", WHO + "mycotoxins"),
    "who_lead": ("WHO fact sheet: Lead poisoning and health", WHO + "lead-poisoning-and-health"),
    "who_arsenic": ("WHO fact sheet: Arsenic", WHO + "arsenic"),
    "who_mercury": ("WHO fact sheet: Mercury and health", WHO + "mercury-and-health"),
    "who_salmonella": ("WHO fact sheet: Salmonella (non-typhoidal)", WHO + "salmonella-(non-typhoidal)"),
    "who_listeria": ("WHO fact sheet: Listeriosis", WHO + "listeriosis"),
    "who_ecoli": ("WHO fact sheet: E. coli", WHO + "e-coli"),
    "who_campylobacter": ("WHO fact sheet: Campylobacter", WHO + "campylobacter"),
    "who_cholera": ("WHO fact sheet: Cholera", WHO + "cholera"),
    "who_typhoid": ("WHO fact sheet: Typhoid", WHO + "typhoid"),
    "who_hepa": ("WHO fact sheet: Hepatitis A", WHO + "hepatitis-a"),
    "who_hepe": ("WHO fact sheet: Hepatitis E", WHO + "hepatitis-e"),
    "who_botulism": ("WHO fact sheet: Botulism", WHO + "botulism"),
    "codex_cxs193": ("Codex CXS 193-1995 General Standard for Contaminants and Toxins in Food and Feed",
                     "https://openknowledge.fao.org/server/api/core/bitstreams/4d0e7245-8166-49ca-b822-ca80a1ff5cfe/content"),
    "who_dioxins": ("WHO fact sheet: Dioxins", WHO + "dioxins-and-their-effects-on-human-health"),
    "who_pesticides": ("WHO fact sheet: Pesticide residues in food", WHO + "pesticide-residues-in-food"),
    "iarc": ("IARC Monographs: list of classifications", IARC_PAGE),
    "cdc_staph": ("CDC: Staphylococcal food poisoning", "https://www.cdc.gov/staph-food-poisoning/about/index.html"),
    "cdc_perfringens": ("CDC: Clostridium perfringens food poisoning",
                        "https://www.cdc.gov/clostridium-perfringens/about/index.html"),
    "cdc_norovirus": ("CDC: About norovirus", "https://www.cdc.gov/norovirus/about/index.html"),
    "cdc_vibrio": ("CDC: About Vibrio infection", "https://www.cdc.gov/vibrio/about/index.html"),
    "fda_badbug": ("US FDA Bad Bug Book, 2nd edition (Bacillus cereus chapter)",
                   "https://www.fda.gov/files/food/published/Bad-Bug-Book-2nd-Edition-(PDF).pdf"),
    "fao_histamine": ("FAO/WHO (2013) Public health risks of histamine and other biogenic amines from fish",
                      "https://www.fao.org/3/i3390e/i3390e.pdf"),
    "fao_biotoxins": ("FAO (2004) Marine biotoxins, FAO Food and Nutrition Paper 80",
                      "https://www.fao.org/3/y5486e/y5486e00.htm"),
    "who_melamine": ("WHO/FAO expert meeting on melamine and cyanuric acid (Ottawa, 2008), via Health Canada",
                     "https://www.canada.ca/en/health-canada/services/food-nutrition/food-safety/chemical-contaminants/"
                     "melamine/2008-world-health-organization-expert-meeting-review-toxicological-aspects-melamine-"
                     "cyanuric-acid.html"),
    "efsa_sudan": ("EFSA (2005) Opinion on Sudan dyes and other illegal dyes in food",
                   "https://efsa.onlinelibrary.wiley.com/doi/10.2903/j.efsa.2005.263"),
    "efsa_chloramphenicol": ("EFSA (2014) Scientific opinion on chloramphenicol in food",
                             "https://efsa.onlinelibrary.wiley.com/doi/10.2903/j.efsa.2014.3907"),
    "efsa_nitrofurans": ("EFSA (2015) Scientific opinion on nitrofurans and their metabolites in food",
                         "https://efsa.onlinelibrary.wiley.com/doi/10.2903/j.efsa.2015.4140"),
    "efsa_malachite": ("EFSA (2016) Malachite green in food", "https://efsa.onlinelibrary.wiley.com/doi/10.2903/j.efsa.2016.4530"),
    "epa_rmpp": ("US EPA: Recognition and Management of Pesticide Poisonings (6th ed.)",
                 "https://www.epa.gov/pesticide-worker-safety/recognition-and-management-pesticide-poisonings"),
    "epa_rmpp_op": ("US EPA RMPP 6th ed., ch. 5: Organophosphate insecticides",
                    "https://www.epa.gov/sites/default/files/documents/rmpp_6thed_ch5_organophosphates.pdf"),
    "epa_rmpp_carb": ("US EPA RMPP 6th ed., ch. 6: N-methyl carbamate insecticides",
                      "https://www.epa.gov/sites/default/files/documents/rmpp_6thed_ch6_carbamates.pdf"),
    "efsa_acrylamide": ("EFSA (2015) Scientific opinion on acrylamide in food",
                        "https://doi.org/10.2903/j.efsa.2015.4104"),
    "efsa_mcpd": ("EFSA (2016) Risks for human health related to 3- and 2-MCPD and their fatty acid esters, and "
                  "glycidyl fatty acid esters in food", "https://doi.org/10.2903/j.efsa.2016.4426"),
    "efsa_pa": ("EFSA (2017) Risks for human health related to pyrrolizidine alkaloids in honey, tea, herbal "
                "infusions and food supplements", "https://doi.org/10.2903/j.efsa.2017.4908"),
    "efsa_sulphites": ("EFSA (2016) Re-evaluation of sulfur dioxide and sulfites (E 220-228) as food additives",
                       "https://doi.org/10.2903/j.efsa.2016.4438"),
    "fao_allergens": ("FAO/WHO (2022) Risk assessment of food allergens, Part 1",
                      "https://www.fao.org/documents/card/en/c/cb9070en"),
    "fssai_dart": ("FSSAI: Detect Adulteration with Rapid Test (DART) booklet",
                   "https://fssai.gov.in/book-details.php?bkid=201"),
    "ijmr_lathyrism": ("Indian J Med Res (2014): Grass pea consumption & neurolathyrism in Maharashtra",
                       "https://pmc.ncbi.nlm.nih.gov/articles/PMC4181167/"),
    "ni_dropsy": ("Neurology India (2000): Neurologic complications of dropsy (1998 Delhi outbreak)",
                  "https://journals.lww.com/neur/fulltext/2000/48020/neurologic_complications_of_dropsy___from.9.aspx"),
}


def E(outcome_key, outcome, organ_system, exposure, evidence, src, icd10=None, onset=None, vulnerable=()):
    return {"outcome_key": outcome_key, "outcome": outcome, "organ_system": organ_system, "exposure": exposure,
            "evidence": evidence, "source": src, "icd10": icd10, "onset": onset,
            "vulnerable_groups": list(vulnerable)}


GI = "gastrointestinal"
KIDS, PREG, OLD, IMMUNO = "young children", "pregnant women", "older adults", "immunocompromised people"

# hazard_key -> definition. hazard_key values match pipeline/sources/standards_common.hazard_key().
HAZARDS: dict[str, dict] = {
    # ---------------- mycotoxins
    "aflatoxins_total": dict(name="Aflatoxins", hazard_class="mycotoxin", iarc_agent="Aflatoxins",
        aliases=["aflatoxin", "aflatoxins", "aflatoxin b1", "aflatoxin b2", "aflatoxin g1", "aflatoxin g2"],
        summary="Produced by Aspergillus moulds on groundnuts, maize, spices and nuts stored warm and humid.",
        effects=[
            E("liver_cancer", "Liver cancer (hepatocellular carcinoma)", "hepatic", "chronic",
              "IARC Group 1; WHO: risk is higher in people already infected with hepatitis B", "who_food_safety",
              "C22.0", "years", ["people with chronic hepatitis B"]),
            E("aflatoxicosis", "Acute aflatoxin poisoning (aflatoxicosis), liver damage", "hepatic", "acute",
              "WHO: large doses can cause life-threatening acute poisoning through liver damage", "who_mycotoxins",
              "T64", "days")]),
    "aflatoxin_b1": dict(name="Aflatoxin B1", hazard_class="mycotoxin", iarc_agent="Aflatoxins", parent="aflatoxins_total"),
    "aflatoxin_m1": dict(name="Aflatoxin M1", hazard_class="mycotoxin", iarc_agent="Aflatoxin M1",
        aliases=["afm1"], summary="The form of aflatoxin B1 that passes into milk when dairy animals eat contaminated feed.",
        iarc_agent_override="Aflatoxins",
        effects=[E("liver_cancer", "Liver cancer (hepatocellular carcinoma)", "hepatic", "chronic",
                   "Metabolite of aflatoxin B1; see IARC classification", "iarc", "C22.0", "years", [KIDS])]),
    "ochratoxin_a": dict(name="Ochratoxin A", hazard_class="mycotoxin", iarc_agent="Ochratoxin A", aliases=["ota"],
        summary="Mould toxin found in cereals, coffee, dried fruit, spices and wine.",
        effects=[E("kidney_damage", "Kidney damage", "renal", "chronic",
                   "WHO: kidney damage is the most sensitive effect; may affect fetal development and immunity",
                   "who_mycotoxins", "N28.9", "years", [PREG])]),
    "patulin": dict(name="Patulin", hazard_class="mycotoxin", iarc_agent="Patulin",
        summary="Mould toxin in rotting apples and apple juice.",
        effects=[E("acute_gastroenteritis", "Nausea, vomiting, gastrointestinal upset", GI, "acute",
                   "WHO: human symptoms include nausea, gastrointestinal disturbances and vomiting", "who_mycotoxins",
                   None, "hours")]),
    "fumonisins": dict(name="Fumonisins", hazard_class="mycotoxin", iarc_agent="Fumonisin B1",
        aliases=["fumonisin", "fumonisin b1", "fumonisin b2"], summary="Fusarium mould toxins in maize.",
        effects=[E("oesophageal_cancer", "Oesophageal cancer", "digestive tract", "chronic",
                   "WHO: related to oesophageal cancer in humans", "who_mycotoxins", "C15", "years")]),
    "deoxynivalenol": dict(name="Deoxynivalenol (vomitoxin)", hazard_class="mycotoxin", aliases=["don", "vomitoxin"],
        summary="Fusarium toxin in wheat, maize and barley.",
        effects=[E("acute_gastroenteritis", "Irritation of the gut, diarrhoea", GI, "acute",
                   "WHO: can be acutely toxic, causing rapid irritation of the intestinal mucosa and diarrhoea",
                   "who_mycotoxins", None, "hours")]),
    # ---------------- metals
    "lead": dict(name="Lead", hazard_class="heavy_metal", iarc_agent="Lead compounds, inorganic", aliases=["pb"],
        summary="No known safe level of exposure. In food, from contaminated soil/water, and from adulteration "
                "(e.g. lead chromate added to colour spices).",
        effects=[
            E("neurodevelopmental_impairment", "Lower IQ, attention and learning problems in children", "nervous",
              "chronic", "WHO: permanently affects children's brain development; no safe level", "who_lead", "F79",
              "years", [KIDS, PREG]),
            E("anaemia", "Anaemia", "blood", "chronic", "WHO: lead causes anaemia", "who_lead", "D64.9", "months", [KIDS]),
            E("cardiovascular_disease", "High blood pressure and cardiovascular disease", "cardiovascular", "chronic",
              "WHO: increased risk of high blood pressure, cardiovascular problems", "who_lead", "I10", "years"),
            E("kidney_damage", "Kidney damage", "renal", "chronic", "WHO: kidney damage in adults", "who_lead",
              "N28.9", "years"),
            E("adverse_pregnancy_outcome", "Reduced fetal growth and preterm birth", "reproductive", "chronic",
              "WHO: exposure in pregnancy can cause reduced fetal growth and preterm birth", "who_lead", "P05",
              "months", [PREG])]),
    "cadmium": dict(name="Cadmium", hazard_class="heavy_metal", iarc_agent="Cadmium and cadmium compounds",
        aliases=["cd"], summary="Accumulates in rice, leafy vegetables, shellfish; stays in the kidneys for decades.",
        effects=[
            E("kidney_damage", "Chronic kidney disease", "renal", "chronic",
              "WHO: cadmium is linked to chronic kidney diseases", "who_food_safety", "N18", "years"),
            E("osteoporosis", "Bone loss (osteoporosis)", "skeletal", "chronic",
              "WHO: cadmium is linked to osteoporosis", "who_food_safety", "M81", "years", [OLD])]),
    "arsenic_inorganic": dict(name="Inorganic arsenic", hazard_class="heavy_metal",
        iarc_agent="Arsenic and inorganic arsenic compounds", aliases=["arsenic", "as", "inorganic arsenic"],
        summary="From groundwater used for drinking, cooking and irrigation (rice). India is among the most "
                "affected countries (WHO).",
        effects=[
            E("skin_lesions", "Skin pigmentation changes and hard patches (keratosis)", "skin", "chronic",
              "WHO: typically after about five years of exposure", "who_arsenic", "L85.1", "years"),
            E("skin_cancer", "Skin cancer", "skin", "chronic", "WHO / IARC Group 1", "who_arsenic", "C44", "years"),
            E("bladder_cancer", "Bladder cancer", "urinary", "chronic", "WHO / IARC Group 1", "who_arsenic", "C67", "years"),
            E("lung_cancer", "Lung cancer", "respiratory", "chronic", "WHO / IARC Group 1", "who_arsenic", "C34", "years"),
            E("cardiovascular_disease", "Cardiovascular disease", "cardiovascular", "chronic",
              "WHO: associated with cardiovascular disease and heart attacks", "who_arsenic", "I25", "years"),
            E("diabetes", "Type 2 diabetes", "endocrine", "chronic", "WHO: associated with diabetes", "who_arsenic",
              "E11", "years"),
            E("neurodevelopmental_impairment", "Impaired cognitive development in children", "nervous", "chronic",
              "WHO: early-life exposure impairs cognitive development, intelligence and memory", "who_arsenic",
              "F79", "years", [KIDS, PREG])]),
    "mercury": dict(name="Mercury", hazard_class="heavy_metal", iarc_agent="Mercury and inorganic mercury compounds",
        aliases=["hg"], summary="Mostly a concern as methylmercury in large predatory fish.",
        effects=[E("kidney_damage", "Kidney damage (inorganic mercury)", "renal", "chronic",
                   "WHO mercury fact sheet", "who_mercury", "N28.9", "years")]),
    "methylmercury": dict(name="Methylmercury", hazard_class="heavy_metal", iarc_agent="Methylmercury compounds",
        aliases=["methyl mercury"], summary="Builds up in large predatory fish (shark, swordfish, tuna).",
        effects=[E("neurodevelopmental_impairment", "Impaired brain development before birth and in infancy",
                   "nervous", "chronic", "WHO: increases the risk of intellectual disability in children",
                   "who_food_safety", "F79", "years", [PREG, KIDS])]),
    "tin": dict(name="Tin (inorganic)", hazard_class="heavy_metal", aliases=["sn"],
        summary="Leaches from unlacquered cans into acidic canned food.",
        effects=[E("acute_gastroenteritis", "Stomach upset, vomiting, diarrhoea at high levels", GI, "acute",
                   "Codex CXS 193 sets tin limits for canned foods; JECFA notes gastric irritation at high "
                   "concentrations", "codex_cxs193", None, "hours")]),
    # ---------------- process / environmental contaminants
    "benzo_a_pyrene": dict(name="Benzo[a]pyrene (PAH)", hazard_class="process_contaminant",
        iarc_agent="Benzo[a]pyrene", aliases=["pah", "pahs", "polycyclic aromatic hydrocarbons"],
        summary="Forms when food is smoked, grilled or dried over open fire.",
        effects=[E("cancer", "Cancer (genotoxic carcinogen)", "multiple", "chronic", "IARC Group 1", "iarc", "C80",
                   "years")]),
    "pcbs": dict(name="Polychlorinated biphenyls (PCBs)", hazard_class="environmental_pollutant",
        iarc_agent="Polychlorinated biphenyls", aliases=["pcb", "dioxin-like pcbs"],
        summary="Persistent industrial pollutants that build up in fish and animal fat.",
        effects=[E("cancer", "Cancer", "multiple", "chronic", "IARC Group 1", "iarc", "C80", "years"),
                 E("reproductive_developmental_toxicity", "Reproductive, developmental, immune and hormonal effects",
                   "reproductive", "chronic", "WHO: dioxins and PCBs cause reproductive and developmental problems, "
                   "damage the immune system and interfere with hormones", "who_food_safety", None, "years",
                   [PREG, KIDS])]),
    "dioxins": dict(name="Dioxins", hazard_class="environmental_pollutant",
        iarc_agent="2,3,7,8-Tetrachlorodibenzo-para-dioxin", aliases=["dioxin", "pcdd/f"],
        summary="Persistent combustion by-products concentrated in animal fat.",
        effects=[E("cancer", "Cancer", "multiple", "chronic", "IARC Group 1 (TCDD)", "who_dioxins", "C80", "years"),
                 E("reproductive_developmental_toxicity", "Reproductive and developmental problems", "reproductive",
                   "chronic", "WHO dioxins fact sheet", "who_dioxins", None, "years", [PREG, KIDS])]),
    "ethylene_oxide": dict(name="Ethylene oxide", hazard_class="pesticide", iarc_agent="Ethylene oxide",
        aliases=["ethylene oxide", "eto", "2-chloroethanol", "ethylene oxide (sum)"],
        summary="A sterilising gas used on sesame seeds, spices and gums; not authorised for food use in the EU.",
        effects=[E("cancer", "Cancer (genotoxic carcinogen)", "multiple", "chronic",
                   "IARC Group 1 (carcinogenic to humans)", "iarc", "C80", "years")]),
    "acrylamide": dict(name="Acrylamide", hazard_class="process_contaminant", iarc_agent="Acrylamide",
        summary="Forms when starchy food is fried, roasted or baked at high temperature (chips, coffee, biscuits).",
        effects=[E("cancer", "Cancer (genotoxic carcinogen)", "multiple", "chronic",
                   "EFSA 2015: acrylamide in food potentially increases cancer risk in all age groups; IARC Group 2A",
                   "efsa_acrylamide", "C80", "years")]),
    "glycidyl_esters": dict(name="Glycidyl fatty acid esters (glycidol)", hazard_class="process_contaminant",
        iarc_agent="Glycidol", aliases=["glycidyl esters", "glycidyl fatty acid esters", "glycidol"],
        summary="Form in refined vegetable oils, especially palm oil, during high-temperature refining.",
        effects=[E("cancer", "Cancer (genotoxic carcinogen, released as glycidol)", "multiple", "chronic",
                   "EFSA 2016 MCPD/glycidyl ester opinion; IARC Group 2A (glycidol)", "efsa_mcpd", "C80", "years",
                   [KIDS])]),
    "3mcpd": dict(name="3-MCPD and its fatty acid esters", hazard_class="process_contaminant",
        iarc_agent="3-Monochloro-1,2-propanediol",
        aliases=["3-mcpd", "3-monochloropropanediol", "3-monochlor-1,2-propanediol", "3-monochloropropane-1,2-diol"],
        summary="Process contaminant in refined oils, soy sauce and hydrolysed vegetable protein.",
        effects=[E("kidney_damage", "Kidney damage (critical effect; also male fertility)", "renal", "chronic",
                   "EFSA 2016: kidney effects are the critical endpoint for 3-MCPD; IARC Group 2B", "efsa_mcpd",
                   "N28.9", "years", [KIDS])]),
    "pyrrolizidine_alkaloids": dict(name="Pyrrolizidine alkaloids", hazard_class="natural_toxin",
        aliases=["pyrrolizidine alkaloids", "pyrrolizidine alkaloid", "pas"],
        summary="Plant toxins that contaminate tea, herbal infusions, honey and spices through weeds harvested "
                "with the crop.",
        effects=[E("liver_damage", "Liver damage (hepatic veno-occlusive disease)", "hepatic", "both",
                   "EFSA 2017 opinion on pyrrolizidine alkaloids", "efsa_pa", "K76.5", "weeks to years"),
                 E("cancer", "Cancer (genotoxic carcinogens)", "multiple", "chronic",
                   "EFSA 2017: 1,2-unsaturated pyrrolizidine alkaloids are genotoxic carcinogens", "efsa_pa",
                   "C80", "years")]),
    "sulphites": dict(name="Sulphites (sulphur dioxide, E220-E228)", hazard_class="additive",
        aliases=["sulphite", "sulfite", "sulphites", "sulfites", "sulphur dioxide", "sulfur dioxide", "e220",
                 "e221", "e222", "e223", "e224"],
        summary="Preservatives in dried fruit, wine and shrimp; a declared allergen in the EU above 10 mg/kg.",
        effects=[E("sulphite_intolerance", "Intolerance reactions, including asthma attacks in sensitive people",
                   "respiratory", "acute", "EFSA 2016 re-evaluation of sulphites as food additives",
                   "efsa_sulphites", "T78.1", "minutes", ["people with asthma"])]),
    "melamine": dict(name="Melamine", hazard_class="other", aliases=["melamine adulteration"],
        summary="Added illegally to milk to fake protein content (China 2008).",
        effects=[E("kidney_stones", "Kidney stones and kidney failure", "renal", "acute",
                   "WHO 2009 expert meeting", "who_melamine", "N20", "weeks", [KIDS])]),
    # ---------------- natural toxins
    "histamine": dict(name="Histamine", hazard_class="natural_toxin", aliases=["scombrotoxin"],
        summary="Forms in tuna, mackerel, sardines and other fish kept too warm after catch.",
        effects=[E("scombroid_poisoning", "Scombroid (histamine) fish poisoning: flushing, headache, rash, "
                   "palpitations", "immune/skin", "acute", "FAO/WHO 2013 expert meeting", "fao_histamine", "T61.1",
                   "minutes to hours")]),
    "paralyticshellfishpoison": dict(name="Paralytic shellfish poison (saxitoxins)", hazard_class="marine_biotoxin",
        aliases=["psp", "saxitoxin"], summary="Algal toxin concentrated by mussels, clams and oysters.",
        effects=[E("shellfish_poisoning", "Paralytic shellfish poisoning: numbness, paralysis, respiratory failure",
                   "nervous", "acute", "FAO marine biotoxins paper", "fao_biotoxins", "T61.2", "minutes to hours")]),
    "amnesicshellfishpoison": dict(name="Amnesic shellfish poison (domoic acid)", hazard_class="marine_biotoxin",
        aliases=["asp", "domoic acid"], summary="Algal toxin in shellfish.",
        effects=[E("shellfish_poisoning", "Amnesic shellfish poisoning: vomiting, memory loss, seizures", "nervous",
                   "acute", "FAO marine biotoxins paper", "fao_biotoxins", "T61.2", "hours")]),
    "diarrheticshellfishpoison": dict(name="Diarrhetic shellfish poison (okadaic acid)", hazard_class="marine_biotoxin",
        aliases=["dsp", "okadaic acid"], summary="Algal toxin in shellfish.",
        effects=[E("acute_gastroenteritis", "Diarrhetic shellfish poisoning: diarrhoea, vomiting", GI, "acute",
                   "FAO marine biotoxins paper", "fao_biotoxins", "T61.2", "hours")]),
    "hydrocyanicacid": dict(name="Hydrocyanic acid (cyanogenic glycosides)", hazard_class="natural_toxin",
        aliases=["cyanide", "cyanogenic glycosides"], summary="Released from cassava, bitter almonds, apricot kernels.",
        effects=[E("cyanide_poisoning", "Cyanide poisoning", "multiple", "acute",
                   "WHO lists cyanogenic glycosides among naturally occurring food toxins", "who_food_safety",
                   "T65.0", "minutes to hours")]),
    "argemone_oil": dict(name="Argemone oil (sanguinarine)", hazard_class="adulterant",
        aliases=["argemone", "sanguinarine"], summary="Mexican prickly poppy seed oil mixed into mustard oil; "
                "caused the 1998 Delhi epidemic (>3,000 affected).",
        effects=[E("epidemic_dropsy", "Epidemic dropsy: leg swelling, heart failure, glaucoma", "cardiovascular",
                   "acute", "Clinical series from the 1998 Delhi outbreak", "ni_dropsy", None, "days to weeks")]),
    "india_adulterants": dict(name="Common adulterants listed by FSSAI (DART)", hazard_class="adulterant",
        aliases=["detergent", "urea", "formalin", "metanil yellow", "brick powder", "chalk powder", "sawdust",
                 "synthetic milk", "washing soda", "malachite green dye"],
        summary="Substances FSSAI's 'Detect Adulteration with Rapid Test' (DART) booklet tells consumers to test "
                "for at home. No single health outcome is asserted: it depends on the substance and the dose.",
        source_keys=["fssai_dart"], effects=[]),
    "lathyrus_odap": dict(name="beta-ODAP (Lathyrus sativus / khesari dal)", hazard_class="natural_toxin",
        aliases=["khesari", "lathyrus", "odap", "boaa"],
        summary="Neurotoxin in grass pea, eaten as a staple in drought and famine.",
        effects=[E("neurolathyrism", "Neurolathyrism: irreversible spastic paralysis of the legs", "nervous", "chronic",
                   "Indian J Med Res review", "ijmr_lathyrism", None, "weeks to months")]),
    # ---------------- veterinary drugs
    "chloramphenicol": dict(name="Chloramphenicol", hazard_class="veterinary_drug", iarc_agent="Chloramphenicol",
        summary="Antibiotic banned in food animals; found in shrimp and honey.",
        effects=[E("aplastic_anaemia", "Aplastic anaemia (bone-marrow failure)", "blood", "chronic",
                   "EFSA 2014: no safe residue level can be set because of aplastic anaemia risk",
                   "efsa_chloramphenicol", "D61", "weeks to months")]),
    "nitrofurans": dict(name="Nitrofurans (AOZ, SEM, AMOZ, AHD)", hazard_class="veterinary_drug",
        aliases=["nitrofuran", "furazolidone", "nitrofurazone", "aoz", "sem", "amoz", "ahd"],
        summary="Banned antibiotics; recurring finding in farmed shrimp.",
        effects=[E("cancer", "Cancer (genotoxic carcinogenic metabolites)", "multiple", "chronic",
                   "EFSA 2015 opinion", "efsa_nitrofurans", "C80", "years")]),
    "malachitegreen": dict(name="Malachite green", hazard_class="veterinary_drug",
        aliases=["malachite green", "leucomalachite green"], summary="Banned dye used against fungus in fish farming.",
        effects=[E("cancer", "Cancer (genotoxic)", "multiple", "chronic", "EFSA 2016", "efsa_malachite", "C80", "years")]),
    # ---------------- illegal dyes
    "sudan_dyes": dict(name="Sudan dyes", hazard_class="adulterant",
        aliases=["sudan i", "sudan ii", "sudan iii", "sudan iv", "sudan 1", "sudan 4", "para red", "rhodamine b"],
        summary="Industrial dyes added to chilli powder, curry and palm oil to deepen the red colour.",
        effects=[E("cancer", "Cancer (genotoxic in animal studies)", "multiple", "chronic",
                   "EFSA 2005: Sudan I is genotoxic and carcinogenic in animals", "efsa_sudan", "C80", "years")]),
    # ---------------- allergens
    "undeclared_allergen": dict(name="Undeclared allergen", hazard_class="allergen",
        aliases=["gluten", "peanut", "sesame", "milk", "egg", "sulphite", "sulfite", "mustard", "soy", "nuts", "celery"],
        summary="An allergen present but missing from the label.",
        effects=[E("allergic_reaction", "Allergic reaction, up to anaphylaxis", "immune", "acute",
                   "FAO/WHO 2022 risk assessment of food allergens", "fao_allergens", "T78.1", "minutes",
                   ["people with food allergy"])]),
    # ---------------- microbiological
    "salmonella": dict(name="Salmonella (non-typhoidal)", hazard_class="pathogen_bacteria",
        aliases=["salmonella", "salmonella spp", "salmonella enteritidis", "salmonella typhimurium",
                 "salmonella infantis"],
        summary="Eggs, poultry, meat, milk, and vegetables contaminated with manure; also spices and sesame.",
        effects=[E("acute_gastroenteritis", "Salmonellosis: fever, abdominal pain, diarrhoea, vomiting", GI, "acute",
                   "WHO: onset 6-72 h (usually 12-36 h), lasts 2-7 days", "who_salmonella", "A02.0", "6-72 hours",
                   [KIDS, OLD, IMMUNO])]),
    "salmonella_typhi": dict(name="Salmonella Typhi / Paratyphi", hazard_class="pathogen_bacteria",
        aliases=["typhoid", "salmonella typhi", "paratyphi"], summary="Spread through food and water contaminated by "
                "faeces of an infected person.",
        effects=[E("typhoid_fever", "Typhoid fever", "systemic", "acute", "WHO typhoid fact sheet", "who_typhoid",
                   "A01.0", "6-30 days", [KIDS])]),
    "listeria_monocytogenes": dict(name="Listeria monocytogenes", hazard_class="pathogen_bacteria",
        aliases=["listeria", "listeria monocytogenes"], summary="Grows in the fridge; ready-to-eat meat, soft cheese, "
                "smoked fish.",
        effects=[
            E("invasive_listeriosis", "Invasive listeriosis: septicaemia, meningitis (20-30% fatal)", "systemic",
              "acute", "WHO: case fatality 20-30%; incubation up to 90 days", "who_listeria", "A32", "1-2 weeks (up to 90 days)",
              [PREG, OLD, IMMUNO]),
            E("pregnancy_loss", "Miscarriage, stillbirth, newborn infection", "reproductive", "acute",
              "WHO: pregnant women ~20x more likely to get listeriosis", "who_listeria", "O03", "1-2 weeks", [PREG])]),
    "stec": dict(name="Shiga toxin-producing E. coli (STEC)", hazard_class="pathogen_bacteria",
        aliases=["e. coli o157", "e.coli o157", "stec", "vtec", "shiga toxin", "escherichia coli o157"],
        summary="Undercooked minced meat, raw milk, contaminated vegetables and sprouts.",
        effects=[
            E("acute_gastroenteritis", "Bloody diarrhoea, abdominal cramps", GI, "acute",
              "WHO: incubation 3-8 days", "who_ecoli", "A04.3", "3-8 days"),
            E("hus_kidney_failure", "Haemolytic uraemic syndrome (acute kidney failure)", "renal", "acute",
              "WHO: develops in ~10% of patients, mostly young children and the elderly", "who_ecoli", "D59.3",
              "1-2 weeks", [KIDS, OLD])]),
    "escherichia_coli": dict(name="Escherichia coli (indicator / pathogenic)", hazard_class="pathogen_bacteria",
        aliases=["e. coli", "e.coli", "escherichia coli"], summary="A marker of faecal contamination; some strains "
                "cause diarrhoea.",
        effects=[E("acute_gastroenteritis", "Diarrhoeal illness", GI, "acute",
                   "WHO food safety fact sheet (enterotoxigenic E. coli)", "who_food_safety", "A04.4", "hours to days",
                   [KIDS])]),
    "campylobacter": dict(name="Campylobacter", hazard_class="pathogen_bacteria", aliases=["campylobacter jejuni"],
        summary="Undercooked poultry, raw milk.",
        effects=[E("acute_gastroenteritis", "Campylobacteriosis: diarrhoea, fever, abdominal pain", GI, "acute",
                   "WHO campylobacter fact sheet", "who_campylobacter", "A04.5", "2-5 days", [KIDS]),
                 E("guillain_barre", "Guillain-Barre syndrome (rare complication)", "nervous", "acute",
                   "WHO campylobacter fact sheet", "who_campylobacter", "G61.0", "weeks")]),
    "vibrio_cholerae": dict(name="Vibrio cholerae", hazard_class="pathogen_bacteria", aliases=["cholera"],
        summary="Contaminated water and food, raw seafood.",
        effects=[E("cholera", "Cholera: profuse watery diarrhoea, severe dehydration", GI, "acute",
                   "WHO cholera fact sheet", "who_cholera", "A00", "12 hours-5 days", [KIDS])]),
    "vibrio": dict(name="Vibrio (parahaemolyticus, vulnificus)", hazard_class="pathogen_bacteria",
        aliases=["vibrio parahaemolyticus", "vibrio vulnificus", "vibrio spp"], summary="Raw or undercooked seafood.",
        effects=[E("acute_gastroenteritis", "Vibriosis: diarrhoea, vomiting; severe wound/blood infection (vulnificus)",
                   GI, "acute", "CDC vibrio", "cdc_vibrio", "A05.3", "24 hours", [IMMUNO])]),
    "staphylococcus_aureus": dict(name="Staphylococcus aureus (enterotoxin)", hazard_class="pathogen_bacteria",
        aliases=["staphylococcus aureus", "s. aureus", "staphylococcal enterotoxin"],
        summary="Handled foods left at room temperature (sweets, dairy, sandwiches).",
        effects=[E("toxin_food_poisoning", "Sudden vomiting and cramps from pre-formed toxin", GI, "acute",
                   "CDC: symptoms within 30 min-8 h", "cdc_staph", "A05.0", "30 min-8 hours")]),
    "bacillus_cereus": dict(name="Bacillus cereus", hazard_class="pathogen_bacteria", aliases=["b. cereus", "bacillus cereus"],
        summary="Cooked rice and starchy foods held warm; spices.",
        effects=[E("toxin_food_poisoning", "Vomiting (emetic) or diarrhoeal food poisoning", GI, "acute",
                   "FDA Bad Bug Book: emetic form within about 0.5-6 h, diarrhoeal form 6-15 h", "fda_badbug", "A05.4",
                   "0.5-15 hours")]),
    "clostridium_perfringens": dict(name="Clostridium perfringens", hazard_class="pathogen_bacteria",
        aliases=["c. perfringens", "clostridium perfringens"], summary="Large batches of meat, curries and gravies "
                "cooled slowly.",
        effects=[E("toxin_food_poisoning", "Diarrhoea and cramps", GI, "acute", "CDC", "cdc_perfringens", "A05.2",
                   "6-24 hours")]),
    "clostridium_botulinum": dict(name="Clostridium botulinum (botulinum toxin)", hazard_class="pathogen_bacteria",
        aliases=["botulism", "clostridium botulinum", "botulinum"], summary="Improperly canned, fermented or "
                "vacuum-packed foods.",
        effects=[E("botulism", "Botulism: descending paralysis, can be fatal", "nervous", "acute", "WHO botulism",
                   "who_botulism", "A05.1", "12-36 hours")]),
    "shigella": dict(name="Shigella", hazard_class="pathogen_bacteria", aliases=["shigella spp"],
        summary="Food handled by an infected person, contaminated water.",
        effects=[E("acute_gastroenteritis", "Shigellosis (bacillary dysentery)", GI, "acute",
                   "WHO food safety fact sheet", "who_food_safety", "A03", "1-3 days", [KIDS])]),
    "norovirus": dict(name="Norovirus", hazard_class="pathogen_virus", aliases=["norovirus", "norwalk"],
        summary="Shellfish, fresh produce and ready-to-eat food handled by an infected person.",
        effects=[E("acute_gastroenteritis", "Vomiting and watery diarrhoea", GI, "acute", "WHO / CDC", "cdc_norovirus",
                   "A08.1", "12-48 hours", [KIDS, OLD])]),
    "hepatitis_a": dict(name="Hepatitis A virus", hazard_class="pathogen_virus", aliases=["hepatitis a", "hav"],
        summary="Raw shellfish, frozen berries, food handled by an infected person.",
        effects=[E("viral_hepatitis", "Hepatitis A (liver inflammation, jaundice)", "hepatic", "acute",
                   "WHO hepatitis A", "who_hepa", "B15", "14-28 days")]),
    "hepatitis_e": dict(name="Hepatitis E virus", hazard_class="pathogen_virus", aliases=["hepatitis e", "hev"],
        summary="Faecally contaminated water; undercooked pork.",
        effects=[E("viral_hepatitis", "Hepatitis E; severe in pregnancy", "hepatic", "acute", "WHO hepatitis E",
                   "who_hepe", "B17.2", "2-10 weeks", [PREG])]),
}

# Pesticide chemical classes: the mode of action decides the acute syndrome.
PESTICIDE_CLASSES: dict[str, dict] = {
    "organophosphate": dict(
        members=["acephate", "chlorpyrifos", "chlorpyrifosmethyl", "diazinon", "dichlorvos", "dimethoate", "edifenphos",
                 "ethion", "fenitrothion", "iprobenfos", "malathion", "methamidophos", "monocrotophos", "omethoate",
                 "parathion", "parathionmethyl", "phenthoate", "phorate", "phosalone", "phosphamidon",
                 "pirimiphosmethyl", "profenofos", "quinalphos", "triazophos", "anilophos", "fenthion", "phosmet",
                 "terbufos", "disulfoton", "ethoprophos", "fenamiphos", "methidathion", "azinphosmethyl",
                 "oxydemetonmethyl", "thiometon", "cadusafos", "fosthiazate", "tolclofosmethyl"],
        effects=[E("cholinergic_poisoning", "Acute cholinergic poisoning: sweating, vomiting, pinpoint pupils, "
                   "breathing failure (acetylcholinesterase inhibition)", "nervous", "acute",
                   "US EPA: organophosphates inhibit acetylcholinesterase, producing cholinergic toxicity",
                   "epa_rmpp_op", "T60.0", "minutes to hours", [KIDS]),
                 E("chronic_neurotoxicity", "Long-term effects on the developing nervous system", "nervous",
                   "chronic", "WHO: pesticides can have chronic health effects", "who_pesticides", None, "years",
                   [PREG, KIDS])]),
    "carbamate": dict(
        members=["aldicarb", "benfuracarb", "carbaryl", "carbofuran", "carbosulfan", "fenobucarb", "methiocarb",
                 "methomyl", "oxamyl", "pirimicarb", "propoxur", "thiodicarb"],
        effects=[E("cholinergic_poisoning", "Acute cholinergic poisoning (reversible acetylcholinesterase inhibition)",
                   "nervous", "acute", "US EPA: N-methyl carbamates reversibly inhibit acetylcholinesterase",
                   "epa_rmpp_carb", "T60.0", "minutes to hours", [KIDS])]),
    "organochlorine": dict(
        members=["aldrinanddieldrin", "aldrin", "dieldrin", "chlordane", "ddt", "dicofol", "endosulfan", "endrin",
                 "heptachlor", "hexachlorocyclohexane", "lindane", "hexachlorobenzene"],
        effects=[E("chronic_neurotoxicity", "Nervous-system toxicity; persistent, accumulates in body fat and breast milk",
                   "nervous", "chronic", "Persistent organic pollutants; WHO food safety fact sheet",
                   "who_food_safety", "T60.1", "years", [PREG, KIDS]),
                 E("endocrine_disruption", "Hormone disruption", "endocrine", "chronic",
                   "WHO: persistent organic pollutants interfere with hormones", "who_food_safety", None, "years")]),
    "pyrethroid": dict(
        members=["bifenthrin", "cyfluthrin", "cyhalothrin", "cypermethrin", "deltamethrin", "esfenvalerate", "etofenprox",
                 "fenpropathrin", "fenvalerate", "permethrin", "flumethrin"],
        effects=[E("acute_neurotoxicity", "Tingling, dizziness, tremor at high doses (sodium-channel toxicity)",
                   "nervous", "acute", "US EPA Recognition and Management of Pesticide Poisonings", "epa_rmpp",
                   "T60.2", "hours")]),
    "neonicotinoid": dict(
        members=["acetamiprid", "clothianidin", "dinotefuran", "imidacloprid", "thiacloprid", "thiamethoxam"],
        effects=[E("acute_neurotoxicity", "Nicotinic toxicity at high doses: vomiting, tremor, fast heart rate",
                   "nervous", "acute", "US EPA Recognition and Management of Pesticide Poisonings", "epa_rmpp",
                   "T60.2", "hours")]),
}
GENERIC_PESTICIDE = [E("pesticide_toxicity", "Pesticide toxicity (acute at high doses; possible long-term effects)",
                       "multiple", "both", "WHO: pesticides can have both acute and chronic health effects",
                       "who_pesticides", "T60.9", "hours to years")]

# RASFF hazard categories -> hazard class (for hazards not individually in the KB).
RASFF_CATEGORY_CLASS = {
    "pesticide residues": "pesticide", "mycotoxins": "mycotoxin", "pathogenic micro-organisms": "pathogen_bacteria",
    "metals": "heavy_metal", "heavy metals": "heavy_metal", "allergens": "allergen",
    "residues of veterinary medicinal products": "veterinary_drug", "food additives and flavourings": "additive",
    "industrial contaminants": "environmental_pollutant", "environmental pollutants": "environmental_pollutant",
    "process contaminants": "process_contaminant", "natural toxins (other)": "natural_toxin",
    "biotoxins (other)": "marine_biotoxin", "marine biotoxins": "marine_biotoxin",
    "foreign bodies": "foreign_body", "non-pathogenic micro-organisms": "hygiene_indicator",
    "microbial contaminants (other)": "hygiene_indicator", "poor or insufficient controls": "control_failure",
    "adulteration / fraud": "adulterant", "composition": "composition", "genetically modified food or feed": "gmo",
    "novel food": "novel_food", "parasitic infestation": "parasite", "migration": "food_contact_migration",
    "organoleptic aspects": "quality", "packaging defective / incorrect": "packaging", "labelling absent/incomplete/incorrect": "labelling",
    "radiation": "radionuclide", "chemical contamination (other)": "other", "other hazards": "other",
}

CLASS_EFFECTS = {   # broad class-level outcomes for hazards the KB does not list individually
    "pesticide": GENERIC_PESTICIDE,
    "pathogen_bacteria": [E("acute_gastroenteritis", "Foodborne bacterial infection (gastroenteritis)", GI, "acute",
                            "WHO food safety fact sheet", "who_food_safety", "A05.9", "hours to days", [KIDS, OLD])],
    "mycotoxin": [E("mycotoxin_toxicity", "Mycotoxin toxicity (liver, kidney, immune effects)", "multiple", "chronic",
                    "WHO mycotoxins fact sheet", "who_mycotoxins", None, "years")],
    "heavy_metal": [E("metal_toxicity", "Heavy-metal toxicity (kidney, nervous system)", "multiple", "chronic",
                      "WHO food safety fact sheet", "who_food_safety", None, "years", [KIDS, PREG])],
    "veterinary_drug": [E("antimicrobial_resistance_and_toxicity", "Drug residue toxicity; antimicrobial resistance",
                          "multiple", "chronic", "EFSA opinions on banned veterinary drugs", "efsa_nitrofurans",
                          None, "years")],
    "allergen": HAZARDS["undeclared_allergen"]["effects"],
    "marine_biotoxin": [E("shellfish_poisoning", "Shellfish poisoning", "nervous", "acute", "FAO marine biotoxins",
                          "fao_biotoxins", "T61.2", "hours")],
    "pathogen_virus": [E("acute_gastroenteritis", "Viral foodborne illness", GI, "acute", "WHO food safety fact sheet",
                         "who_food_safety", "A08.4", "1-2 days")],
}


# ---------------------------------------------------------------- IARC

def js_literal_to_json(js: str, start: int) -> str:
    """The JS object literal starting at js[start] ('{') -> a JSON string.
    Handles what a minifier emits: unquoted keys, single- or double-quoted
    strings, `!0`/`!1` for true/false. Stops at the matching close brace."""
    out, i, depth = [], start, 0
    n = len(js)
    while i < n:
        c = js[i]
        if c in "\"'":
            q, j, buf = c, i + 1, []
            while j < n and js[j] != q:
                if js[j] == "\\" and j + 1 < n:
                    nxt = js[j + 1]
                    buf.append(nxt if nxt == "'" else "\\" + nxt)
                    j += 2
                    continue
                buf.append('\\"' if js[j] == '"' else js[j])
                j += 1
            out.append('"' + "".join(buf) + '"')
            i = j + 1
            continue
        if c == "!" and i + 1 < n and js[i + 1] in "01":
            out.append("true" if js[i + 1] == "0" else "false")
            i += 2
            continue
        m = re.match(r"[A-Za-z_$][\w$]*(?=\s*:)", js[i:i + 64]) if (out and out[-1] in "{,") else None
        if m:
            out.append('"' + m.group(0) + '"')
            i += len(m.group(0))
            continue
        if c == "{" or c == "[":
            depth += 1
        elif c == "}" or c == "]":
            depth -= 1
        out.append(c)
        i += 1
        if depth == 0:
            break
    return "".join(out)


def parse_iarc_bundle(js: str) -> tuple[dict, list[dict]]:
    """IARC's list-of-classifications app ships its data as a JS object literal:
    e.exports={last_volume:"142",last_update:"...",agents:[{name:"...",group:"1",
    cas:[...],volume:[...],year:2012,yeareval:2009,comment:"..."},...]}."""
    start = js.find("{last_volume:")
    if start < 0:
        raise ValueError("IARC bundle layout changed: no last_volume object")
    data = json.loads(js_literal_to_json(js, start))
    meta = {"last_volume": data.get("last_volume"), "last_update": data.get("last_update")}
    agents = []
    for a in data["agents"]:
        name = re.sub(r"<[^>]+>", "", a.get("name") or "").strip()
        agents.append({"name": name, "group": (a.get("group") or "").strip(), "cas": a.get("cas") or [],
                       "volumes": a.get("volume") or [], "year": a.get("year"), "comment": a.get("comment")})
    if len(agents) < 500:
        raise ValueError(f"IARC list has only {len(agents)} agents — layout probably changed")
    return meta, agents


def fetch_iarc() -> tuple[dict, list[dict]]:
    req = urllib.request.Request(IARC_BUNDLE, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return parse_iarc_bundle(r.read().decode("utf-8", "replace"))


# ---------------------------------------------------------------- loading

def _effect_rows(hazard_key: str, effects: list[dict]) -> list[tuple]:
    out = []
    for e in effects:
        title, url = SRC[e["source"]]
        out.append((hazard_key, e["outcome_key"], e["outcome"], e["icd10"], e["organ_system"], e["exposure"], e["onset"],
                    e["vulnerable_groups"], e["evidence"], title, url))
    return out


def build(iarc_agents: Optional[list[dict]] = None, pesticide_cas: Optional[dict[str, str]] = None,
          regulated: Optional[set[str]] = None) -> dict:
    """Pure: the curated KB (+ IARC join) -> hazard and effect rows. `regulated` =
    pesticide keys that appear in some rule-book; only those get the generic
    pesticide outcome (an EU active-substance record alone — a pheromone, a
    microorganism — is not evidence of a food-residue health effect)."""
    by_name = {a["name"].lower(): a for a in iarc_agents or []}
    by_cas: dict[str, dict] = {}
    for a in iarc_agents or []:
        for c in a["cas"]:
            by_cas[c.strip()] = a
    hazards, effects = [], []
    for key, h in HAZARDS.items():
        agent = by_name.get((h.get("iarc_agent_override") or h.get("iarc_agent") or "").lower())
        parent = h.get("parent")
        effs = h.get("effects") or (HAZARDS[parent]["effects"] if parent else [])
        srcs = sorted({SRC[e["source"]][1] for e in effs} | {SRC[k][1] for k in h.get("source_keys", [])})
        hazards.append({"hazard_key": key, "name": h["name"], "hazard_class": h["hazard_class"],
                        "aliases": h.get("aliases", []), "summary": h.get("summary") or
                        (HAZARDS[parent].get("summary") if parent else None),
                        "iarc_group": agent["group"] if agent else None, "iarc_agent": agent["name"] if agent else None,
                        "sources": [{"url": u} for u in srcs] + ([{"url": IARC_PAGE, "title": "IARC"}] if agent else [])})
        effects += _effect_rows(key, effs)
    pest_seen = set()
    for cls, d in PESTICIDE_CLASSES.items():
        for m in d["members"]:
            pest_seen.add(m)
            effects += _effect_rows(m, d["effects"])
    iarc_pesticides = []
    for key, cas in (pesticide_cas or {}).items():
        a = by_cas.get((cas or "").strip())
        if a:
            iarc_pesticides.append({"hazard_key": key, "iarc_group": a["group"], "iarc_agent": a["name"]})
        if key not in pest_seen and key not in HAZARDS and (regulated is None or key in regulated):
            effects += _effect_rows(key, GENERIC_PESTICIDE)
    return {"hazards": hazards, "effects": effects, "iarc_pesticides": iarc_pesticides,
            "pesticide_class": {m: c for c, d in PESTICIDE_CLASSES.items() for m in d["members"]}}


def pesticide_class_of(hazard_key: Optional[str]) -> Optional[str]:
    for c, d in PESTICIDE_CLASSES.items():
        if hazard_key in d["members"]:
            return c
    return None


def run(dry_run: bool = False) -> dict:
    meta, agents = fetch_iarc()
    from pipeline.config import pg_connect
    conn = None if dry_run else pg_connect()
    cas: dict[str, str] = {}
    regulated: set[str] = set()
    if conn:
        with conn.cursor() as cur:
            cur.execute("SELECT hazard_key, cas_number FROM hazards WHERE hazard_class='pesticide' AND cas_number IS NOT NULL")
            cas = dict(cur.fetchall())
            cur.execute("SELECT DISTINCT hazard_raw, hazard_key FROM food_standards "
                        "WHERE standard_type='pesticide_mrl' AND hazard_key IS NOT NULL")
            from pipeline.sources.standards_common import substance_key
            for raw, fam in cur.fetchall():
                regulated.add(fam)
                regulated.add(substance_key(raw))
    kb = build(agents, cas, regulated)
    info = {"iarc_agents": len(agents), "iarc_last_volume": meta["last_volume"], "iarc_last_update": meta["last_update"],
            "kb_hazards": len(kb["hazards"]), "effect_rows": len(kb["effects"]),
            "pesticides_with_iarc_group": len(kb["iarc_pesticides"])}
    if dry_run:
        return {**info, "dry_run": True}
    from psycopg2.extras import execute_batch
    try:
        with conn.cursor() as cur:
            execute_batch(cur,
                """INSERT INTO hazards (hazard_key, name, hazard_class, aliases, iarc_group, iarc_agent, summary,
                                        sources, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                   ON CONFLICT (hazard_key) DO UPDATE SET name=EXCLUDED.name, hazard_class=EXCLUDED.hazard_class,
                     aliases=EXCLUDED.aliases, iarc_group=EXCLUDED.iarc_group, iarc_agent=EXCLUDED.iarc_agent,
                     summary=EXCLUDED.summary, sources=EXCLUDED.sources, updated_at=NOW()""",
                [(h["hazard_key"], h["name"], h["hazard_class"], h["aliases"], h["iarc_group"], h["iarc_agent"],
                  h["summary"], json.dumps(h["sources"])) for h in kb["hazards"]], page_size=500)
            execute_batch(cur, "UPDATE hazards SET iarc_group=%s, iarc_agent=%s, updated_at=NOW() WHERE hazard_key=%s",
                          [(p["iarc_group"], p["iarc_agent"], p["hazard_key"]) for p in kb["iarc_pesticides"]],
                          page_size=500)
            cur.execute("DELETE FROM hazard_health_effects")
            execute_batch(cur,
                """INSERT INTO hazard_health_effects (hazard_key, outcome_key, outcome, icd10, organ_system, exposure,
                     onset, vulnerable_groups, evidence, source_title, source_url)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (hazard_key, outcome_key) DO NOTHING""",
                [tuple(e) for e in kb["effects"]], page_size=500)
        conn.commit()
    finally:
        conn.close()
    return {**info, "inserted": len(kb["effects"])}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    print(run(ap.parse_args().dry_run))


if __name__ == "__main__":
    main()
