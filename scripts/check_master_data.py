"""Align the flow and product names used by the tool with the ecoinvent Master Data.

The tool must harmonise with the Master Data, never the other way round: the Master Data workbook
(path in agritool.cfg or AGRITOOL_MASTER_DATA_PATH) is only read.

The names to check are the rows of two review tables in data/:

  elementary_flow_alignment.csv       elementary flows written by the tool
  intermediate_exchange_alignment.csv intermediate exchanges (products) written by the tool

They were generated on 2026-10-09 from the ecoSpold writer of the legacy tool (Java templates and
pesticide mappings of sri-crop-tool); since then the tables themselves are the inventory of
names, so the legacy code is no longer needed. To add a flow, add a row with source,
model_variable, legacy_name, legacy_unit (and compartment / subcompartment for elementary flows)
and run this script.

For every row not yet signed in reviewed_by the script recomputes:

  status       ok        exact match in the Master Data, nothing to do
               renamed   same flow, Master Data spelling (documented rule below)
               proposed  proposal for the Master Data name: confirm or change it
               decision  several Master Data names are possible (see candidates): choose one
               missing   no candidate found: give a name or mark not_needed
  md312_name, md312_uuid, md312_unit, candidates, note

Signed rows (reviewer set status confirmed / not_needed and reviewed_by) are kept; only their
UUID and unit are refreshed, and names that do not exist in the Master Data are reported.

Two more review tables hold the products whose Master Data properties the model reads
(decision L74, template v3 T23):

  crop_main_product.csv   reference product of each crop (legacy names from the legacy
                          ecospold_main_output_mapping.properties)
  coproduct_list.csv      co-products offered in the template (legacy labels of yield_BP1..3)

Their unsigned rows get status, md312_product, md312_uuid, candidates and note in the same way
(rules MAIN_PRODUCT_* and COPRODUCT_* below). From the products named in both tables the script
then writes the generated table

  md312_product_properties.csv   dry mass, water in wet mass, carbon content (non-fossil), price
                                 (sheet 'IntermediateExchanges prop.') and by-product
                                 classification (sheet 'IntermediateExchanges')

which the model reads through dataloader (the Master Data is not in the repository, O4).

Usage (repository root):  .venv\\Scripts\\python scripts\\check_master_data.py
"""
import csv
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "legacy_model"))

import config  # noqa: E402

DATA = ROOT / "data"
ELEMENTARY_FILE = DATA / "elementary_flow_alignment.csv"
INTERMEDIATE_FILE = DATA / "intermediate_exchange_alignment.csv"
MAIN_PRODUCT_FILE = DATA / "crop_main_product.csv"
COPRODUCT_FILE = DATA / "coproduct_list.csv"
PROPERTIES_FILE = DATA / "md312_product_properties.csv"

# Legacy names (ecoinvent 3.4 era) -> Master Data 3.12 name of the same flow. Master Data 3.12
# has only the ionic forms of these metals in water and agricultural soil.
RENAME_RULES = {
    "Cadmium, ion": "Cadmium II", "Cadmium": "Cadmium II",
    "Lead": "Lead II", "Mercury": "Mercury II",
    "Nickel, ion": "Nickel II", "Nickel": "Nickel II",
    "Zinc, ion": "Zinc II", "Zinc": "Zinc II",
    "Copper, ion": "Copper ion",
}

