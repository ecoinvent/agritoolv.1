"""Particulate matter (PM10, PM2.5) of soil and crop dust from field operations, EMEP/EEA 2023 3.D Tier 2
(decision L68, issue #53).

EMEP/EEA air pollutant emission inventory guidebook 2023, 3.D Crop production and agricultural soils
(Literature/emep_3.DAgriculturalsoils2023FINAL.pdf), Eq. (5), p. 22, per ha of the crop:

    E_PM [kg/(ha and crop cycle)] = sum over operations k of EF_PM(t, k) x N(t, k)
    EF_PM(t, k) = (1 - d) x EF_PM,wet(t, k) + d x EF_PM,dry(t, k)

EF_PM in kg/ha per pass: Tables 3-6 (PM10, wet), 3-7 (PM10, dry), 3-8 (PM2.5, wet) and 3-9 (PM2.5, dry), p. 23
(van der Hoek and Hinz, 2007), in data/emep2023_3d_tables3_6_3_9.csv; "NC" (not calculable) is an empty value, read as
0. Dry = Mediterranean climate, wet = all other climates (p. 22). d = mediterranean_climate_share, default the share of
the SPAM 2020 crop area in the Koppen-Geiger classes Csa, Csb and Csc (data/koppen_mediterranean_share.csv,
scripts/build_koppen_mediterranean_share.py).

Crop t: emep2023_pm_crop_mapping.csv (wheat -> wheat, oat -> oats, every other crop -> other arable, whose harvesting,
cleaning and drying are NC). Passes N(t, k): the ha of each field operation per ha and crop cycle (outputs of
OutputMapping.mapMachineries: kg diesel of the legacy inputs / legacy diesel intensity of the operation,
data/legacy_machinery_diesel_intensity.csv), summed per EMEP operation with emep2023_pm_operation_mapping.csv (soil
cultivation, harvesting); operations without an EMEP operation are not counted, and cleaning and drying have no pass
(N = 0). On this legacy path only the operations with a diesel intensity per ha count: decompactation is written as
diesel energy (MJ), not as ha, so it gives no PM until the passes come from template v3 (limit (f) of L68).

ecoinvent PM flows are exclusive size classes: pm2_5_field_operations_air = PM2.5 (Particulate Matter, < 2.5 um) and
pm2_5_to_10_field_operations_air = PM10 - PM2.5 (Particulate Matter, > 2.5 um and < 10um); nothing goes to > 10 um.
No correction for the deposition near the field (p. 22). Exhaust PM of the diesel is in the diesel dataset.
"""
import dataloader
from outputMapping import machinery_diesel_intensity

EF_TABLE = "emep2023_3d_tables3_6_3_9.csv"
OPERATION_MAPPING = "emep2023_pm_operation_mapping.csv"
CROP_MAPPING = "emep2023_pm_crop_mapping.csv"
PM10, PM2_5 = "PM10", "PM2.5"
WET, DRY = "wet", "dry"
CONFIRMED = "confirmed"
PM2_5_KEY = "pm2_5_field_operations_air"
PM2_5_TO_10_KEY = "pm2_5_to_10_field_operations_air"


def emission_factors():
    """{(pollutant, climate, emep_crop, operation): kg/ha per pass}; NC (empty value) -> 0.0."""
    out = {}
    for row in dataloader.rows(EF_TABLE):
        value = row["ef_kg_per_ha_per_pass"]
        out[(row["pollutant"], row["climate"], row["emep_crop"], row["operation"])] = float(value) if value else 0.0
    return out


def check_pm2_5_below_pm10(factors):
    """Guard of L68: PM2.5 <= PM10 for every crop, operation and climate."""
    for (pollutant, climate, crop, operation), value in factors.items():
        if pollutant == PM2_5 and value > factors[(PM10, climate, crop, operation)]:
            raise ValueError("%s: PM2.5 %s > PM10 %s for %s, %s, %s climate"
                             % (EF_TABLE, value, factors[(PM10, climate, crop, operation)], crop, operation, climate))


def _confirmed(filename, key_column, value_column):
    out = {}
    for row in dataloader.rows(filename):
        if row["status"] != CONFIRMED:
            raise ValueError("%s: row %s is not confirmed" % (filename, row[key_column]))
        out[row[key_column]] = row[value_column]
    return out


def emep_crop(crop):
    crops = _confirmed(CROP_MAPPING, "crop", "emep_crop")
    if crop not in crops:
        raise KeyError("Crop %r has no row in %s" % (crop, CROP_MAPPING))
    return crops[crop]


def operation_mapping():
    """{operation key: EMEP operation} of the counted operations."""
    return {k: v for k, v in _confirmed(OPERATION_MAPPING, "operation", "emep_operation").items() if v}


def passes_per_emep_operation(operation_passes):
    """{EMEP operation: passes per crop cycle} from {operation key: ha of the operation per ha}."""
    out = {}
    for operation, emep_operation in operation_mapping().items():
        out[emep_operation] = out.get(emep_operation, 0.0) + (operation_passes.get(operation) or 0.0)
    return out


def field_operation_pm(crop, operation_passes, mediterranean_share):
    """{PM10, PM2.5: kg/(ha and crop cycle)} of Eq. (5) for one crop."""
    if not 0.0 <= mediterranean_share <= 1.0:
        raise ValueError("mediterranean_climate_share must be between 0 and 1, got %r" % (mediterranean_share,))
    factors = emission_factors()
    check_pm2_5_below_pm10(factors)
    t = emep_crop(crop)
    out = {PM10: 0.0, PM2_5: 0.0}
    for operation, passes in passes_per_emep_operation(operation_passes).items():
        for pollutant in out:
            ef = (1.0 - mediterranean_share) * factors[(pollutant, WET, t, operation)] \
                + mediterranean_share * factors[(pollutant, DRY, t, operation)]
            out[pollutant] += ef * passes
    return out


def legacy_operations_in_ha():
    """Counted operations whose legacy output is ha of the operation (diesel intensity per ha in
    legacy_machinery_diesel_intensity.csv)."""
    intensity = machinery_diesel_intensity()
    return [k for k in operation_mapping() if k in intensity and intensity[k][1] == "ha"]


class PmModel(object):
    def __init__(self, allInputs):
        self.allInputs = allInputs

    def compute(self):
        passes = {k: self.allInputs[k] for k in legacy_operations_in_ha() if k in self.allInputs}
        pm = field_operation_pm(self.allInputs["crop"], passes, self.allInputs["mediterranean_climate_share"])
        return {PM2_5_KEY: pm[PM2_5], PM2_5_TO_10_KEY: pm[PM10] - pm[PM2_5]}
