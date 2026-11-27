"""Utility water written as the Master Data 3.12 resource of its source (walkthrough A10, decision R12).

The legacy writer wrote the groundwater utility water as 'Water, river' (EcospoldTemplateSubstanceUsages.java,
array resources); R12 corrects the row of R7 to 'Water, well, in ground'. Surface water stays 'Water, river'.
"""
import csv

import pytest

import dataloader

EXPECTED = {
    "utilities_wateruse_ground": ("Water, well, in ground", "67c40aae-d403-464d-9649-c12695e43ad8", "m3"),
    "utilities_wateruse_surface": ("Water, river", "8c75e7ab-8ab8-41e4-b394-c166ff5b050d", "m3"),
}


def _rows():
    with open(dataloader.DATA_DIR / "elementary_flow_alignment.csv", newline="", encoding="utf-8") as f:
        return {r["model_variable"]: r for r in csv.DictReader(f) if r["model_variable"] in EXPECTED}


@pytest.mark.parametrize("variable", sorted(EXPECTED))
def test_utility_water_is_written_as_the_resource_of_its_source(variable):
    row = _rows()[variable]
    assert (row["md312_name"], row["md312_uuid"], row["md312_unit"]) == EXPECTED[variable]
    assert (row["compartment"], row["subcompartment"]) == ("natural resource", "in water")


def test_groundwater_and_surface_water_are_different_flows():
    rows = _rows()
    assert rows["utilities_wateruse_ground"]["md312_uuid"] != rows["utilities_wateruse_surface"]["md312_uuid"]