# Proposals that rely on a judgement (spelling variant, synonym, generic product with the same
# reference basis): status "proposed" with the reason, to be confirmed by the reviewer.
PROPOSAL_RULES = {
    "Phenol, pentachloro-": ("Pentachlorophenol", "same substance, index name vs common name"),
    "Dimethenamid": ("Dimethenamide", "racemic dimethenamid; Dimethenamid-P is the S-enantiomer"),
    "2-Amino-3-chloro-1,4-naphthoquinone": ("Quinoclamine", "chemical name of quinoclamine (CAS 2797-51-5)"),
    "Fosetyl-aluminium": ("Fosetyl-Al", "same substance, abbreviated name"),
    "Iprodion": ("Iprodione", "German spelling"),
    "Prothioconazol": ("Prothioconazole", "German spelling"),
    "Pyraclostrobin (prop)": ("Pyraclostrobin", "suffix (prop) dropped"),
    "Thiophanat-methyl": ("Thiophanate-methyl", "German spelling"),
    "nitrogen fertiliser, as N": ("inorganic nitrogen fertiliser, as N", "generic mineral N fertiliser, same basis (kg N)"),
    "phosphate fertiliser, as P2O5": ("inorganic phosphorus fertiliser, as P2O5", "generic mineral P fertiliser, same basis (kg P2O5)"),
    "potassium fertiliser, as K2O": ("inorganic potassium fertiliser, as K2O", "generic mineral K fertiliser, same basis (kg K2O)"),
    "ammonia, liquid": ("ammonia, anhydrous, liquid", "same product, amount already in kg NH3"),
    "triazine-compound, unspecified": ("triazine-compound", "', unspecified' dropped in 3.12"),
    "transport, tractor and trailer, agricultural": ("transport, freight, tractor and trailer, diesel, agricultural", "same service, unit metric ton*km"),
    "cotton seed": ("cottonseed, for sowing", "superseded by the seed mapping of Fix F6"),
}

# Several Master Data names are possible; the reviewer chooses.
DECISION_RULES = {
    "Chromium, ion": (["Chromium III", "Chromium VI"], "two different substances"),
    "Chromium": (["Chromium III", "Chromium VI"], "two different substances"),
    "Cyfluthrin": (["Beta-cyfluthrin"], "only the beta isomer mixture exists: use it or drop the flow"),
    "Pyrethrine": (["Pyrethrins", "Pyrethrin I", "Pyrethrin II"], "group vs single components"),
    "Pyrethrum": (["Pyrethrum, natural", "Pyrethrins"], "natural extract vs active components"),
    "ammonium nitrate, as N": (["inorganic nitrogen fertiliser, as N", "ammonium nitrate"],
                               "generic as N (same basis) or product in kg (needs N content)"),
    "urea, as N": (["inorganic nitrogen fertiliser, as N", "urea"], "generic as N (same basis) or product in kg (needs N content)"),
    "ammonium sulfate, as N": (["inorganic nitrogen fertiliser, as N", "ammonium sulfate"],
                               "generic as N (same basis) or product in kg (needs N content)"),
    "potassium chloride, as K2O": (["inorganic potassium fertiliser, as K2O", "potassium chloride"],
                                   "generic as K2O (same basis) or product in kg (needs K2O content)"),
    "potassium sulfate, as K2O": (["inorganic potassium fertiliser, as K2O", "potassium sulfate"],
                                  "generic as K2O (same basis) or product in kg (needs K2O content)"),
    "phosphate rock, as P2O5, beneficiated, dry": (["phosphate rock, beneficiated", "inorganic phosphorus fertiliser, as P2O5"],
                                                   "product in kg (needs P2O5 content) or generic as P2O5"),
    "lime": (["limestone, milled, packed", "limestone, milled, loose", "limestone, crushed, washed", "limestone, from algae"],
             "'lime' no longer exists; the model amount is kg CaCO3 (seaweed lime: Ca(OH)2)"),
}

