"""Decision L68 (issue #53): PM10 and PM2.5 of soil and crop dust from field operations, EMEP/EEA 2023 3.D Tier 2,
Eq. (5) p. 22 and Tables 3-6 to 3-9 p. 23.

Expected values computed by hand from the four tables (kg/ha per pass):
- wheat: soil cultivation PM10 0.25 wet / 2.25 dry, PM2.5 0.015 / 0.12; harvesting PM10 2.7 / 2.45, PM2.5 0.02 / 0.098;
- oats: harvesting PM10 3.4 wet, PM2.5 0.025 wet;
- other arable: soil cultivation as wheat, harvesting NC (0).
ecoinvent flows: pm2_5_field_operations_air = PM2.5, pm2_5_to_10_field_operations_air = PM10 - PM2.5."""
import csv

import pytest

import dataloader
import regression_support as rs
from defaultGeneration import DEFAULTS_VALUES_GENERATORS, DefaultValuesWrapper
from models.pmmodel import (PM10, PM2_5, PM2_5_KEY, PM2_5_TO_10_KEY, PmModel, check_pm2_5_below_pm10,
                            emission_factors, emep_crop, field_operation_pm, operation_mapping)

PLOUGH = "soilcultivation_tillage_plough"
ROTARY_HARROW = "soilcultivation_tillage_rotary_harrow"
CHISEL = "soilcultivation_tillage_chisel"
COMBINE = "harvesting_threshing_combine_harvester"
WHEAT_PASSES = {PLOUGH: 1.0, ROTARY_HARROW: 1.0, COMBINE: 1.0}


# --- tables ---

def test_emission_factor_table_has_the_four_tables():
    rows = dataloader.rows("emep2023_3d_tables3_6_3_9.csv")
    assert len(rows) == 96
    assert {r["table"] for r in rows} == {"Table 3-6", "Table 3-7", "Table 3-8", "Table 3-9"}
    assert {r["page"] for r in rows} == {"23"}


@pytest.mark.parametrize("pollutant, climate, crop, operation, value", [
    ("PM10", "wet", "wheat", "harvesting", 2.7),
    ("PM10", "dry", "oats", "harvesting", 3.10),
    ("PM10", "wet", "barley", "drying", 0.43),
    ("PM2.5", "wet", "oats", "drying", 0.198),
    ("PM2.5", "dry", "wheat", "cleaning", 0.0095),
    ("PM2.5", "dry", "grass", "harvesting", 0.05),
    ("PM10", "dry", "rye", "drying", 0.0),
])
def test_emission_factor_values(pollutant, climate, crop, operation, value):
    assert emission_factors()[(pollutant, climate, crop, operation)] == value


def test_nc_only_for_other_arable_harvesting_cleaning_drying():
    nc = {(r["emep_crop"], r["operation"]) for r in dataloader.rows("emep2023_3d_tables3_6_3_9.csv")
          if r["ef_kg_per_ha_per_pass"] == ""}
    assert nc == {("other arable", op) for op in ("harvesting", "cleaning", "drying")}


def test_pm2_5_not_above_pm10():
    check_pm2_5_below_pm10(emission_factors())


def test_guard_rejects_pm2_5_above_pm10():
    factors = dict(emission_factors())
    factors[(PM2_5, "wet", "wheat", "harvesting")] = 3.0
    with pytest.raises(ValueError, match="PM2.5"):
        check_pm2_5_below_pm10(factors)


def test_crop_mapping_covers_every_crop():
    crops = [row["crop"] for row in dataloader.rows("crop_types.csv")]
    assert emep_crop("wheat") == "wheat" and emep_crop("oat") == "oats"
    assert {emep_crop(c) for c in crops if c not in ("wheat", "oat")} == {"other arable"}


def test_operation_mapping():
    mapping = operation_mapping()
    assert [k for k, v in mapping.items() if v == "harvesting"] == [COMBINE]
    assert len([k for k, v in mapping.items() if v == "soil cultivation"]) == 9
    assert "sowingplanting_sowing" not in mapping and "soilcultivation_other" not in mapping


