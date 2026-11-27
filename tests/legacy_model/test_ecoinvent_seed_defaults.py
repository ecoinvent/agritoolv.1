"""Decision L79: default seed of carrot, sugar beet, sweet corn, flax, hemp and coriander from the ecoinvent 3.12 datasets
(data/ecoinvent312_seed_rates.csv, built by scripts/build_ecoinvent_seed_rates.py; activities and seed exchanges in
data/seed_rate_crop_mapping.csv); the 11 crops without source take the legacy value or 0 with a warning; a crop in no
table raises KeyError instead of a silent 0."""
import importlib.util
import os
import statistics
import warnings
from pathlib import Path

import pytest

import dataloader
from defaultGeneration import DefaultValuesWrapper, DEFAULTS_VALUES_GENERATORS

ROOT = Path(__file__).resolve().parents[2]
MAPPING = {row["crop"]: row for row in dataloader.rows("seed_rate_crop_mapping.csv")}
RATES = dataloader.rows("ecoinvent312_seed_rates.csv")
ECOINVENT_CROPS = {"carrot", "sugarbeet", "sweetcorn", "flax", "hemp", "coriander"}


def _build_module():
    spec = importlib.util.spec_from_file_location("build", ROOT / "scripts" / "build_ecoinvent_seed_rates.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _defaults(crop, country):
    return DefaultValuesWrapper({"crop": crop, "country": country}, DEFAULTS_VALUES_GENERATORS)


def _seed(crop, country):
    defaults = _defaults(crop, country)
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # the sourced crops give no warning
        value = defaults["seed_quantities"]
    assert set(value) == {crop}
    return value[crop]


def test_mapping_lists_the_six_ecoinvent_crops_and_their_datasets():
    assert {crop for crop, row in MAPPING.items() if row["use"] == "ecoinvent"} == ECOINVENT_CROPS
    activities = {row["activity_name"] for row in RATES}
    for crop in ECOINVENT_CROPS:
        for activity in MAPPING[crop]["ecoinvent_activities"].split("|"):
            assert activity in activities, (crop, activity)
    assert "flax production" not in activities  # fresh flax plant IN, RoW (60 kg/ha): rejected
    assert {crop for crop, row in MAPPING.items() if row["use"] == "legacy"} == {"cassava", "guar", "turmeric"}


@pytest.mark.parametrize("crop, country, expected", [
    ("carrot", "GLO", 4.2), ("carrot", "NL", 4.2), ("carrot", "CH", (1.6 + 1.2) / 2),
    ("sugarbeet", "GLO", 2.1), ("sugarbeet", "DE", 3.0), ("sugarbeet", "FR", 2.0), ("sugarbeet", "CH", 2.1),
    ("sugarbeet", "US", 2.1),
    ("sweetcorn", "GLO", 21.8), ("sweetcorn", "HU", 15.0), ("sweetcorn", "TH", 16.0),
    ("sweetcorn", "US", statistics.mean((9.5, 11.08, 12.27, 12.27, 12.27, 9.68))),
    ("flax", "GLO", 115.0), ("hemp", "GLO", 47.26), ("hemp", "FR", 47.26), ("coriander", "GLO", 45.0),
])
def test_default_seed_of_the_ecoinvent_datasets(crop, country, expected):
    assert _seed(crop, country) == pytest.approx(expected, rel=1e-2)


@pytest.mark.parametrize("crop, country, glo", [
    ("carrot", "IT", 4.2), ("sugarbeet", "PL", 2.1), ("sweetcorn", "MX", 21.8), ("flax", "FR", 115.0),
    ("hemp", "IT", 47.26), ("coriander", "MA", 45.0),
])
def test_country_without_dataset_takes_glo(crop, country, glo):
    assert _seed(crop, country) == pytest.approx(glo, rel=1e-2)


def test_regions_and_variants_are_averaged_and_rer_is_not_a_country():
    us = [float(row["seed_kg_per_ha_and_crop_cycle"]) for row in RATES
          if row["activity_name"] == "sweet corn production" and row["geography"].startswith("US-")]
    assert len(us) == 6 and _seed("sweetcorn", "US") == pytest.approx(statistics.mean(us))
    from defaultMatrixSeed import NB_SEEDS_PER_PARTIAL_CROP_PER_COUNTRY as seeds
    assert set(seeds["flax"]) == {"GLO"} and set(seeds["hemp"]) == {"FR", "GLO"}
    assert "RoW" not in seeds["carrot"] and "IL" in seeds["carrot"]


def test_only_the_seed_of_the_crop_is_counted():
    # Swiss datasets also sow grass seed after the crop; US sweet corn has 'planting, by row crop planter' (ha)
    for row in RATES:
        exchanges = set(row["seed_exchange"].split("|"))
        crop = next(c for c in ECOINVENT_CROPS if row["activity_name"] in MAPPING[c]["ecoinvent_activities"].split("|"))
        assert exchanges <= set(MAPPING[crop]["ecoinvent_seed_exchanges"].split("|")), row
        assert not any("grass" in name or "planting" in name for name in exchanges)


@pytest.mark.parametrize("crop, field, expected", [
    ("blueberry", "nb_planted_trees", 0.0), ("cranberry", "nb_planted_trees", 0.0),
    ("pineapple", "nb_planted_trees", 0.0), ("sugarcane", "nb_planted_trees", 0.0),
    ("raspberry", "nb_seedlings", 0.0), ("chilli", "nb_seedlings", 0.0), ("eggplant", "nb_seedlings", 0.0),
    ("ginger", "nb_seedlings", 0.0),
    ("cassava", "seeds", 0.0), ("guar", "seeds", 0.0), ("turmeric", "seeds", 100.0),
])
def test_crops_without_source_take_the_legacy_value_with_one_warning(crop, field, expected):
    defaults = _defaults(crop, "FR")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert defaults["seed_quantities"] == {crop: expected}
    assert len(caught) == 1
    message = str(caught[0].message)
    assert message.startswith("Crop '%s': default %s = %g " % (crop, field, expected))
    assert "legacy, undocumented, provisional" in message
    fruit_tree = crop in ("blueberry", "cranberry", "pineapple", "raspberry")
    assert ("no planting input although the exchange 'fruit tree seedling, for planting' exists" in message) \
        == fruit_tree


def test_template_value_gives_no_warning():
    defaults = DefaultValuesWrapper({"crop": "blueberry", "country": "US", "nb_planted_trees": 2000.0},
                                    DEFAULTS_VALUES_GENERATORS)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert defaults["seed_quantities"] == {"blueberry": 2000.0}


def test_crop_in_no_table_raises_key_error():
    with pytest.raises(KeyError, match="seeds: no default for crop 'unknown_crop'"):
        _defaults("unknown_crop", "FR")["seed_quantities"]
    # a tree crop has no seed default in kg: no silent 0
    with pytest.raises(KeyError, match="seeds: no default for crop 'apple'"):
        _defaults("apple", "FR")["seeds"]


@pytest.mark.skipif(not os.environ.get("AGRITOOL_SLOW_TESTS"), reason="about 60 s; set AGRITOOL_SLOW_TESTS=1")
def test_seed_table_equals_the_ecoinvent_exchanges():
    build = _build_module()
    source = dataloader.EXTERNAL_DATA_DIR / build.EXCHANGES_FILE
    if not source.is_file():
        pytest.skip("ecoinvent 3.12 exchanges file not in data/external_data/")
    rebuilt, _ = build.build(source)
    assert [{key: str(value) for key, value in row.items()} for row in rebuilt] == [dict(row) for row in RATES]
