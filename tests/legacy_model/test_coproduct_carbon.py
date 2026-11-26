"""Decision L74 (template v3 T23, walkthrough B6): CO2 uptake from the Master Data 3.12 carbon of the products.

CO2_from_yield = sum over the main product and the removed co-products of fresh mass x dry mass x carbon content,
non-fossil x 44/12, with the properties of data/md312_product_properties.csv (generated from the Master Data 3.12
by scripts/check_master_data.py). Co-products left on field count 0. The gross energy stays on the main product.

Expected values computed by hand from the Master Data 3.12 values (sheet 'IntermediateExchanges prop.'):
wheat grain dry mass 0.85, carbon 0.4646009; straw dry mass 0.85, carbon 0.4373767; coconut husk dry mass 1,
carbon 0.52; apple dry mass 0.15, carbon 0.44; and M(CO2) / M(C) = 44.0095 / 12.0107 (atomic masses
C 12.0107, O 15.9994 of models/atomicmass.py).
"""
import csv

import pytest

import dataloader
from defaultGeneration import DEFAULTS_VALUES_GENERATORS, DefaultValuesWrapper, coproduct_carbon_dioxide
from defaultTables import CARBON_CONTENT_PER_CROP, WATER_CONTENT_FM_RATIO_PER_CROP
from models.atomicmass import MA_C, MA_CO2

CO2_PER_C = 44.0095 / 12.0107


def generators(**inputs):
    return DefaultValuesWrapper(inputs, DEFAULTS_VALUES_GENERATORS)


def test_ratio_of_the_atomic_masses():
    assert MA_CO2 / MA_C == pytest.approx(CO2_PER_C, rel=1e-12)


def test_wheat_grain_properties_from_the_master_data():
    assert dataloader.crop_main_product("wheat") == "wheat grain"
    g = generators(crop="wheat")
    assert g["yield_main_product_carbon_content"] == pytest.approx(0.4646009, abs=1e-7)
    assert g["yield_main_product_dry_content"] == pytest.approx(0.85, abs=1e-12)


def test_removed_straw_adds_its_carbon():
    straw = {"product": "straw", "amount": 1000.0, "fate": "removed"}
    assert coproduct_carbon_dioxide(straw) == pytest.approx(1000 * 0.85 * 0.4373767 * CO2_PER_C, rel=1e-6)
    assert coproduct_carbon_dioxide(straw) == pytest.approx(1362.24, abs=0.01)


def test_straw_left_on_field_adds_nothing():
    assert coproduct_carbon_dioxide({"product": "straw", "amount": 1000.0, "fate": "left on field"}) == 0.0


def test_removed_coconut_husk_adds_its_carbon():
    husk = {"product": "coconut husk", "amount": 1000.0, "fate": "removed"}
    assert coproduct_carbon_dioxide(husk) == pytest.approx(1000 * 1.0 * 0.52 * CO2_PER_C, rel=1e-9)
    assert coproduct_carbon_dioxide(husk) == pytest.approx(1905.38, abs=0.01)


def test_burned_or_unknown_fate_is_an_error():
    with pytest.raises(ValueError):
        coproduct_carbon_dioxide({"product": "straw", "amount": 1000.0, "fate": "burned"})
    with pytest.raises(ValueError):
        coproduct_carbon_dioxide({"product": "straw", "amount": 1000.0, "fate": "sold"})


def test_product_not_in_the_properties_table_is_an_error():
    with pytest.raises(KeyError):
        coproduct_carbon_dioxide({"product": "cereal straw, free text", "amount": 1000.0, "fate": "removed"})


def test_co2_from_yield_is_main_product_plus_removed_coproducts():
    coproducts = [{"product": "straw", "amount": 1000.0, "fate": "removed"},
                  {"product": "straw", "amount": 2000.0, "fate": "left on field"},
                  {"product": "coconut husk", "amount": 1000.0, "fate": "removed"}]
    g = generators(crop="wheat", yield_main_product_per_crop_cycle=6000.0, coproducts=coproducts)
    main = 6000 * 0.85 * 0.464600933621769 * CO2_PER_C
    assert g["CO2_from_main_product"] == pytest.approx(main, rel=1e-9)
    assert g["CO2_from_yield"] == pytest.approx(main + 1362.2370 + 1905.3794, rel=1e-6)


def test_no_coproducts_by_default_and_legacy_by_product_fields_give_no_carbon():
    g = generators(crop="wheat", yield_main_product_per_crop_cycle=6000.0, yield_BP1_per_crop_cycle=5000.0)
    assert g["coproducts"] == []
    assert g["CO2_from_yield"] == pytest.approx(6000 * 0.85 * 0.464600933621769 * CO2_PER_C, rel=1e-9)


def test_gross_energy_proxy_uses_the_main_product_only():
    # apple has no GCV in ENERGY_GROSS_CALORIFIC_VALUE_PER_CROP_PARTIAL: legacy proxy 11.5 x CO2 of the main product
    g = generators(crop="apple", yield_main_product_per_crop_cycle=10000.0,
                   coproducts=[{"product": "straw", "amount": 1000.0, "fate": "removed"}])
    main = 10000 * 0.15 * 0.44 * CO2_PER_C
    assert main == pytest.approx(2418.366, abs=1e-3)
    assert g["energy_gross_calorific_value"] == pytest.approx(main * 11.5, rel=1e-9)
    assert g["CO2_from_yield"] == pytest.approx(main + 1362.2370, rel=1e-6)


def test_crop_without_master_data_product_keeps_the_legacy_tables():
    rows = {r["crop"]: r for r in dataloader.rows("crop_main_product.csv")}
    for crop, row in rows.items():
        if row["md312_product"]:
            continue
        assert row["status"] in ("missing", "decision"), crop
        g = generators(crop=crop)
        assert g["yield_main_product_dry_content"] == 1 - WATER_CONTENT_FM_RATIO_PER_CROP[crop]
        assert g["yield_main_product_carbon_content"] == CARBON_CONTENT_PER_CROP[crop]


def test_every_crop_has_a_row_and_every_named_product_has_properties():
    with open(dataloader.DATA_DIR / "crop_types.csv", newline="", encoding="utf-8") as f:
        crops = [r["crop"] for r in csv.DictReader(f)]
    rows = dataloader.rows("crop_main_product.csv")
    assert [r["crop"] for r in rows] == crops
    named = {r["md312_product"] for table in ("crop_main_product.csv", "coproduct_list.csv")
             for r in dataloader.rows(table) if r["md312_product"]}
    properties = dataloader.table("md312_product_properties.csv")
    assert named == set(properties)
    for product, p in properties.items():
        assert p["unit"] == "kg", product
        assert 0 < p["dry_mass_kg_per_kg"] <= 1, product
        assert 0 < p["carbon_content_non_fossil_kg_per_kg_dm"] < 1, product
        assert p["by_product_classification"] in ("allocatable product", "Recyclable", "Waste"), product
