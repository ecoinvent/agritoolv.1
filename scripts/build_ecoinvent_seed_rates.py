"""Build data/ecoinvent312_seed_rates.csv, the seed sown per ha of the ecoinvent 3.12 crop datasets of the sown crops
without FAOSTAT or TCF seed rate, decision L79 (same source and method as the plantings of decision L47).

Source: ecoinvent 3.12, system model 'Allocation, cut-off by classification', release file 'exchanges (3.12, cut-off).xlsx'
(sheet 'exchanges'), copied by FC from the ecoinvent release folder to data/external_data/.

For every dataset (activity and geography) of the activities of the crops of data/seed_rate_crop_mapping.csv with use
'ecoinvent':
  - seed input = sum of the technosphere inputs named in the column ecoinvent_seed_exchanges of the crop (kg per kg of
    the reference product; all reference products of these activities are 1 kg). Other seed inputs of the dataset
    (e.g. the grass seed of the Swiss datasets, sown after the crop) are not counted and are listed on the screen;
  - transformation = sum of the elementary exchanges 'Transformation, from ...' (m2 per kg);
  - seed_kg_per_ha_and_crop_cycle = seed input x 10000 / transformation (the land is transformed once per crop cycle).
A dataset without a seed input of its crop is an error. Only these derived values per ha are stored (no ecoinvent
amounts per kg).

Usage (repository root):
    python scripts/build_ecoinvent_seed_rates.py
    python scripts/build_ecoinvent_seed_rates.py --exchanges <xlsx> --out <path>
"""
import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "legacy_model"))

import dataloader  # noqa: E402

EXCHANGES_FILE = "exchanges (3.12, cut-off).xlsx"
SHEET = "exchanges"
MAPPING = "seed_rate_crop_mapping.csv"
COLUMNS = ["activity_name", "geography", "reference_product", "seed_exchange", "seed_kg_per_ha_and_crop_cycle"]


def _round(value, digits=6):
    return float("%.*g" % (digits, value))


def seed_exchanges_per_activity():
    """{activity: set of seed exchange names} of the crops with use 'ecoinvent'."""
    activities = {}
    for row in dataloader.rows(MAPPING):
        if row["use"] != "ecoinvent":
            continue
        exchanges = set(filter(None, row["ecoinvent_seed_exchanges"].split("|")))
        for activity in filter(None, row["ecoinvent_activities"].split("|")):
            if activity in activities and activities[activity] != exchanges:
                raise ValueError("%s: activity %r mapped with different seed exchanges" % (MAPPING, activity))
            activities[activity] = exchanges
    return activities


def read_exchanges(path, activities):
    """{activityId: dataset} with the seed inputs, transformation and reference product of the given activities."""
    import openpyxl
    workbook = openpyxl.load_workbook(path, read_only=True)
    rows = workbook[SHEET].iter_rows(values_only=True)
    index = {name: i for i, name in enumerate(next(rows))}
    datasets = defaultdict(lambda: {"seed": defaultdict(float), "other_seed": set(), "transformation": 0.0,
                                    "reference": []})
    for row in rows:
        activity = row[index["activityName"]]
        if activity not in activities:
            continue
        name, unit, amount = (row[index["exchange name"]], row[index["exchange unitName"]],
                              row[index["exchange amount"]])
        dataset = datasets[row[index["activityId"]]]
        dataset["activity_name"], dataset["geography"] = activity, row[index["geography"]]
        group = row[index["group"]]
        if group == "ReferenceProduct":
            dataset["reference"].append((name, unit, amount))
        elif group == "FromTechnosphere" and name in activities[activity]:
            if unit != "kg":
                raise ValueError("%s %s: seed input %r in %r" % (activity, dataset["geography"], name, unit))
            dataset["seed"][name] += amount
        elif group == "FromTechnosphere" and "seed" in name.lower():
            dataset["other_seed"].add(name)
        elif group == "FromEnvironment" and name.startswith("Transformation, from "):
            if unit != "m2":
                raise ValueError("%s: transformation in %r" % (activity, unit))
            dataset["transformation"] += amount
    return datasets


def build(path):
    activities = seed_exchanges_per_activity()
    datasets = read_exchanges(path, activities)
    missing = set(activities) - {d["activity_name"] for d in datasets.values()}
    if missing:
        raise ValueError("activities not found in %s: %s" % (path, sorted(missing)))
    out, not_counted = [], []
    for dataset in datasets.values():
        label = "%s, %s" % (dataset["activity_name"], dataset["geography"])
        if [(unit, amount) for _, unit, amount in dataset["reference"]] != [("kg", 1)]:
            raise ValueError("%s: reference product %r" % (label, dataset["reference"]))
        if not dataset["seed"]:
            raise ValueError("%s: no seed input among %s" % (label, sorted(activities[dataset["activity_name"]])))
        if dataset["other_seed"]:
            not_counted.append("%s: %s" % (label, "|".join(sorted(dataset["other_seed"]))))
        out.append({"activity_name": dataset["activity_name"], "geography": dataset["geography"],
                    "reference_product": dataset["reference"][0][0],
                    "seed_exchange": "|".join(sorted(dataset["seed"])),
                    "seed_kg_per_ha_and_crop_cycle": _round(sum(dataset["seed"].values()) * 10000.0
                                                            / dataset["transformation"])})
    out.sort(key=lambda row: (row["activity_name"], row["geography"]))
    return out, sorted(not_counted)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exchanges", default=str(dataloader.EXTERNAL_DATA_DIR / EXCHANGES_FILE))
    parser.add_argument("--out", default=str(dataloader.DATA_DIR / "ecoinvent312_seed_rates.csv"))
    args = parser.parse_args()
    rows, not_counted = build(args.exchanges)
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print("%d rows written to %s" % (len(rows), args.out))
    print("other seed inputs, not counted: %s" % ("; ".join(not_counted) or "none"))


if __name__ == "__main__":
    main()