# --- Eq. (5): expected values of issue #53 ---

@pytest.mark.parametrize("share, pm10, pm2_5", [(0.0, 3.20, 0.050), (1.0, 6.95, 0.338), (0.4, 4.70, 0.1652)])
def test_wheat_plough_harrow_combine(share, pm10, pm2_5):
    pm = field_operation_pm("wheat", WHEAT_PASSES, share)
    assert pm[PM10] == pytest.approx(pm10, abs=1e-9)
    assert pm[PM2_5] == pytest.approx(pm2_5, abs=1e-9)


def test_wheat_flows_are_exclusive_size_classes():
    out = PmModel({"crop": "wheat", "mediterranean_climate_share": 0.4, **WHEAT_PASSES}).compute()
    assert out[PM2_5_KEY] == pytest.approx(0.1652, abs=1e-9)
    assert out[PM2_5_TO_10_KEY] == pytest.approx(4.5348, abs=1e-9)


@pytest.mark.parametrize("share, pm10, pm2_5", [(0.0, 0.50, 0.030), (1.0, 4.50, 0.24)])
def test_other_arable_harvesting_nc(share, pm10, pm2_5):
    pm = field_operation_pm("maizegrain", {PLOUGH: 1.0, CHISEL: 1.0, COMBINE: 1.0}, share)
    assert pm[PM10] == pytest.approx(pm10, abs=1e-9)
    assert pm[PM2_5] == pytest.approx(pm2_5, abs=1e-9)


def test_oat_plough_combine_wet():
    pm = field_operation_pm("oat", {PLOUGH: 1.0, COMBINE: 1.0}, 0.0)
    assert pm[PM10] == pytest.approx(3.65, abs=1e-9)
    assert pm[PM2_5] == pytest.approx(0.040, abs=1e-9)


def test_operations_not_counted_give_zero():
    passes = {"sowingplanting_sowing": 1.0, "plantprotection_spraying": 3.0, "fertilisation_fertilizing_broadcaster": 2.0}
    assert field_operation_pm("wheat", passes, 0.5) == {PM10: 0.0, PM2_5: 0.0}


def test_no_operations_give_zero():
    assert PmModel({"crop": "wheat", "mediterranean_climate_share": 0.5}).compute() == \
        {PM2_5_KEY: 0.0, PM2_5_TO_10_KEY: 0.0}


def test_share_outside_0_1_rejected():
    with pytest.raises(ValueError, match="mediterranean_climate_share"):
        field_operation_pm("wheat", WHEAT_PASSES, 1.2)


def test_unknown_crop_rejected():
    with pytest.raises(KeyError, match="emep2023_pm_crop_mapping"):
        field_operation_pm("barley", WHEAT_PASSES, 0.0)


# --- Mediterranean share (koppen_mediterranean_share.csv) ---

