"""Decision L78 (walkthrough A8): the copper of copper fungicides reaches the flow 'Copper' (soil, agricultural) once.

The SALCAheavymetal 2023 balance (L10, L14) already counts the field share of the pesticide metal input,
(1 - f_air - f_OFS) x m = (f_soil + f_crop) x m, so OLCA-Pest (L65) no longer writes that share to agricultural soil
for the active ingredients flagged `field_share_in_hm_balance` = yes in data/hm_pesticide_mapping.csv (copper_cu only).
OLCA-Pest keeps air, off-field water, off-field forestry and the off-field agricultural soil f_off_field x agri x m.

Expected values computed independently from OLCA-Pest scenario SC25 (Fruit trees temperate / Fun):
f_air 0.08, f_soil 0.265964823, f_crop 0.620584586, f_off_field 0.033450591."""
import pytest

import dataloader
from models.hmmodel import HmModel
from models.olcapestmodel import OlcaPestModel, land_shares, scenario

SC25 = {"f_air": 0.08, "f_soil": 0.265964823, "f_crop": 0.620584586, "f_off_field": 0.033450591}
FIELD = SC25["f_soil"] + SC25["f_crop"]


def _apple_fr(**grams):
    pesticides = {"part_fungicides_" + name: value for name, value in grams.items()}
    return OlcaPestModel({"specified_pesticides": pesticides, "crop": "apple", "country": "FR"}).compute()


def test_apple_scenario_is_sc25():
    fractions = scenario("apple", "Fun")
    assert fractions["scenario_id"] == "SC25"
    assert {k: fractions[k] for k in SC25} == pytest.approx(SC25, abs=1e-12)


def test_copper_field_share_is_not_written_to_agricultural_soil():
    out = _apple_fr(copper_cu=3000.0)["pesti_fungicides_copper_cu"]
    # 2.7204537 (before L78) - (f_soil + f_crop) x 3 = 2.7204537 - 2.6596482
    assert out["soil_agricultural"] == pytest.approx(0.0608055, abs=1e-7)
    assert out["soil_agricultural"] == pytest.approx(SC25["f_off_field"] * land_shares("FR")["agri"] * 3.0, rel=1e-9)
    assert out["air"] == pytest.approx(0.24, abs=1e-12)
    assert out["water_surface"] == pytest.approx(0.0016946, abs=1e-7)
    assert out["soil_forestry"] == pytest.approx(0.0378517, abs=1e-7)


def test_mancozeb_keeps_its_field_share_on_agricultural_soil():
    out = _apple_fr(mancozeb=1000.0)["pesti_fungicides_mancozeb"]
    expected = (FIELD + SC25["f_off_field"] * land_shares("FR")["agri"]) * 1.0
    assert out["soil_agricultural"] == pytest.approx(expected, rel=1e-9)


def test_copper_mass_balance_between_olca_pest_and_the_heavy_metal_balance():
    out = _apple_fr(copper_cu=3000.0)["pesti_fungicides_copper_cu"]
    model = HmModel.__new__(HmModel)
    model.crop = "apple"
    hm_field_input = model._pesticide_field_fraction("Fun") * 3.0  # kg a.i. counted by the HM balance (L14)
    assert hm_field_input == pytest.approx(2.6596482, abs=1e-7)
    assert sum(out.values()) + hm_field_input == pytest.approx(3.0, abs=1e-8)


def test_only_copper_is_flagged_as_counted_in_the_heavy_metal_balance():
    rows = dataloader.rows("hm_pesticide_mapping.csv")
    assert {row["field_share_in_hm_balance"] for row in rows} == {"yes", "no"}
    assert [row["legacy_pesticide"] for row in rows if row["field_share_in_hm_balance"] == "yes"] == ["copper_cu"]