# A model variable written with another exchange than its legacy name (the legacy name is shared with other
# variables, so PROPOSAL_RULES cannot be used): status "proposed", to be confirmed by the reviewer.
VARIABLE_PROPOSAL_RULES = {
    "plantprotection_flaming": ("heat, district or industrial, other than natural gas",
                                "L69: the flaming gas is propane, 46.35 legacy = Master Data propane 46.4; product of "
                                "'heat production, propane, at industrial furnace >100kW' (data/fuel_heating_values.csv)"),
    "quicklime_applied": ("quicklime, milled, loose",
                          "L72 (template v3 T20): CaO in kg of product, spread in bulk; same name in ecoCalc v4; "
                          "other Master Data 3.12 products: 'quicklime, milled, packed', 'quicklime, in pieces, loose'"),
    "hydrated_lime_applied": ("hydrated lime, loose",
                              "L72 (template v3 T20): Ca(OH)2 in kg of product, spread in bulk; same name in ecoCalc v4; "
                              "other Master Data 3.12 product: 'hydrated lime, packed'"),
    "utilities_wateruse_ground": ("Water, well, in ground",
                                  "groundwater source; MD 3.12 'Water, well, in ground'; corrects R7 (walkthrough A10)"),
}

REVIEW_STATUSES = ("confirmed", "not_needed")

# Reference product of a crop (crop_main_product.csv, decision L74), keyed by the legacy name of
# ecospold_main_output_mapping.properties.
MAIN_PRODUCT_RENAME_RULES = {
    "cabbage red": "red cabbage", "cabbage white": "white cabbage",
}
MAIN_PRODUCT_PROPOSAL_RULES = {
    "rice": ("rice, non-basmati", "the default yield is FAOSTAT 'Rice' (paddy); 'rice, basmati' has the same "
                                  "Master Data 3.12 dry mass, carbon content and price"),
    "cotton seed": ("seed-cotton", "the default yield is FAOSTAT 'Seed cotton; unginned'; 'cottonseed' is the "
                                   "seed separated at ginning"),
    "hemp": ("hemp stem, dew-retted", "the default yield is FAOSTAT 'True hemp; raw or retted'; the only hemp "
                                      "stem product of the Master Data"),
    "mulberry": ("mulberry leaves", "mulberry is grown for its leaves (sericulture); no other mulberry product"),
}
MAIN_PRODUCT_DECISION_RULES = {
    "flax": (["flax straw, dew-retted", "flax plant, harvested"],
             "the default yield is FAOSTAT 'Flax; raw or retted'"),
}

# Co-products offered in the template (coproduct_list.csv), keyed by the legacy label of yield_BP1..3.
COPRODUCT_RENAME_RULES = {
    "waste wood untreated": "waste wood, untreated",
}
COPRODUCT_PROPOSAL_RULES = {
    "flax seeds": ("linseed", "seed of flax, the Master Data product of the linseed crop"),
}
COPRODUCT_DECISION_RULES = {}

# Master Data properties copied to md312_product_properties.csv: column -> (sheet property, unit)
PRODUCT_PROPERTIES = {
    "dry_mass_kg_per_kg": ("dry mass", "kg"),
    "water_in_wet_mass_kg_per_kg": ("water in wet mass", "kg"),
    "carbon_content_non_fossil_kg_per_kg_dm": ("carbon content, non-fossil", "dimensionless"),
    "price_eur2005_per_unit": ("price", "EUR2005"),
}


def read_sheet(workbook, name):
    it = workbook[name].iter_rows(values_only=True)
    header = [str(h) for h in next(it)]
    return [dict(zip(header, r)) for r in it]


def read_table(path):
    with open(path, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]


def propose(legacy_name, lookup, pool, rename=RENAME_RULES, proposal=PROPOSAL_RULES, decision=DECISION_RULES,
            cutoff=0.6):
    """(status, md312_name, candidates, note) for a legacy name. ``lookup(name)`` -> MD row."""
    if lookup(legacy_name):
        return "ok", legacy_name, "", ""
    if legacy_name in rename and lookup(rename[legacy_name]):
        return "renamed", rename[legacy_name], "", "Master Data 3.12 name of the same flow"
    case_match = [n for n in pool if n.lower() == legacy_name.lower()]
    if case_match:
        return "renamed", case_match[0], "", "capitalisation only"
    if legacy_name in proposal and lookup(proposal[legacy_name][0]):
        name, reason = proposal[legacy_name]
        return "proposed", name, "", reason
    if legacy_name in decision:
        options, reason = decision[legacy_name]
        return "decision", "", " | ".join(o for o in options if lookup(o)), reason
    return "missing", "", " | ".join(difflib.get_close_matches(legacy_name, pool, n=4, cutoff=cutoff)), ""


