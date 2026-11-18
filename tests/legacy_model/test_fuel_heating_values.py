"""Decision L69 (issue #55): fuel factors of outputMapping.py from data/fuel_heating_values.csv.

Factor (MJ of the written exchange per template unit) = input_per_template_unit / fuel input of the background dataset
(ecoinvent 3.12, 'exchanges (3.12, undef).xlsx') per MJ it produces, so the fuel declared in the template equals the
fuel burned in the background dataset. Only the derived factor is stored (L50); the slow test recomputes the input
as input_per_template_unit / factor and compares it with the release file.

Expected values computed by hand (conversion x LHV x efficiency of the dataset comments; L50: no exchange amounts):
- diesel, the dataset input is the inverse of 45 MJ/kg to 12 decimals: 10 kg -> 450.00000000045 MJ (legacy 450.045);
- petrol 45.3 MJ/kg: 10 kg -> 453.0 MJ (legacy 453.001);
- lignite briquettes 19.5 MJ/kg x efficiency 0.70: 10 kg -> 136.5 MJ heat (legacy 90.09);
- plough 26.1 kg/ha and combine harvester 33.3 kg/ha (L68) unchanged.
"""
import os
import re
from pathlib import Path

import pytest

import config
import dataloader
import outputMapping
from directMappingEnums import (Fertilisation, Harvesting, OtherWorkProcesses, Plantprotection, Soilcultivation,
                                Sowingplanting)
from outputMapping import OutputMapping

DIESEL_ITEMS = ["remains_machinery_diesel", "energy_diesel_excluding_diesel_used_in_tractor", "plantprotection_other",
                "soilcultivation_decompactation", "soilcultivation_other", "sowingplanting_other",
                "fertilisation_other", "harvesting_other", "otherworkprocesses_other"]
ENERGY_ITEMS = ["energy_natural_gas", "energy_fuel_oil_light", "energy_fuel_oil_heavy", "energy_lignite_briquette",
                "energy_hard_coal_briquette", "energy_wood_pellets_humidity_10_percent",
                "energy_wood_chips_fresh_humidity_40_percent", "energy_wood_logs"]
ITEMS = DIESEL_ITEMS + ["total_machinery_gazoline", "plantprotection_flaming"] + ENERGY_ITEMS
OUTPUT_MAPPING_FILE = Path(outputMapping.__file__)


def _rows():
    return {row["item"]: row for row in dataloader.rows(dataloader.FUEL_TABLE)}


def _input_per_mj(row):
    """Fuel input of the background dataset per MJ it produces, recomputed from the stored factor."""
    return float(row["input_per_template_unit"]) / float(row["factor_MJ_per_template_unit"])


def _background_amount(item, written):
    """Fuel burned in the background dataset (its input unit) for an amount written in MJ."""
    return written * _input_per_mj(_rows()[item])


def _template_units(item, written):
    """Template units (kg, Nm3) that correspond to an amount written in MJ: the mass balance."""
    return _background_amount(item, written) / float(_rows()[item]["input_per_template_unit"])


# --- table ---

def test_table_has_one_row_per_fuel_item():
    rows = dataloader.rows(dataloader.FUEL_TABLE)
    assert [row["item"] for row in rows] == ITEMS
    assert "input_amount" not in rows[0]  # L50: no ecoinvent amounts in the repository
    for row in rows:
        assert float(row["factor_MJ_per_template_unit"]) > 0.0, row["item"]
        assert float(row["input_per_template_unit"]) > 0.0, row["item"]
        assert row["source"].strip(), row["item"]
        assert row["source"].startswith("exchanges (3.12, undef).xlsx, " + row["dataset_name"] + " GLO"), row["item"]
        assert row["dataset_geography"] == "GLO" and row["note"], row["item"]
        assert "legacy, undocumented, provisional" not in row["note"], row["item"]
        assert dataloader.fuel_factor(row["item"]) == float(row["factor_MJ_per_template_unit"]), row["item"]


def test_units_and_exchanges():
    rows = _rows()
    assert {rows[i]["input_unit_of_template"] for i in ITEMS if i != "energy_natural_gas"} == {"kg"}
    assert rows["energy_natural_gas"]["input_unit_of_template"] == "Nm3"
    assert rows["energy_natural_gas"]["input_unit"] == "m3/MJ"
    assert {rows[i]["input_unit"] for i in ("energy_lignite_briquette", "energy_hard_coal_briquette")} == {"MJ/MJ"}
    assert {rows[i]["exchange_written"] for i in DIESEL_ITEMS} == {"diesel, burned in agricultural machinery"}
    assert rows["plantprotection_flaming"]["exchange_written"] == "heat, district or industrial, other than natural gas"
    assert rows["plantprotection_flaming"]["fuel"] == "propane"


