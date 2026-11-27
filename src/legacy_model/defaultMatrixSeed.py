# Seeds per ha of the sown crops, kg/(ha and crop cycle): the crops of data/seed_rate_crop_mapping.csv with use
# 'sua_tcf' come from data/default_seed.csv (FAOSTAT SUA seed / area harvested of the next year, 2021-2023, checked
# against the FAO Technical Conversion Factors; built by scripts/build_default_seed.py; decision L46); the crops with use
# 'ecoinvent' from the ecoinvent 3.12 datasets of data/ecoinvent312_seed_rates.csv (built by
# scripts/build_ecoinvent_seed_rates.py; decision L79); the crops with use 'legacy' keep the GLO values of _LEGACY_SEEDS.
# Seedlings and trees per ha (decision L47): the crops of data/ecoinvent312_planting_crop_mapping.csv with use
# 'ecoinvent' or 'proxy' come from the ecoinvent 3.12 datasets of data/ecoinvent312_planting_rates.csv (built by
# scripts/build_ecoinvent_planting_rates.py), in the quantity of the mapping: per ha and crop cycle, or per ha and year
# for the plantings amortised over the plantation lifetime (defaultGeneration.PlantingDefaultGenerator multiplies them by
# the orchard lifetime) and for mint; the crops with use 'legacy' keep _LEGACY_SEEDLINGS and _LEGACY_TREES.
# Country value of the ecoinvent crops = mean of the datasets of the country and its regions; GLO = mean of the RoW
# datasets or, without a RoW dataset, mean of the values of all geographies.
# legacy, undocumented, provisional: _LEGACY_SEEDS, _LEGACY_SEEDLINGS and _LEGACY_TREES (generated from the Quantis
# workbook GD_crop); these crops have no source, and defaultGeneration warns whenever their default is used (L79).
import statistics
from collections import defaultdict

import dataloader

SEED_MAPPING = "seed_rate_crop_mapping.csv"
PLANTING_MAPPING = "ecoinvent312_planting_crop_mapping.csv"
_DEFAULT_SEED_TABLE = "default_seed.csv"
_SEED_RATES = "ecoinvent312_seed_rates.csv"
_PLANTING_RATES = "ecoinvent312_planting_rates.csv"

#from GD_crop Seeds_L0
#only glo as all values per country are the same
_LEGACY_SEEDS = {
    "cassava": {"GLO": 0.0},
    "guar": {"GLO": 0.0},
    "turmeric": {"GLO": 100.0},
}

#GD_crop Seedlings_L0
_LEGACY_SEEDLINGS = {
    "chilli": {"GLO": 0.0},
    "eggplant": {"GLO": 0.0},
    "ginger": {"GLO": 0.0},
    "raspberry": {},
}

#No values, as data in GD crops are for the whole lifetime
#GD_crop Trees_L0
_LEGACY_TREES = {
    "blueberry": {},
    "cranberry": {},
    "pineapple": {},
    "sugarcane": {},
}


def _ecoinvent_means(mapping_row, rates, quantity):
    """{country: value} of a crop mapped to ecoinvent datasets: mean of the datasets of the crop whose geography is the
    country or one of its regions (BR-MG -> BR, US-CA -> US), without the excluded geographies of the mapping, for the
    countries of faostat_country_mapping.csv; GLO = mean of the RoW datasets or, when ecoinvent has no RoW dataset,
    mean of the values of all geographies of the crop (e.g. RER)."""
    countries = {row["country"] for row in dataloader.rows("faostat_country_mapping.csv")} - {"GLO"}
    activities = set(mapping_row["ecoinvent_activities"].split("|"))
    excluded = set(mapping_row["excluded_geographies"].split("|")) - {""}
    values = defaultdict(list)
    for row in rates:
        if row["activity_name"] in activities and row["geography"] not in excluded:
            values[row["geography"].split("-")[0]].append(float(row[quantity]))
    if not values:
        raise ValueError("no ecoinvent dataset of %s" % mapping_row["crop"])
    means = {country: statistics.mean(v) for country, v in values.items()}
    table = {country: mean for country, mean in means.items() if country in countries}
    table["GLO"] = means["RoW"] if "RoW" in means else statistics.mean(means.values())
    return table


def _load_default_seeds():
    seeds = {crop: dict(values) for crop, values in _LEGACY_SEEDS.items()}
    for row in dataloader.rows(_DEFAULT_SEED_TABLE):
        seeds.setdefault(row["crop"], {})[row["country"]] = float(row["seed_kg_per_ha"])
    rates = dataloader.rows(_SEED_RATES)
    for crop in dataloader.rows(SEED_MAPPING):
        if crop["use"] == "ecoinvent":
            seeds[crop["crop"]] = _ecoinvent_means(crop, rates, "seed_kg_per_ha_and_crop_cycle")
    return seeds


def _load_planting_rates(template_field, legacy):
    """{crop: {country: rate}} of the crops of the template field: legacy values, and for the crops with use 'ecoinvent'
    or 'proxy' the means of the ecoinvent datasets of the crop (_ecoinvent_means) in the quantity of the mapping."""
    rates = dataloader.rows(_PLANTING_RATES)
    table = {crop: dict(values) for crop, values in legacy.items()}
    for crop in dataloader.rows(PLANTING_MAPPING):
        if crop["template_field"] != template_field or crop["use"] == "legacy":
            continue
        table[crop["crop"]] = _ecoinvent_means(crop, rates, crop["quantity"])
    return table


def legacy_crops(mapping):
    """Crops of the mapping with use 'legacy': no source, legacy value or none (legacy, undocumented, provisional)."""
    return frozenset(row["crop"] for row in dataloader.rows(mapping) if row["use"] == "legacy")


NB_SEEDS_PER_PARTIAL_CROP_PER_COUNTRY = _load_default_seeds()

# seedlings per ha and crop cycle; asparagus (amortised) and mint: per ha and year
NB_SEEDLINGS_PER_PARTIAL_CROP_PER_COUNTRY = _load_planting_rates("nb_seedlings", _LEGACY_SEEDLINGS)

# trees per ha and year (amortised)
NB_PLANTED_TREES_PER_PARTIAL_CROP_PER_COUNTRY = _load_planting_rates("nb_planted_trees", _LEGACY_TREES)