def write_table(path, rows, fieldnames=None):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames or list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def update_product_table(path, legacy_column, intermediate, rules):
    """Align a product table (crop_main_product.csv, coproduct_list.csv) like update_table; return problems.

    Unsigned rows get status, md312_product, candidates and note from ``rules`` (rename, proposal,
    decision); signed rows (status confirmed / not_needed and reviewed_by) are kept. The UUID is refreshed.
    """
    rows = read_table(path)
    pool = sorted(intermediate)
    problems = []
    for row in rows:
        if row["reviewed_by"].strip():
            if row["status"] not in REVIEW_STATUSES:
                problems.append("%s: signed row with status '%s' (use confirmed or not_needed)"
                                % (row[legacy_column], row["status"]))
            if row["status"] == "confirmed" and row["md312_product"] not in intermediate:
                problems.append("%s: md312_product '%s' not in the Master Data" % (row[legacy_column], row["md312_product"]))
        else:
            rename, proposal, decision = rules
            status, name, candidates, note = propose(row[legacy_column], intermediate.get, pool, rename, proposal,
                                                     decision, cutoff=0.75)
            row.update(status=status, md312_product=name, candidates=candidates, note=note)
        md = intermediate.get(row["md312_product"])
        row["md312_uuid"] = md["id"] if md else ""
        if md and md["unitName"] != "kg":
            problems.append("%s: '%s' is in %s, the model needs kg" % (row[legacy_column], row["md312_product"], md["unitName"]))
    write_table(path, rows)
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("%s: %d rows %s" % (path.relative_to(ROOT), len(rows), counts))
    for p in problems:
        print("  PROBLEM:", p)
    return problems


def write_product_properties(intermediate, properties):
    """Write md312_product_properties.csv for the products of crop_main_product.csv and coproduct_list.csv.

    One row per product: UUID, unit, by-product classification and the PRODUCT_PROPERTIES amounts. No
    judgement: the values are copied from the Master Data; a note flags a product whose dry mass and
    water in wet mass do not add up to its wet mass of 1 kg (the model reads the dry mass).
    """
    names = sorted({r["md312_product"] for path in (MAIN_PRODUCT_FILE, COPRODUCT_FILE)
                    for r in read_table(path) if r["md312_product"]})
    rows, problems = [], []
    for name in names:
        md = intermediate[name]
        row = {"md312_product": name, "md312_uuid": md["id"], "unit": md["unitName"],
               "by_product_classification": md["By-product classification"]}
        for column, (prop, unit) in PRODUCT_PROPERTIES.items():
            values = properties.get((name, prop), [])
            if len(values) != 1:
                problems.append("%s: %d values of '%s'" % (name, len(values), prop))
                row[column] = ""
                continue
            amount, prop_unit = values[0]
            if prop_unit != unit:
                problems.append("%s: '%s' in %s, expected %s" % (name, prop, prop_unit, unit))
            row[column] = repr(float(amount))
        note = ""
        if row["dry_mass_kg_per_kg"] and row["water_in_wet_mass_kg_per_kg"]:
            total = float(row["dry_mass_kg_per_kg"]) + float(row["water_in_wet_mass_kg_per_kg"])
            if abs(total - 1.0) > 1e-6:
                note = "dry mass + water in wet mass = %.4g kg, not 1 kg (Master Data 3.12)" % total
        row["note"] = note
        rows.append(row)
    write_table(PROPERTIES_FILE, rows, ["md312_product", "md312_uuid", "unit", "by_product_classification"]
                + list(PRODUCT_PROPERTIES) + ["note"])
    print("%s: %d products, %d with a note" % (PROPERTIES_FILE.relative_to(ROOT), len(rows),
                                               sum(1 for r in rows if r["note"])))
    for r in rows:
        if r["note"]:
            print("  NOTE: %s: %s" % (r["md312_product"], r["note"]))
    for p in problems:
        print("  PROBLEM:", p)
    return problems