def test_exchange_alignment_of_flaming_is_the_propane_heat():
    alignment = {r["model_variable"]: r for r in dataloader.rows("intermediate_exchange_alignment.csv")}
    rows = _rows()
    assert alignment["plantprotection_flaming"]["md312_name"] == rows["plantprotection_flaming"]["exchange_written"]
    assert alignment["plantprotection_flaming"]["status"] == "confirmed"
    assert alignment["plantprotection_flaming"]["reviewed_by"] == "FC 2026-11-18"
    for item in ITEMS:
        assert alignment[item]["md312_unit"] == "MJ", item
        if item != "plantprotection_flaming":
            assert alignment[item]["md312_name"] == rows[item]["exchange_written"], item


def test_unknown_item_names_the_item():
    with pytest.raises(KeyError, match="no_such_fuel"):
        dataloader.fuel_factor("no_such_fuel")


# --- mass consistency: the declared fuel is the fuel burned in the background dataset ---

def _machinery_output(quantities, remains=None):
    inputs = {"plantprotection_quantities": {}, "soilcultivation_quantities": {}, "sowingplanting_quantities": {},
              "fertilisation_quantities": {}, "harvesting_quantities": {}, "otherworkprocesses_quantities": {}}
    inputs.update(quantities)
    if remains is not None:
        inputs["remains_machinery_diesel"] = remains
    mapping = OutputMapping()
    mapping.mapMachineries(inputs)
    return mapping.output


MACHINERY_FUEL_OPERATIONS = {
    "plantprotection_quantities": [Plantprotection.other, Plantprotection.flaming],
    "soilcultivation_quantities": [Soilcultivation.other, Soilcultivation.decompactation],
    "sowingplanting_quantities": [Sowingplanting.other],
    "fertilisation_quantities": [Fertilisation.other],
    "harvesting_quantities": [Harvesting.other],
    "otherworkprocesses_quantities": [OtherWorkProcesses.other],
}


def test_machinery_fuel_operations_are_mass_consistent():
    out = _machinery_output({group: {op: 10.0 for op in ops} for group, ops in MACHINERY_FUEL_OPERATIONS.items()},
                            remains=25.0)
    for ops in MACHINERY_FUEL_OPERATIONS.values():
        for op in ops:
            assert _template_units(op.value, out[op.value]) == pytest.approx(10.0, rel=1e-9), op.value
    assert _template_units("remains_machinery_diesel", out["remains_machinery_diesel"]) == pytest.approx(25.0, rel=1e-9)
    # flaming: 10 kg declared = 10 kg propane in 'heat production, propane, at industrial furnace >100kW'
    assert _background_amount("plantprotection_flaming", out["plantprotection_flaming"]) == pytest.approx(10.0, rel=1e-9)


@pytest.mark.parametrize("item", ["energy_diesel_excluding_diesel_used_in_tractor", "total_machinery_gazoline"]
                         + ENERGY_ITEMS)
def test_direct_fuel_items_are_mass_consistent(item):
    written = OutputMapping._DIRECT_OUTPUT_MAPPING[item](10.0)
    assert _template_units(item, written) == pytest.approx(10.0, rel=1e-9)


@pytest.mark.parametrize("item, dry_kg", [
    ("energy_wood_pellets_humidity_10_percent", 10.0 / 1.1),
    ("energy_wood_chips_fresh_humidity_40_percent", 6.0),
    ("energy_wood_logs", 10.0 / 1.3),
])
def test_wood_moisture(item, dry_kg):
    """10 kg of wood in the template = kg dry mass in the heat dataset (input measured as dry mass)."""
    written = OutputMapping._DIRECT_OUTPUT_MAPPING[item](10.0)
    assert _background_amount(item, written) == pytest.approx(dry_kg, rel=1e-9)


# --- hand values ---

def test_hand_values():
    out = _machinery_output({"soilcultivation_quantities": {Soilcultivation.other: 10.0}})
    assert out["soilcultivation_other"] == pytest.approx(450.00000000045, rel=1e-12)
    assert OutputMapping._DIRECT_OUTPUT_MAPPING["total_machinery_gazoline"](10.0) == pytest.approx(453.0, rel=1e-9)
    assert OutputMapping._DIRECT_OUTPUT_MAPPING["energy_lignite_briquette"](10.0) == pytest.approx(136.5, rel=1e-9)
    assert OutputMapping._DIRECT_OUTPUT_MAPPING["energy_natural_gas"](1.0) == pytest.approx(36.0 / 0.98, rel=1e-9)
    assert OutputMapping._DIRECT_OUTPUT_MAPPING["energy_hard_coal_briquette"](10.0) == pytest.approx(314.0 / 1.43,
                                                                                                      rel=1e-9)


