"""Decision L73 (walkthrough B5): P2O5 of compost, of the other organic fertilisers and of dehydrated
and dried sewage sludge in SALCA-P (Prasuhn 2006).

Run-off (p. 13, "Klaerschlamm wird wie Guelle, Kompost wie Mist beruecksichtigt"): every sewage
sludge enters the slurry term of Fro (0.7/80), every compost type the solid manure term (0.4/80).
Leaching (p. 7): only liquid manure and liquid sewage sludge (0.2/80).
Contents per t FM from data/organic_fertiliser_composition.csv (GRUDAF 2009 Table 42 for compost,
Agribalyse 3.1 Table 142 for the rest). Expected values computed by hand from these contents.
"""
import warnings

import pytest

from models.atomicmass import P_TO_PO4_FACTOR
from models.otherorganicfertilisermodel import CompostType, OtherOrganicFertModel, SludgeType
from models.pmodel import LandUseCategory, PModel

# Arable land: average leaching 0.07 kg P/(ha*yr), run-off 0.175 kg P/(ha*yr) (p_landuse_classes.csv)
LEACHING_BASE = 0.07
RUNOFF_BASE = 0.175


def _organic(compost=None, sludge=None):
    c = {k: 0.0 for k in CompostType}
    c.update(compost or {})
    s = {k: 0.0 for k in SludgeType}
    s.update(sludge or {})
    return OtherOrganicFertModel({"compost_quantities": c, "sludge_quantities": s})


def _p_outputs(compost=None, sludge=None, known_slope_pct=None):
    """P model fed as in modelsSequence: liquid sludge, solid sludge and compost P2O5 [kg/ha]."""
    liquid_sludge, solid_sludge, compost_p2o5 = _organic(compost, sludge).computeP2O5()
    return PModel({
        "crop_cycle_per_year": 1.0, "drained_part": 0.0, "eroded_soil": 0.0,
        "land_use_category": LandUseCategory.arable_land, "known_slope_pct": known_slope_pct,
        "p2o5_in_liquid_manure": 0.0, "p2o5_in_liquid_sludge": liquid_sludge,
        "p2o5_in_solid_sludge": solid_sludge, "p2o5_in_compost": compost_p2o5,
        "p2O5_from_mineral_fert": 0.0, "p2o5_in_solid_manure": 0.0,
    }).compute()


def _runoff_increment(out):
    """Fro - 1 of the run-off [kg PO4/ha] on arable land."""
    return out["m_P_PO4_surfacewater_ro"] / (RUNOFF_BASE * P_TO_PO4_FACTOR) - 1


def _leaching_increment(out):
    """Leaching correction factor - 1 of the groundwater phosphate [kg PO4/ha] on arable land."""
    return out["m_P_PO4_groundwater"] / (LEACHING_BASE * P_TO_PO4_FACTOR) - 1


def test_compost_enters_the_manure_term_of_runoff_only():
    # 10 t x 3 kg P2O5/t = 30 kg P2O5; 0.4/80 x 30 = 0.15
    assert _organic(compost={CompostType.compost: 10_000}).computeP2O5() == pytest.approx((0.0, 0.0, 30.0))
    out = _p_outputs(compost={CompostType.compost: 10_000})
    assert _runoff_increment(out) == pytest.approx(0.15, rel=1e-9)
    assert _leaching_increment(out) == pytest.approx(0.0, abs=1e-12)


def test_dehydrated_sludge_enters_the_slurry_term_of_runoff_only():
    # 1 t x 7.5 kg P2O5/t; 0.7/80 x 7.5 = 0.065625
    assert _organic(sludge={SludgeType.sewagesludge_dehydrated: 1_000}).computeP2O5() == pytest.approx((0.0, 7.5, 0.0))
    out = _p_outputs(sludge={SludgeType.sewagesludge_dehydrated: 1_000})
    assert _runoff_increment(out) == pytest.approx(0.065625, rel=1e-9)
    assert _leaching_increment(out) == pytest.approx(0.0, abs=1e-12)


def test_dried_sludge_enters_the_slurry_term_of_runoff_only():
    # 1 t x 60 kg P2O5/t; 0.7/80 x 60 = 0.525
    out = _p_outputs(sludge={SludgeType.sewagesludge_dried: 1_000})
    assert _runoff_increment(out) == pytest.approx(0.525, rel=1e-9)
    assert _leaching_increment(out) == pytest.approx(0.0, abs=1e-12)


def test_liquid_sludge_unchanged_in_leaching_and_runoff():
    # 1 t x 2.5 kg P2O5/t; run-off 0.7/80 x 2.5 = 0.021875, leaching 0.2/80 x 2.5 = 0.00625
    assert _organic(sludge={SludgeType.sewagesludge_liquid: 1_000}).computeP2O5() == pytest.approx((2.5, 0.0, 0.0))
    out = _p_outputs(sludge={SludgeType.sewagesludge_liquid: 1_000})
    assert _runoff_increment(out) == pytest.approx(0.021875, rel=1e-9)
    assert _leaching_increment(out) == pytest.approx(0.00625, rel=1e-9)


def test_dried_poultry_manure_enters_the_manure_term():
    # 1 t x 37.9 kg P2O5/t; 0.4/80 x 37.9 = 0.1895
    out = _p_outputs(compost={CompostType.dried_poultry_manure: 1_000})
    assert _runoff_increment(out) == pytest.approx(0.1895, rel=1e-9)
    assert _leaching_increment(out) == pytest.approx(0.0, abs=1e-12)


def test_vinasse_has_no_p2o5_and_no_warning():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert _organic(compost={CompostType.vinasse: 1_000}).computeP2O5() == (0.0, 0.0, 0.0)


@pytest.mark.parametrize("fert_type", [CompostType.meat_and_bone_meal, CompostType.castor_oil_shell_coarse,
                                       CompostType.feather_meal, CompostType.horn_meal,
                                       CompostType.horn_shavings_fine, CompostType.stone_meal])
def test_types_without_a_p2o5_source_count_zero_with_a_warning(fert_type):
    with pytest.warns(UserWarning, match=fert_type.value):
        assert _organic(compost={fert_type: 1_000}).computeP2O5() == (0.0, 0.0, 0.0)


def test_types_without_a_p2o5_source_give_no_warning_when_not_applied():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert _organic().computeP2O5() == (0.0, 0.0, 0.0)


def test_no_runoff_for_known_slope_up_to_3_pct_whatever_the_organic_p():
    out = _p_outputs(compost={CompostType.compost: 10_000},
                     sludge={SludgeType.sewagesludge_dried: 1_000, SludgeType.sewagesludge_liquid: 1_000},
                     known_slope_pct=3.0)
    assert out["m_P_PO4_surfacewater_ro"] == 0.0