def update_table(path, lookup, pool_for):
    """Recompute unsigned rows, refresh signed rows, write the table back; return problems."""
    rows = read_table(path)
    problems = []
    for row in rows:
        md_lookup = lambda name, r=row: lookup(r, name)  # noqa: E731
        if row.get("reviewed_by", "").strip():
            md = md_lookup(row["md312_name"]) if row["md312_name"] else None
            if row["status"] not in REVIEW_STATUSES:
                problems.append("%s: signed row with status '%s' (use confirmed or not_needed)"
                                % (row["legacy_name"], row["status"]))
            if row["status"] == "confirmed" and not md:
                problems.append("%s: md312_name '%s' not in the Master Data" % (row["legacy_name"], row["md312_name"]))
        else:
            if row.get("model_variable") in VARIABLE_PROPOSAL_RULES:
                name, note = VARIABLE_PROPOSAL_RULES[row["model_variable"]]
                status, candidates = ("proposed", "") if md_lookup(name) else ("missing", "")
            else:
                status, name, candidates, note = propose(row["legacy_name"], md_lookup, pool_for(row))
            md = md_lookup(name) if name else None
            row.update(status=status, md312_name=name, candidates=candidates, note=note)
        row["md312_uuid"] = md["id"] if md else ""
        row["md312_unit"] = md["unitName"] if md else ""
        if row["md312_unit"] and row["md312_unit"] != row["legacy_unit"] and "UNIT:" not in row["note"]:
            row["note"] = (row["note"] + "; " if row["note"] else "") + \
                "UNIT: tool uses %s, Master Data %s" % (row["legacy_unit"], row["md312_unit"])
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    counts = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("%s: %d rows %s" % (path.relative_to(ROOT), len(rows), counts))
    for p in problems:
        print("  PROBLEM:", p)
    return problems


def main():
    from openpyxl import load_workbook
    wb = load_workbook(config.require_master_data_path(), read_only=True, data_only=True)
    elementary = {(r["name"], r["compartment"], r["subcompartment"]): r for r in read_sheet(wb, "ElementaryExchanges")}
    intermediate = {r["name"]: r for r in read_sheet(wb, "IntermediateExchanges") if r["name"]}
    pools = {}
    for (n, c, s) in elementary:
        pools.setdefault((c, s), []).append(n)
    all_products = sorted(intermediate)

    problems = update_table(
        ELEMENTARY_FILE,
        lambda row, name: elementary.get((name, row["compartment"], row["subcompartment"])),
        lambda row: pools.get((row["compartment"], row["subcompartment"]), []))
    problems += update_table(INTERMEDIATE_FILE, lambda row, name: intermediate.get(name), lambda row: all_products)

    problems += update_product_table(MAIN_PRODUCT_FILE, "legacy_name", intermediate,
                                     (MAIN_PRODUCT_RENAME_RULES, MAIN_PRODUCT_PROPOSAL_RULES, MAIN_PRODUCT_DECISION_RULES))
    problems += update_product_table(COPRODUCT_FILE, "legacy_label", intermediate,
                                     (COPRODUCT_RENAME_RULES, COPRODUCT_PROPOSAL_RULES, COPRODUCT_DECISION_RULES))
    properties = {}
    for r in read_sheet(wb, "IntermediateExchanges prop."):
        if r["name"] and r["amount"] is not None:
            properties.setdefault((r["name"], r["propertyName"]), []).append((r["amount"], r["unitName"]))
    problems += write_product_properties(intermediate, properties)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
