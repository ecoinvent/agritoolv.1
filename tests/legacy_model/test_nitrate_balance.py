"""Decision L77: nitrate leaching from a nitrogen balance x the leaching coefficient of Sio et al. (2008) Taula 6,
computed next to SQCB (not written). Expected values computed independently from Taula 6 (p. 5).

The conversions between NO3 and N use the atomic masses of the tool (models/atomicmass.py, 62.0049 / 14.0067), the
expected values of the brief 14/62 exactly: those tests compare with rel = 1e-3 (difference 4e-4).
"""
import csv
import warnings

import pytest

import dataloader
import regression_support as rs
from defaultGeneration import DefaultValuesWrapper, DEFAULTS_VALUES_GENERATORS
from models import nitratebalance as nb
from models.nmodel import NModel
from models.otherorganicfertilisermodel import CompostType, OtherOrganicFertModel, SludgeType
from test_fix_f3_nitrate_supply import BASE_INPUTS

NO3_REL = 1e-3


# --- 1-3. leached fraction -------------------------------------------------------------------------------------

@pytest.mark.parametrize("depth, texture, rain, expected", [
    (60, "loam", 250.0, 0.6125),   # 1 - (0.35 + 0.425) / 2, interpolated between 200 and 300 mm
    (90, "sandy", 50.0, 0.025),    # leached(100 mm) = 1 - (0.90 + 1.00) / 2 = 0.05, x 50 / 100
    (30, "clay", 700.0, 1.0),      # above the last row (> 400 mm): its value 0.00
    (90, "clay", 100.0, 0.0),
    (90, "silty", 200.0, 0.20),    # 1 - (0.75 + 0.85) / 2 (Anton 2026 Table 4 prints 0.225)
    (30, "loam", 350.0, 0.975),    # 1 - (0.00 + 0.05) / 2
])
def test_leached_fraction_well_drained(depth, texture, rain, expected):
    assert nb.leached_fraction(depth, texture, "well", rain) == pytest.approx(expected)


@pytest.mark.parametrize("depth, texture, group, expected", [
    (60, "loam", "moderately_well", 0.505),   # 1 - (0.40 x 1.1 + 0.50 x 1.1) / 2
    (60, "loam", "poorly", 0.46),             # 1 - (0.40 x 1.2 + 0.50 x 1.2) / 2
    (90, "clay", "poorly", 0.02),             # 1 - (0.80 x 1.2 + min(1.00 x 1.2, 1)) / 2
])
def test_drainage_factor_and_cap(depth, texture, group, expected):
    assert nb.leached_fraction(depth, texture, group, 200.0) == pytest.approx(expected)


def test_weighted_coefficient():
    shares = {(60, "loam", "well"): 0.5, (90, "clay", "well"): 0.5}
    assert nb.weighted_leached_fraction(shares, 200.0) == pytest.approx(0.5 * 0.55 + 0.5 * 0.10)


def test_taula6_transcription_has_every_cell():
    rows = dataloader.rows(nb.TAULA6)
    cells = {(int(r["depth_cm"]), int(r["rain_mm"]), r["texture"]) for r in rows}
    rains = {90: [100, 200, 300, 400, 500], 60: [100, 200, 300, 400, 500], 30: [100, 200, 300, 400]}
    assert len(rows) == len(cells) == 56
    assert cells == {(d, r, t) for d, rs_ in rains.items() for r in rs_ for t in ("clay", "silty", "loam", "sandy")}
    assert all(0.0 <= float(r[c]) <= 1.0 for r in rows for c in nb.COLUMNS)


# --- 4. drainage-season rain ------------------------------------------------------------------------------------

def test_drainage_season_precipitation():
    ppt = [10.0 * m for m in range(1, 13)]
    assert nb.drainage_season_precipitation(ppt, [60.0] * 12) == pytest.approx(570.0)


