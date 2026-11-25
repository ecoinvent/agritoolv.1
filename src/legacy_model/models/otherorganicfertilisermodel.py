import warnings
from enum import Enum

import dataloader
from models.atomicmass import N_TO_NH3_FACTOR
from models.manuremodel import ManureModel
from models.modelEnums import HeavyMetalType

class CompostType(Enum):
    compost="composttype_compost"
    meat_and_bone_meal="composttype_meat_and_bone_meal"
    castor_oil_shell_coarse="composttype_castor_oil_shell_coarse"
    vinasse="composttype_vinasse"
    dried_poultry_manure="composttype_dried_poultry_manure"
    stone_meal="composttype_stone_meal"
    feather_meal="composttype_feather_meal"
    horn_meal="composttype_horn_meal"
    horn_shavings_fine="composttype_horn_shavings_fine"
    
class SludgeType(Enum):
    sewagesludge_liquid="sewagesludge_liquid"
    sewagesludge_dehydrated="sewagesludge_dehydrated"
    sewagesludge_dried="sewagesludge_dried"

class OtherOrganicFertModel(object):
    """Inputs:
      compost_quantities: map CompostType -> kg fert/ha
      sludge_quantities: map SludgeType -> kg fert/ha

    Outputs:
      computeP2O5:
        (liquid sewage sludge, dehydrated and dried sewage sludge, compost types): kg P2O5/ha
      computeN:
        N_total_otherfert: kg N/ha
      computeNH3:
        nh3_total_otherfert: kg NH3/ha
      computeHeavyMetal:
        hm_total_otherfert : map HeavyMetalType -> mg i/ha (i:hm type)
    """
    
    _input_variables = ["compost_quantities",
                        "sludge_quantities"
                       ]
    
    # Contents per t of fresh matter (N, TAN, P2O5) and the EMEP/EEA 2023 source category of each
    # type are read from data/organic_fertiliser_composition.csv; the NH3 EF per kg N applied of a
    # 3.D category from data/emep2023_3d_table3_1.csv (decision L15). Livestock manure (3.B
    # category, decision L21) uses the spreading EF of its emep_livestock / emep_manure_type row
    # of data/emep2023_3b_table3_9.csv, as the manure model.
    _COMPOSITION_TABLE = "organic_fertiliser_composition.csv"
    _EF_TABLE = "emep2023_3d_table3_1.csv"

    @classmethod
    def _content(cls, fert_type, column):
        """Content [kg/t FM] of a compost or sludge type, column of the composition table."""
        rows = dataloader.table(cls._COMPOSITION_TABLE)
        if fert_type.value not in rows:
            raise KeyError("Fertiliser type %s not in %s" % (fert_type.value, cls._COMPOSITION_TABLE))
        return rows[fert_type.value][column]

    @classmethod
    def _nh3_ef(cls, fert_type):
        """EMEP/EEA 2023 3.D Table 3-1 Tier 1 EF [kg NH3/kg N applied] of the type's category."""
        nfr = dataloader.table(cls._COMPOSITION_TABLE)[fert_type.value]["emep_nfr"]
        for row in dataloader.rows(cls._EF_TABLE):
            if row["nfr"] == nfr and row["pollutant"] == "NH3":
                return float(row["ef"])
        raise KeyError("No NH3 row for %s in %s" % (nfr, cls._EF_TABLE))

    def __init__(self, inputs):
        #TODO: Should we log usage of default value?
        for key in OtherOrganicFertModel._input_variables:
            setattr(self, key, inputs[key])
            
    def computeP2O5(self):
        """P2O5 [kg/ha] for SALCA-P (Prasuhn 2006), decision L73, as three sums:
        (liquid sewage sludge, dehydrated and dried sewage sludge, compost types).

        Liquid sludge enters leaching and the slurry term of run-off, solid sludge only the slurry
        term of run-off ("Klaerschlamm wird wie Guelle ... beruecksichtigt", p. 13), the compost types
        the solid manure term of run-off ("Kompost wie Mist"). P2O5 per t FM from the composition
        table; a type without a P2O5 value (no source) counts 0, with a warning when applied.
        """
        liquid_sludge = self._p2o5({SludgeType.sewagesludge_liquid:
                                    self.sludge_quantities[SludgeType.sewagesludge_liquid]})
        solid_sludge = self._p2o5({k: v for k, v in self.sludge_quantities.items()
                                   if k != SludgeType.sewagesludge_liquid})
        return (liquid_sludge, solid_sludge, self._p2o5(self.compost_quantities))

    def _p2o5(self, quantities):
        """sum(kg FM / 1000 x kg P2O5/t FM) over the given types [kg P2O5/ha]."""
        total = 0.0
        for fert_type, kg_fm in quantities.items():
            content = self._content(fert_type, "p2o5_kg_per_t_fm")
            if content is None:
                if kg_fm > 0:
                    warnings.warn("%s applied (%g kg/ha) has no P2O5 content in %s: its P is not counted "
                                  "in the P model (decision L73)" % (fert_type.value, kg_fm, self._COMPOSITION_TABLE))
                continue
            total += kg_fm * content / 1000.0
        return total

    def computeN(self):
        return self._sum_per_t(lambda fert_type: self._content(fert_type, "n_total_kg_per_t_fm"))

    def computeNH3(self):
        """NH3 [kg NH3/ha] after spreading of compost and sewage sludge (decisions L15, L21).

        EMEP/EEA 2023 3.D Tier 1, Eq. (1): sum(quantity [kg FM] / 1000 * N [kg N/t FM] * EF),
        with EF in kg NH3 per kg N applied (Table 3-1), so the result is already kg NH3 (Fix F5).
        Livestock manure (3.B category): TAN [kg N/t FM] x EF application (fraction of TAN emitted
        as NH3-N, 3.B Table 3-9) x 17/14.
        """
        return self._sum_per_t(self._nh3_per_t)

    @classmethod
    def _nh3_per_t(cls, fert_type):
        """NH3 [kg NH3/t FM] after spreading of one type."""
        row = dataloader.table(cls._COMPOSITION_TABLE)[fert_type.value]
        if row["emep_nfr"].startswith("3B"):
            ef = ManureModel._application_ef(row["emep_livestock"], row["emep_manure_type"])
            return row["tan_kg_n_per_t_fm"] * ef * N_TO_NH3_FACTOR
        return row["n_total_kg_per_t_fm"] * cls._nh3_ef(fert_type)

    def computeSolubleN(self):
        """Soluble (ammoniacal) N applied with compost and sludge [kg N/ha] (Fix F3)."""
        return self._sum_per_t(lambda fert_type: self._content(fert_type, "tan_kg_n_per_t_fm"))

    def _sum_per_t(self, value_per_t):
        """sum(kg FM / 1000 x value_per_t(type)) over compost and sludge."""
        return sum(v * value_per_t(k)
                   for quantities in (self.compost_quantities, self.sludge_quantities)
                   for k, v in quantities.items()) / 1000.0

    # Heavy metals: organic-fertiliser rows of SALCAheavymetal 2023 Table 1 (decision L10)
    # assigned in data/hm_organic_fertiliser_mapping.csv; apply_dm = no for sewage sludge, whose
    # Table 1 values are used per kg fresh matter (recommendation 5).
    _HM_MAPPING = "hm_organic_fertiliser_mapping.csv"

    def computeHeavyMetal(self):
        """Heavy-metal input with compost and sewage sludge, map HeavyMetalType -> mg/ha:
        kg fresh matter x DM (if apply_dm) x mg/kg of the Table 1 row."""
        mapping = dataloader.table(self._HM_MAPPING, numeric=False)
        total_hm_values = dict.fromkeys(HeavyMetalType, 0.0)
        for quantities in (self.compost_quantities, self.sludge_quantities):
            for fert_type, kg_fm in quantities.items():
                row = mapping[fert_type.value]
                content = dataloader.hm_entry(row["salca2023_row"])
                dm = content["dm"] if row["apply_dm"] == "yes" else 1.0
                for element in HeavyMetalType:
                    total_hm_values[element] += kg_fm * dm * content[element.name.capitalize()]
        return total_hm_values
