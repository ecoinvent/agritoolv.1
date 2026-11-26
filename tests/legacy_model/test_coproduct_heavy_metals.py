"""Decision L75 (template v3 T11): the removed co-products of the input ``coproducts`` export heavy metals.

Export of a removed co-product = fresh mass x Master Data 3.12 dry mass (data/md312_product_properties.csv, L74)
x concentration (mg/kg DM) of the SALCAheavymetal 2023 Table 1 row of data/hm_coproduct_product_mapping.csv.
Co-products left on field export nothing.

Expected values computed by hand: Master Data 3.12 dry mass straw 0.85, coconut husk 1, biowaste 0.4, waste wood,
untreated 0.8, linseed 0.909090909091; Table 1 Zn (mg/kg DM) wheat straw 9.6, co-product, mean 20.6, green waste
shredding 71, wood chips 107, main product, mean 29.1; Cd wheat straw 0.2; Hg co-product, mean 0.15; Pb green
waste shredding 20.
"""
import pytest

import dataloader
from defaultGeneration import HeavyMetalExportWithHarvestGenerator
from models.modelEnums import HeavyMetalType

BASE = {"yield_BP1_per_crop_cycle": "", "yield_BP2_per_crop_cycle": "", "yield_BP3_per_crop_cycle": "",
        "yield_main_product_dry_per_crop_cycle": 0.0}


def export(crop, *coproducts):
    items = [{"product": p, "amount": 1000.0, "fate": f} for p, f in coproducts]
    return HeavyMetalExportWithHarvestGenerator().generateDefault("", dict(BASE, crop=crop, coproducts=items))


def test_no_coproducts_no_export():
    assert all(v == 0.0 for v in export("wheat").values())


def test_wheat_straw_takes_the_straw_row_of_wheat():
    out = export("wheat", ("straw", "removed"))
    assert out[HeavyMetalType.zn] == pytest.approx(1000 * 0.85 * 9.6)
    assert out[HeavyMetalType.cd] == pytest.approx(1000 * 0.85 * 0.2)


def test_straw_of_another_crop_takes_the_coproduct_mean():
    assert export("apple", ("straw", "removed"))[HeavyMetalType.zn] == pytest.approx(1000 * 0.85 * 20.6)


def test_straw_left_on_field_exports_nothing():
    assert all(v == 0.0 for v in export("wheat", ("straw", "left on field")).values())


@pytest.mark.parametrize("product, metal, expected", [
    ("coconut husk", HeavyMetalType.zn, 1000 * 1.0 * 20.6),
    ("coconut husk", HeavyMetalType.hg, 1000 * 1.0 * 0.15),
    ("biowaste", HeavyMetalType.zn, 1000 * 0.4 * 71),
    ("biowaste", HeavyMetalType.pb, 1000 * 0.4 * 20),
    ("waste wood, untreated", HeavyMetalType.zn, 1000 * 0.8 * 107),
    ("linseed", HeavyMetalType.zn, 1000 * 0.909090909091 * 29.1),
])
def test_other_coproducts(product, metal, expected):
    assert export("coconut", (product, "removed"))[metal] == pytest.approx(expected, rel=1e-9)


def test_burned_is_an_error():
    with pytest.raises(ValueError):
        export("wheat", ("straw", "burned"))


def test_every_coproduct_of_the_list_has_a_row_for_any_crop():
    products = {r["md312_product"] for r in dataloader.rows("coproduct_list.csv") if r["md312_product"]}
    for product in products:
        dataloader.hm_entry(dataloader.hm_coproduct_product(product, "any"))