def test_drainage_rain_of_the_crop_cycle():
    model = _model(drainage_season_precipitation=570.0, crop_cycle_per_year=2.0)
    model.compute()
    assert model.last_balance_nitrate["drainage_rain_mm"] == pytest.approx(285.0)


def test_drainage_rain_default_is_the_crop_row():
    with open(dataloader.data_path("terraclimate1991_2020_climate.csv"), newline="", encoding="utf-8") as f:
        row = next(r for r in csv.DictReader(f) if r["crop"] == "wheat" and r["country"] == "IT")
    values = DefaultValuesWrapper({"crop": "wheat", "country": "IT", "cultivation_type": "open_ground"},
                                  DEFAULTS_VALUES_GENERATORS)
    assert values["drainage_season_precipitation"] == float(row["drainage_season_precipitation_mm"])
    assert 0.0 < values["drainage_season_precipitation"] <= values["average_annual_precipitation"]


def test_soil_shares_sum_to_one():
    for row in dataloader.rows(nb.SOIL_SHARES):
        total = sum(float(v) for c, v in row.items() if c.startswith("share_d"))
        assert total == pytest.approx(1.0, abs=1e-4), (row["crop"], row["country"])


# --- 5. available organic N -------------------------------------------------------------------------------------

def _organic(compost=None, sludge=None):
    return OtherOrganicFertModel({"compost_quantities": compost or {}, "sludge_quantities": sludge or {}})


@pytest.mark.parametrize("compost, sludge, expected", [
    ({CompostType.dried_poultry_manure: 1000.0}, None, 38.2 * 0.65),
    ({CompostType.compost: 2000.0}, None, 1.05),            # 2 x 7.0 x 0.075
    (None, {SludgeType.sewagesludge_liquid: 10000.0}, 13.5),  # 10 x 3 x 0.45
])
def test_available_organic_n(compost, sludge, expected):
    assert _organic(compost, sludge).computeAvailableN() == pytest.approx(expected)


def test_type_without_available_share_counts_zero_with_a_warning():
    with pytest.warns(UserWarning, match="feather_meal"):
        assert _organic({CompostType.feather_meal: 1000.0}).computeAvailableN() == 0.0


def test_type_without_available_share_not_applied_gives_no_warning():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert _organic({CompostType.feather_meal: 0.0}).computeAvailableN() == 0.0


# --- 6. irrigation water N --------------------------------------------------------------------------------------

def test_irrigation_n_from_nitrate():
    assert nb.irrigation_water_n(50.0, "mg NO3/l", 2000.0, "yes") == pytest.approx(22.5806, rel=NO3_REL)


def test_irrigation_n_from_nitrate_n():
    assert nb.irrigation_water_n(10.0, "mg NO3-N/l", 2000.0, "yes") == pytest.approx(20.0)


def test_irrigation_n_taula9_check():
    # Sio et al. (2008) Taula 9: 62 ppm NO3 (1 meq/l) with 1000 m3/ha -> 14 kg N/ha
    assert nb.irrigation_water_n(62.0, "mg NO3/l", 1000.0, "yes") == pytest.approx(14.0, rel=NO3_REL)


@pytest.mark.parametrize("concentration, irrigated", [(50.0, "no"), (None, "yes")])
def test_irrigation_n_zero_when_not_irrigated_or_not_given(concentration, irrigated):
    assert nb.irrigation_water_n(concentration, "mg NO3/l", 2000.0, irrigated) == 0.0


def test_irrigation_n_unknown_unit():
    with pytest.raises(ValueError):
        nb.irrigation_water_n(50.0, "ppm", 2000.0, "yes")


# --- 7. balance of the regression cases -------------------------------------------------------------------------

def _sequence(name, **overrides):
    import config
    from modelsSequence import ModelsSequence
    inputs = rs.load_inputs(name)
    inputs.update(overrides)
    original = config.master_data_path
    config.master_data_path = lambda: None
    try:
        sequence = ModelsSequence(inputs)
        output = sequence.executeSequence()
    finally:
        config.master_data_path = original
    return sequence, output


