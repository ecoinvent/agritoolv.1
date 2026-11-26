"""Compare the nitrate leaching of the SQCB regression (written) with the nitrate of the nitrogen balance x the leaching
coefficient of Sio et al. (2008) Taula 6 (computed, not written; decision L77).

Sections of the report (Markdown on stdout):
1. Inputs of the coefficient for the regression cases: drainage-season rain and soil class shares.
2. Regression cases: SQCB NO3 (ground + surface water) against the balance NO3, with the balance terms.
3. Default datasets (crop x country of data/default_yield.csv, without GLO and the flooded crops, open ground, all
   other inputs default): median and range of balance NO3 / SQCB NO3, share of zero leaching, the largest differences.
4. Moisture check of the N contents of the default N uptake (L28, L41) against the dry mass of the Master Data product
   of the yield (T24, L74): report only.

Usage (repository root, model environment):
    .venv\\Scripts\\python scripts\\compare_nitrate_methods.py [--top 20] [--csv FILE]
"""
import argparse
import csv
import statistics
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "legacy_model"))
sys.path.insert(0, str(ROOT / "tests" / "legacy_model"))

import config  # noqa: E402
import dataloader  # noqa: E402
import regression_support as rs  # noqa: E402
from models import nitratebalance as nb  # noqa: E402
from models import ricech4model  # noqa: E402
from modelsSequence import ModelsSequence  # noqa: E402

SQCB_KEYS = ("m_N_nitrate_to_groundwater", "m_N_nitrate_to_surfacewater")
TERMS = ("mineral_n", "available_organic_n", "n_som", "crop_residue_n", "irrigation_water_n", "n_uptake", "nh3_n",
         "nox_n", "direct_n2o_n", "balance")
MOISTURE_TOLERANCE = 0.02  # kg dry mass per kg: difference reported as "differs"


def run(inputs):
    """(SQCB NO3 [kg], NModel.last_balance_nitrate) of one dataset, without the Master Data seed lookup."""
    original = config.master_data_path
    config.master_data_path = lambda: None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sequence = ModelsSequence(inputs)
            sequence.executeSequence()
    finally:
        config.master_data_path = original
    model = sequence.nModel
    result = model.compute()  # same inputs: recompute to read the SQCB nitrate of the model itself
    return sum(result[k] for k in SQCB_KEYS), model.last_balance_nitrate, model


def fmt(value, digits=2):
    return "" if value is None else ("%.*f" % (digits, value))


def section_inputs(cases):
    print("## 1. Inputs of the leaching coefficient\n")
    print("| case | crop | country | drainage-season rain mm/yr | crop cycles per year | rain of the cycle mm |")
    print("|---|---|---|---|---|---|")
    for name, (inputs, model, balance) in cases.items():
        rain = balance["drainage_rain_mm"] if balance else None
        print("| %s | %s | %s | %s | %s | %s |" % (name, inputs["crop"], inputs["country"],
                                                fmt(model.drainage_season_precipitation, 0),
                                                fmt(model.crop_cycle_per_year, 3), fmt(rain, 0)))
    print("\nSoil class shares (classes with a share above 0.5 %; depth cm, texture, drainage group) and leached "
          "fraction at the rain of the cycle:\n")
    for name, (inputs, model, balance) in cases.items():
        rain = balance["drainage_rain_mm"] if balance else model.drainage_season_precipitation
        print("**%s** (%s)\n" % (name, "coefficient %.4f" % balance["coefficient"] if balance
                                 else "flooded rice: SQCB only"))
        print("| depth | texture | drainage | share | leached fraction |")
        print("|---|---|---|---|---|")
        for (depth, texture, group), share in sorted(model.leaching_soil_shares.items(), key=lambda x: -x[1]):
            if share > 0.005:
                print("| %d | %s | %s | %.3f | %.3f |" % (depth, texture, group, share,
                                                          nb.leached_fraction(depth, texture, group, rain)))
        print()


def section_cases(cases):
    print("## 2. Regression cases\n")
    print("| term (kg N) | " + " | ".join(cases) + " |")
    print("|---|" + "---|" * len(cases))
    for term in TERMS + ("coefficient", "no3_as_n"):
        values = [cases[c][2][term] if cases[c][2] else None for c in cases]
        print("| %s | %s |" % (term, " | ".join(fmt(v, 4) for v in values)))
    print("| **balance NO3 (kg NO3)** | %s |" % " | ".join(
        fmt(b["nitrate_to_groundwater"] + b["nitrate_to_surfacewater"], 2) if b else "-"
        for _, _, b, _ in cases.values()))
    print("| **SQCB NO3 (kg NO3)** | %s |\n" % " | ".join(fmt(cases[c][3], 2) for c in cases))


def default_datasets():
    countries = {r["country"] for r in dataloader.rows("faostat_country_mapping.csv")} - {"GLO"}
    pairs = sorted({(r["crop"], r["country"]) for r in dataloader.rows("default_yield.csv")
                    if r["country"] in countries and not ricech4model.is_flooded(r["crop"])})
    out = []
    for crop, country in pairs:
        try:
            sqcb, balance, _ = run({"crop": crop, "country": country, "cultivation_type": "open_ground"})
        except Exception as error:  # report, do not stop the comparison
            out.append({"crop": crop, "country": country, "error": "%s: %s" % (type(error).__name__, error)})
            continue
        new = balance["nitrate_to_groundwater"] + balance["nitrate_to_surfacewater"]
        out.append(dict({"crop": crop, "country": country, "sqcb_no3": sqcb, "balance_no3": new,
                         "ratio": new / sqcb if sqcb > 0 else None},
                        **{k: balance[k] for k in TERMS + ("drainage_rain_mm", "coefficient")}))
    return out