def _share_rows():
    with open(dataloader.data_path("koppen_mediterranean_share.csv"), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_mediterranean_share_values():
    rows = _share_rows()
    assert all(0.0 <= float(r["dry_share"]) <= 1.0 for r in rows)
    by_key = {(r["crop"], r["country"]): r for r in rows}
    assert float(by_key[("wheat", "DE")]["dry_share"]) == 0.0
    assert float(by_key[("wheat", "IT")]["dry_share"]) == 0.49
    assert by_key[("wheat", "IT")]["weights"] == "WHEA"
    countries = {r["country"] for r in rows}
    assert {c for (crop, c) in by_key if crop == "all_crops"} == countries


def _defaults(**inputs):
    return DefaultValuesWrapper(inputs, DEFAULTS_VALUES_GENERATORS)


def test_default_mediterranean_share():
    assert _defaults(crop="wheat", country="IT")["mediterranean_climate_share"] == 0.49
    assert _defaults(crop="wheat", country="DE")["mediterranean_climate_share"] == 0.0
    assert _defaults(crop="wheat", country="IT", mediterranean_climate_share=0.2)["mediterranean_climate_share"] == 0.2


# --- whole model sequence ---

def _run(inputs):
    from modelsSequence import ModelsSequence
    import config
    original = config.master_data_path
    config.master_data_path = lambda: None
    try:
        return ModelsSequence(inputs).executeSequence()
    finally:
        config.master_data_path = original


def test_model_sequence_wheat_it():
    """wheat_IT: 30 kg diesel of ploughing (1/26.1 ha per kg) and 25 kg of combine harvesting (1/33.3 ha per kg) ->
    1.149425 and 0.750751 passes; dry share 0.49: PM10 3.348853, PM2.5 0.120088 kg/ha."""
    out = _run(rs.load_inputs("wheat_IT"))
    assert out[PM2_5_KEY] == pytest.approx(0.120088, abs=1e-6)
    assert out[PM2_5_TO_10_KEY] == pytest.approx(3.348853 - 0.120088, abs=1e-6)


def test_model_sequence_wheat_it_wet_override():
    """Same passes, mediterranean_climate_share 0: PM10 = 0.25 x 30/26.1 + 2.7 x 25/33.3 = 2.314383,
    PM2.5 = 0.015 x 30/26.1 + 0.02 x 25/33.3 = 0.032256."""
    out = _run(dict(rs.load_inputs("wheat_IT"), mediterranean_climate_share=0.0))
    assert out[PM2_5_KEY] == pytest.approx(0.032256, abs=1e-6)
    assert out[PM2_5_TO_10_KEY] == pytest.approx(2.314383 - 0.032256, abs=1e-6)


@pytest.mark.parametrize("case", ["rice_IN", "apple_FR"])
def test_model_sequence_without_counted_operations(case):
    out = _run(rs.load_inputs(case))
    assert out[PM2_5_KEY] == 0.0 and out[PM2_5_TO_10_KEY] == 0.0


# --- legacy diesel intensities (legacy_machinery_diesel_intensity.csv) and the legacy passes ---

def test_diesel_intensity_table():
    from outputMapping import OutputMapping, machinery_diesel_intensity
    from directMappingEnums import Harvesting, Soilcultivation
    intensity = machinery_diesel_intensity()
    assert len(intensity) == 30
    assert intensity[PLOUGH] == (26.1, "ha") and intensity[COMBINE] == (33.3, "ha")
    assert intensity["otherworkprocesses_transport_tractor_trailer"] == (0.0436, "tkm")
    assert all(row["note"] == "legacy, undocumented, provisional"
               for row in dataloader.rows("legacy_machinery_diesel_intensity.csv"))
    assert OutputMapping._SOILCULTIVATION_FACTORS[Soilcultivation.tillage_plough] == 1.0 / 26.1
    assert OutputMapping._HARVESTING_FACTORS[Harvesting.threshing_combine_harvester] == 1.0 / 33.3
    assert OutputMapping._SOILCULTIVATION_FACTORS[Soilcultivation.decompactation] == 45.00450045


def test_legacy_passes_only_operations_in_ha():
    from models.pmmodel import legacy_operations_in_ha
    operations = legacy_operations_in_ha()
    assert len(operations) == 9 and COMBINE in operations
    assert "soilcultivation_decompactation" not in operations


def test_model_sequence_decompactation_gives_no_pm():
    """10 kg diesel of decompactation is written as 450.045 MJ of diesel, not as ha: PM 0 on the legacy path."""
    inputs = dict(rs.load_inputs("wheat_IT"), total_soilcultivation=10.0, ratio_soilcultivation_tillage_plough=0.0,
                  ratio_soilcultivation_decompactation=1.0, total_harvesting=0.0)
    out = _run(inputs)
    assert out["soilcultivation_decompactation"] == pytest.approx(450.0450045)
    assert out[PM2_5_KEY] == 0.0 and out[PM2_5_TO_10_KEY] == 0.0
