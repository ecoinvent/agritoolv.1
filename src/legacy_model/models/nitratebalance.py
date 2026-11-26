"""Nitrate leaching from a nitrogen balance and a leaching coefficient (decision L77).

NO3-N = N balance x leaching coefficient, computed next to the SQCB-NO3 regression for every crop except the flooded
crops (column "flooded" of data/crop_types.csv), which keep SQCB only.

Leaching coefficient: Sio J., Serra J., Lopez A., Boixadera J., Teixidor N. (2008) Gestio de l'adobat nitrogenat en
el conreu dels cereals d'hivern, 4th ed., DAR Generalitat de Catalunya / Fundacio Mas Badia, Taula 6 (p. 5),
transcribed in data/sio2008_taula6_leaching.csv: fraction of the residual N retained in the soil from 1 October to
1 March, by soil depth (90, 60, 30 cm), rain of the period (100 to 500 mm) and texture (clay, silty, loam, sandy), for
a previous crop irrigated in summer and for a rain-fed summer or a winter previous crop. Per column:

    retained = linear interpolation between the rain rows (above the last row: its value)
               x drainage factor (data/sio2008_drainage_factors.csv), never above 1
    leached  = 1 - mean of the two columns
    rain below the first row (100 mm): leached(100 mm) x rain / 100

The coefficient of a dataset is the sum over the 36 soil classes (depth x texture x drainage group,
data/hwsd2_leaching_soil_shares.csv) of share x leached at the drainage-season rain of the crop cycle.
"""
from functools import lru_cache

import dataloader
from models.atomicmass import N_TO_NO3_FACTOR

TAULA6 = "sio2008_taula6_leaching.csv"
DRAINAGE_FACTORS = "sio2008_drainage_factors.csv"
SOIL_SHARES = "hwsd2_leaching_soil_shares.csv"
COLUMNS = ("retained_irrigated_summer_previous", "retained_rainfed_or_winter_previous")
FIRST_RAIN_ROW_MM = 100.0

# Units of the optional template field irrigation_water_nitrate (T18) -> factor to mg NO3-N/l
IRRIGATION_NITRATE_UNITS = {"mg NO3/l": 1.0 / N_TO_NO3_FACTOR, "mg NO3-N/l": 1.0}


def drainage_month(ppt, pet):
    """Precipitation of a month that counts for the drainage season: ppt when ppt > pet, else 0.

    Works on numbers and on numpy arrays (scripts/build_terraclimate_climate.py); NaN stays NaN."""
    return ppt * (ppt > pet) + 0.0 * pet


def drainage_season_precipitation(ppt_by_month, pet_by_month):
    """Sum of the monthly precipitation of the months with precipitation above PET [mm/yr] (decision L77)."""
    return sum(drainage_month(ppt, pet) for ppt, pet in zip(ppt_by_month, pet_by_month))


def _rows(depth_cm, texture):
    """[(rain_mm, (retained per column))] of Taula 6 for a depth and texture, by increasing rain."""
    out = [(float(r["rain_mm"]), tuple(float(r[c]) for c in COLUMNS))
           for r in dataloader.rows(TAULA6) if int(r["depth_cm"]) == int(depth_cm) and r["texture"] == texture]
    if not out:
        raise KeyError("No row of %s for depth %s cm and texture %s" % (TAULA6, depth_cm, texture))
    return sorted(out)


def retained_fractions(depth_cm, texture, rain_mm):
    """Retained fraction of each column of Taula 6, interpolated linearly in the rain (constant above the last row)."""
    rows = _rows(depth_cm, texture)
    if rain_mm <= rows[0][0]:
        return rows[0][1]
    for (r0, v0), (r1, v1) in zip(rows, rows[1:]):
        if rain_mm <= r1:
            w = (rain_mm - r0) / (r1 - r0)
            return tuple(a + w * (b - a) for a, b in zip(v0, v1))
    return rows[-1][1]


def drainage_factor(group):
    """Factor of the note of Taula 6 for a drainage group (well, moderately_well, poorly)."""
    return dataloader.table(DRAINAGE_FACTORS)[group]["factor"]


def leached_fraction(depth_cm, texture, drainage_group, rain_mm):
    """Leached fraction of the residual N for one soil class at the drainage-season rain [mm]."""
    if rain_mm < 0:
        raise ValueError("rain must not be negative, got %r" % rain_mm)
    factor = drainage_factor(drainage_group)
    retained = [min(v * factor, 1.0)
                for v in retained_fractions(depth_cm, texture, max(rain_mm, FIRST_RAIN_ROW_MM))]
    leached = 1.0 - sum(retained) / len(retained)
    if rain_mm < FIRST_RAIN_ROW_MM:
        return leached * rain_mm / FIRST_RAIN_ROW_MM
    return leached


def parse_class(column):
    """(depth_cm, texture, drainage_group) of a column share_d<depth>_<texture>_<drainage group>."""
    depth, texture, group = column[len("share_d"):].split("_", 2)
    return int(depth), texture, group


def weighted_leached_fraction(shares, rain_mm):
    """Leaching coefficient of a dataset: sum of share x leached fraction over the soil classes.

    shares: {(depth_cm, texture, drainage_group): share}."""
    return sum(share * leached_fraction(depth, texture, group, rain_mm)
               for (depth, texture, group), share in shares.items() if share)


def soil_shares(crop, country):
    """{(depth_cm, texture, drainage_group): share} of the crop in the country; row all_crops of the country for a
    crop outside the table (as the other HWSD defaults, decision L63)."""
    table = _soil_share_table()
    row = table.get((crop, country)) or table[("all_crops", country)]
    return dict(row)


@lru_cache(maxsize=None)
def _soil_share_table():
    return {(r["crop"], r["country"]): tuple((parse_class(c), float(v)) for c, v in r.items()
                                             if c.startswith("share_d") and v != "")
            for r in dataloader.rows(SOIL_SHARES)}


def irrigation_water_n(concentration, unit, water_m3_per_ha, irrigated):
    """N applied with the irrigation water [kg N/ha and crop cycle] (template field T18, decision L77).

    All the N of the water: concentration as mg NO3-N/l x water [m3/ha] / 1000. None (N/A) -> 0; 0 when the crop
    is not irrigated."""
    if irrigated != "yes" or concentration is None:
        return 0.0
    if unit not in IRRIGATION_NITRATE_UNITS:
        raise ValueError("irrigation_water_nitrate_unit must be one of %s, got %r"
                         % (", ".join(IRRIGATION_NITRATE_UNITS), unit))
    return concentration * IRRIGATION_NITRATE_UNITS[unit] * water_m3_per_ha / 1000.0