def section_defaults(rows, top):
    ok = [r for r in rows if "error" not in r]
    errors = [r for r in rows if "error" in r]
    ratios = sorted(r["ratio"] for r in ok if r["ratio"] is not None)
    print("## 3. Default datasets\n")
    print("- datasets: %d (errors: %d)" % (len(rows), len(errors)))
    if ratios:
        q = statistics.quantiles(ratios, n=4)
        print("- balance NO3 / SQCB NO3: median %.2f, quartiles %.2f-%.2f, range %.2f-%.2f (%d datasets with SQCB > 0)"
              % (statistics.median(ratios), q[0], q[2], ratios[0], ratios[-1], len(ratios)))
    zero_new = sum(1 for r in ok if r["balance_no3"] == 0.0)
    zero_sqcb = sum(1 for r in ok if r["sqcb_no3"] == 0.0)
    negative = sum(1 for r in ok if r["balance"] < 0.0)
    print("- zero leaching: balance %d of %d (%.0f %%; negative balance %d), SQCB %d (%.0f %%)"
          % (zero_new, len(ok), 100.0 * zero_new / len(ok), negative, zero_sqcb, 100.0 * zero_sqcb / len(ok)))
    print("- median kg NO3/ha: balance %.1f, SQCB %.1f\n" % (statistics.median(r["balance_no3"] for r in ok),
                                                          statistics.median(r["sqcb_no3"] for r in ok)))
    print("The %d largest absolute differences (balance - SQCB, kg NO3/ha and crop cycle):\n" % top)
    print("| crop | country | SQCB NO3 | balance NO3 | difference | balance kg N | rain mm | coefficient |")
    print("|---|---|---|---|---|---|---|---|")
    for r in sorted(ok, key=lambda r: -abs(r["balance_no3"] - r["sqcb_no3"]))[:top]:
        print("| %s | %s | %.1f | %.1f | %+.1f | %.1f | %.0f | %.3f |" % (
            r["crop"], r["country"], r["sqcb_no3"], r["balance_no3"], r["balance_no3"] - r["sqcb_no3"],
            r["balance"], r["drainage_rain_mm"], r["coefficient"]))
    if errors:
        print("\nDatasets that could not be run:\n")
        for r in errors:
            print("- %s %s: %s" % (r["crop"], r["country"], r["error"]))
    print()


def section_moisture():
    """N contents of the default N uptake: moisture basis of the source against the Master Data dry mass."""
    print("## 4. Moisture of the N contents of the default N uptake (report only)\n")
    props = dataloader.table("md312_product_properties.csv")
    ludemann = dataloader.table("ludemann2023_world_crop_coefficients.csv")
    print("| crop | source of the N content | dry mass of the source | Master Data product | dry mass MD | check |")
    print("|---|---|---|---|---|---|")
    for row in dataloader.rows("n_uptake_crop_parameters.csv"):
        product = dataloader.crop_main_product(row["crop"])
        md = props[product]["dry_mass_kg_per_kg"] if product else None
        print("| %s | WFLDB 2017 sheet 4 '%s' (g/kg FM) | not stated | %s | %s | basis not stated in the source |"
              % (row["crop"], row["wfldb_crop"], product or "-", fmt(md, 3)))
    for row in dataloader.rows("n_uptake_other_crop_parameters.csv"):
        product = dataloader.crop_main_product(row["crop"])
        md = props[product]["dry_mass_kg_per_kg"] if product else None
        if row["ludemann_item_code"]:
            entry = ludemann[row["ludemann_item_code"]]
            dm = entry["dm_pc"] / 100.0 if entry["dm_pc"] is not None else None
            source = "Ludemann 2023 '%s'" % row["ludemann_item"]
        else:
            dm, source = None, "GRUDAF 2009 Tab. 1 '%s'" % row["grudaf_crop"]
        if dm is None or md is None:
            check = "no dry mass in the extracted table" if dm is None else "no Master Data product"
        else:
            check = "differs (%+.3f)" % (dm - md) if abs(dm - md) > MOISTURE_TOLERANCE else "same"
        print("| %s | %s | %s | %s | %s | %s |" % (row["crop"], source, fmt(dm, 3), product or "-", fmt(md, 3),
                                                   check))
    print()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--top", type=int, default=20, help="number of largest differences to list")
    parser.add_argument("--csv", help="write the default datasets to this CSV file")
    args = parser.parse_args(argv)
    cases = {}
    for name in rs.case_names():
        inputs = rs.load_inputs(name)
        sqcb, balance, model = run(dict(inputs))
        cases[name] = (inputs, model, balance, sqcb)
    print("# Nitrate leaching: SQCB regression against the nitrogen balance (decision L77)\n")
    section_inputs({k: v[:3] for k, v in cases.items()})
    section_cases(cases)
    rows = default_datasets()
    section_defaults(rows, args.top)
    section_moisture()
    if args.csv:
        columns = ["crop", "country", "sqcb_no3", "balance_no3", "ratio", "drainage_rain_mm", "coefficient"] \
            + list(TERMS) + ["error"]
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    main()