# Terms of the regression cases (FC 2026-11-26). The gaseous losses are those of the N supply S of SQCB (Fix F3), with
# the atomic masses of the tool (decision of FC 2026-11-26; the first brief split them with 14/17 for NH3, same sum).
BALANCE_TERMS = {
    "wheat_IT": {"mineral_n": 150.0, "available_organic_n": 31.5, "crop_residue_n": 63.8584, "n_som": 0.0,
                 "irrigation_water_n": 0.0, "n_uptake": -154.8083, "nh3_n": -29.1858, "nox_n": -2.0308,
                 "direct_n2o_n": -1.2140, "balance": 58.1194},
    "apple_FR": {"mineral_n": 80.0, "available_organic_n": 9.55, "crop_residue_n": 0.0, "n_som": 0.0,
                 "irrigation_water_n": 0.0, "n_uptake": -36.1, "nh3_n": -6.4991, "nox_n": -1.3757,
                 "direct_n2o_n": -1.0177, "balance": 44.5575},
}


@pytest.mark.parametrize("name", sorted(BALANCE_TERMS))
def test_balance_of_the_regression_cases(name):
    sequence, _ = _sequence(name)
    result = sequence.nModel.last_balance_nitrate
    for term, expected in BALANCE_TERMS[name].items():
        assert result[term] == pytest.approx(expected, abs=1e-4), term


@pytest.mark.parametrize("name", sorted(BALANCE_TERMS))
def test_gaseous_losses_are_those_of_the_sqcb_supply(name):
    sequence, _ = _sequence(name)
    model, result = sequence.nModel, sequence.nModel.last_balance_nitrate
    supply = model.nitrogen_from_mineral_fert + model.soluble_nitrogen_from_organic_fert
    assert model.last_nitrogen_supply > 0.0
    losses = result["nh3_n"] + result["nox_n"] + result["direct_n2o_n"]
    assert supply + losses == pytest.approx(model.last_nitrogen_supply)


def test_nitrate_with_coefficient_one_half(monkeypatch):
    monkeypatch.setattr(nb, "weighted_leached_fraction", lambda shares, rain: 0.5)
    sequence, _ = _sequence("wheat_IT")
    result = sequence.nModel.last_balance_nitrate
    assert result["nitrate_to_groundwater"] + result["nitrate_to_surfacewater"] == pytest.approx(128.693, rel=NO3_REL)


# --- 8. negative balance, flooded rice --------------------------------------------------------------------------

def _model(**overrides):
    inputs = dict(BASE_INPUTS)
    inputs.update(overrides)
    return NModel(inputs)


def test_negative_balance_leaches_nothing():
    model = _model(nitrogen_from_mineral_fert=50.0, nitrogen_uptake_by_crop=150.0, drainage_season_precipitation=400.0)
    model.compute()
    assert model.last_balance_nitrate["balance"] < 0.0
    assert model.last_balance_nitrate["coefficient"] > 0.0
    assert model.last_balance_nitrate["no3_as_n"] == 0.0


def test_split_between_ground_and_surface_water():
    model = _model(nitrogen_from_mineral_fert=250.0, drainage_season_precipitation=400.0, drained_part=0.25)
    model.compute()
    result = model.last_balance_nitrate
    total = result["nitrate_to_groundwater"] + result["nitrate_to_surfacewater"]
    assert total > 0.0
    assert result["nitrate_to_surfacewater"] == pytest.approx(0.25 * total)


def test_flooded_rice_keeps_sqcb_only():
    # the SQCB nitrate of rice_IN is checked by the regression snapshot (test_regression_legacy.py)
    sequence, _ = _sequence("rice_IN")
    assert sequence.nModel.last_balance_nitrate is None


def test_upland_rice_uses_the_balance():
    model = _model(crop="rice", rice_water_regime="upland", nitrogen_from_mineral_fert=200.0,
                   drainage_season_precipitation=300.0)
    model.compute()
    assert model.last_balance_nitrate is not None