def test_intensity_operations_unchanged():
    """Operations with a diesel intensity (L68) keep 1 / intensity: 26.1 kg -> 1 ha ploughing, 33.3 kg -> 1 ha combine."""
    out = _machinery_output({"soilcultivation_quantities": {Soilcultivation.tillage_plough: 26.1},
                             "harvesting_quantities": {Harvesting.threshing_combine_harvester: 33.3}})
    assert out["soilcultivation_tillage_plough"] == pytest.approx(1.0)
    assert out["harvesting_threshing_combine_harvester"] == pytest.approx(1.0)
    assert OutputMapping._SOILCULTIVATION_FACTORS[Soilcultivation.tillage_plough] == 1.0 / 26.1
    assert OutputMapping._HARVESTING_FACTORS[Harvesting.threshing_combine_harvester] == 1.0 / 33.3


def test_machinery_fuel_factors_cover_the_operations_without_intensity():
    assert {op.value for op in OutputMapping._MACHINERY_FUEL_ENERGY_FACTORS} == set(DIESEL_ITEMS[2:]) | {
        "plantprotection_flaming"}


LEGACY_LITERALS = ["45.00450045", "0.0222", "0.022075", "46.35", "0.111", "0.0318", "0.02342", "0.025", "0.0272",
                   "0.0587", "0.0545", "0.0643"]


def test_no_legacy_fuel_literal_left_in_output_mapping():
    source = OUTPUT_MAPPING_FILE.read_text(encoding="utf-8")
    found = [lit for lit in LEGACY_LITERALS if re.search(r"(?<![\d.])%s(?!\d)" % re.escape(lit), source)]
    assert found == []


# --- sources ---

def test_briquette_and_wood_conversions_match_the_master_data():
    path = config.master_data_path()
    if path is None or not path.is_file():
        pytest.skip("ecoinvent Master Data not configured")
    props = dataloader.load_intermediate_exchange_properties(str(path))
    rows = _rows()
    for item, product in (("energy_lignite_briquette", "lignite briquettes"),
                          ("energy_hard_coal_briquette", "hard coal briquettes")):
        assert float(rows[item]["input_per_template_unit"]) == pytest.approx(1.0 / props[(product, "wet mass")],
                                                                               rel=1e-9)
    assert props[("lignite briquettes", "heating value, net")] == 19.5
    for item, product in (("energy_wood_pellets_humidity_10_percent", "wood pellets, dry, measured as dry mass"),
                          ("energy_wood_logs", "cleft timber, green, measured as dry mass")):
        assert float(rows[item]["input_per_template_unit"]) == pytest.approx(1.0 / props[(product, "wet mass")],
                                                                               rel=1e-9)
    # the rejected Master Data net heating values (L69): 10 kg diesel declared would burn 9.51 kg in the background
    assert props[("diesel", "heating value, net")] == 42.8
    assert props[("petrol, unleaded", "heating value, net")] == 43.2
    assert 10.0 * 42.8 * _input_per_mj(rows["remains_machinery_diesel"]) == pytest.approx(9.511, abs=1e-3)


EXCHANGES_FILE = dataloader.EXTERNAL_DATA_DIR / "exchanges (3.12, undef).xlsx"


@pytest.mark.skipif(not os.environ.get("AGRITOOL_SLOW_TESTS"), reason="about 50 s; set AGRITOOL_SLOW_TESTS=1")
def test_input_amounts_equal_the_ecoinvent_datasets():
    """input_per_template_unit / factor = fuel input of the dataset in the release file (rel 1e-9)."""
    if not EXCHANGES_FILE.is_file():
        pytest.skip("exchanges (3.12, undef).xlsx not available")
    import openpyxl
    rows = _rows()
    wanted = {(r["dataset_name"], r["dataset_geography"]) for r in rows.values()}
    found = {}
    sheet_rows = openpyxl.load_workbook(EXCHANGES_FILE, read_only=True)["exchanges"].iter_rows(values_only=True)
    index = {name: i for i, name in enumerate(next(sheet_rows))}
    for r in sheet_rows:
        key = (r[index["activityName"]], r[index["geography"]])
        if key in wanted and r[index["group"]] in ("FromTechnosphere", "ReferenceProduct"):
            found.setdefault(key, {})[(r[index["group"]], r[index["exchange name"]])] = (
                r[index["exchange amount"]], r[index["exchange unitName"]])
    for item, row in rows.items():
        exchanges = found[(row["dataset_name"], row["dataset_geography"])]
        amount, unit = exchanges[("FromTechnosphere", row["input_exchange"])]
        assert amount == pytest.approx(_input_per_mj(row), rel=1e-9), item
        assert row["input_unit"] == unit + "/MJ", item
        assert exchanges[("ReferenceProduct", row["exchange_written"])] == (pytest.approx(1.0), "MJ"), item
