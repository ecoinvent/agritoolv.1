"""Decisions L71 (template v3 T19) and L72 (template v3 T20).

L71: dolomite and the Mg fertiliser are two independent inputs. `magnesium_from_fertilizer` is the kg Mg/ha of the
fertilisers other than dolomite, written as magnesium sulfate; `dolomite_applied` (kg product/ha) is written as it
is, with nothing subtracted. The heavy metals of the dolomite enter the SALCAheavymetal 2023 Table 1 row
"Mg magnesium" with its stoichiometric Mg, M(Mg) / M(CaMg(CO3)2).

L72: quicklime (CaO) and hydrated lime (Ca(OH)2), kg product/ha: no CO2 (no carbonate), heavy metals with their
stoichiometric Ca on the row "Ca limestone", exchanges with the Master Data 3.12 products.

Expected values computed by hand with the atomic masses of models/atomicmass.py (H 1.00794, C 12.0107,
O 15.9994, Mg 24.3050, S 32.066, Ca 40.078; CaMg(CO3)2 184.4008, MgSO4 120.3686, CaO 56.0774, Ca(OH)2 74.09268).
"""
import warnings

import pytest

import config
import regression_support as rs
from defaultGeneration import DEFAULTS_VALUES_GENERATORS
from models.co2model import Co2Model
from models.fertilisermodel import (CaFertiliserType, FertModel, KFertiliserType, NFertiliserType,
                                    PFertiliserType, ZnFertiliserType)
from models.modelEnums import HeavyMetalType
from outputMapping import magnesium_fertiliser_split

NEW_INPUTS = ("dolomite_applied", "quicklime_applied", "hydrated_lime_applied")


def _fert_model(magnesium=0.0, ca=None, **products):
    ca_quantities = dict.fromkeys(CaFertiliserType, 0.0)
    ca_quantities.update(ca or {})
    inputs = {
        "n_fertiliser_quantities": dict.fromkeys(NFertiliserType, 0.0),
        "p_fertiliser_quantities": dict.fromkeys(PFertiliserType, 0.0),
        "k_fertiliser_quantities": dict.fromkeys(KFertiliserType, 0.0),
        "ca_fertiliser_quantities": ca_quantities,
        "zn_fertiliser_quantities": dict.fromkeys(ZnFertiliserType, 0.0),
        "magnesium_from_fertilizer": magnesium,
        "soil_with_ph_under_or_7": 1.0,
        "cultivation_type": "open_ground",
        "crop": "wheat",
    }
    inputs.update(dict.fromkeys(NEW_INPUTS, 0.0))
    inputs.update(products)
    return FertModel(inputs)


def _assert_same_metals(actual, expected):
    assert any(v > 0.0 for v in expected.values())
    for element in HeavyMetalType:
        assert actual[element] == pytest.approx(expected[element], rel=1e-5), element


def _sequence(**extra):
    base_inputs = rs.load_inputs("wheat_IT")
    from modelsSequence import ModelsSequence
    original = config.master_data_path
    config.master_data_path = lambda: None
    try:
        base = ModelsSequence(dict(base_inputs)).executeSequence()
        out = ModelsSequence(dict(base_inputs, **extra)).executeSequence()
    finally:
        config.master_data_path = original
    return base, out


# --- L71: dolomite and Mg fertiliser independent ---

def test_mg_fertiliser_and_dolomite_are_independent():
    # 30 x 120.3686 / 24.305 = 148.573 kg MgSO4; the 13.18 kg Mg of the dolomite are not subtracted
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        mgso4, dolomite = magnesium_fertiliser_split(30.0, 100.0)
    assert mgso4 == pytest.approx(148.573, abs=5e-4)
    assert dolomite == 100.0


def test_dolomite_alone_gives_no_magnesium_sulfate_and_no_warning():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert magnesium_fertiliser_split(0.0, 100.0) == (0.0, 100.0)


def test_heavy_metals_of_dolomite_are_those_of_its_stoichiometric_mg():
    # 100 x 24.305 / 184.4008 = 13.1805 kg Mg on the row "Mg magnesium"
    _assert_same_metals(_fert_model(dolomite_applied=100.0).computeHeavyMetal(),
                        _fert_model(magnesium=13.1805).computeHeavyMetal())


def test_heavy_metals_of_dolomite_add_to_those_of_the_mg_fertiliser():
    _assert_same_metals(_fert_model(magnesium=30.0, dolomite_applied=100.0).computeHeavyMetal(),
                        _fert_model(magnesium=43.1805).computeHeavyMetal())


# --- L72: quicklime and hydrated lime ---

@pytest.mark.parametrize("product, kg_ca", [("quicklime_applied", 71.469), ("hydrated_lime_applied", 54.092)])
def test_heavy_metals_of_lime_are_those_of_its_stoichiometric_ca_on_the_limestone_row(product, kg_ca):
    # quicklime 100 x 40.078 / 56.0774 = 71.469 kg Ca; hydrated lime 100 x 40.078 / 74.09268 = 54.092 kg Ca
    _assert_same_metals(_fert_model(**{product: 100.0}).computeHeavyMetal(),
                        _fert_model(ca={CaFertiliserType.ca_limestone: kg_ca}).computeHeavyMetal())


def test_new_inputs_default_to_zero():
    for name in NEW_INPUTS:
        assert DEFAULTS_VALUES_GENERATORS[name].generateDefault(name, {}) == 0.0
        assert name in FertModel._input_variables
    assert "quicklime_applied" not in Co2Model._input_variables
    assert "hydrated_lime_applied" not in Co2Model._input_variables


# --- whole model sequence (wheat_IT) ---

def test_model_sequence_dolomite_and_mg_fertiliser():
    base, out = _sequence(fert_other_total_mg=30.0, dolomite_applied=100.0)
    assert out["CO2_from_fertilisers"] - base["CO2_from_fertilisers"] == pytest.approx(47.732, abs=5e-4)
    assert out["magnesium_from_fertilizer_as_dolomite"] == 100.0
    assert out["magnesium_from_fertilizer_as_mgso4"] == pytest.approx(148.573, abs=5e-4)
    assert out["heavymetal_to_soil_cd"] > base["heavymetal_to_soil_cd"]


@pytest.mark.parametrize("product", ["quicklime_applied", "hydrated_lime_applied"])
def test_model_sequence_lime_gives_no_co2_and_writes_the_product(product):
    base, out = _sequence(**{product: 100.0})
    assert out["CO2_from_fertilisers"] == base["CO2_from_fertilisers"]
    assert out["CO2_non_fossil_from_fertilisers"] == base["CO2_non_fossil_from_fertilisers"]
    assert out[product] == 100.0
    assert base[product] == 0.0
    assert out["heavymetal_to_soil_cd"] > base["heavymetal_to_soil_cd"]
