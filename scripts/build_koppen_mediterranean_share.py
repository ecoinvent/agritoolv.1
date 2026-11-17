"""Build data/koppen_mediterranean_share.csv: share of the crop area in a Mediterranean climate per crop and country,
for the dry-climate PM factors of EMEP/EEA 2023 3.D Tables 3-7 and 3-9 (decision L68).

Climate rule (EMEP/EEA air pollutant emission inventory guidebook 2023, 3.D, p. 22: "dry climate conditions
(Mediterranean climate) and wet climate conditions (all other climates)"; FC 2026-11-12): a cell is dry where its
Koppen-Geiger class is Csa, Csb or Csc (temperate, dry summer; codes 8, 9 and 10 of the legend), wet otherwise. The
arid classes BWh, BWk, BSh and BSk are wet in this rule (written as a limit of L68).

Data: Koppen-Geiger map 1991-2020 of Beck et al. (2023), Scientific Data 10: 724,
data/external_data/koppen_geiger_1991_2020_0p1.tif (GeoTIFF, uint8, 0.1 degree, 1800 rows x 3600 columns, WGS 84, row
0 at 90 N, column 0 at 180 W; codes 1-30, 0 = sea or no data). The codes of the three classes are checked against the
legend Literature/legend koppen_geiger_1991_2020.txt. Each 1/12 degree cell of the SPAM grid takes the class of the
0.1 degree cell that contains its centre; cells with code 0 are left out (coverage < 1).

Method: dry_share = mean of the dry cells (1) and wet cells (0) over the SPAM 2020 V2r2 physical area of the crop in
the country (spam_grid.py, GAUL 2024 countries, row all_crops for all crops; the crop weights, coverage and fallback
to all_crops are those of ipcc_climate_wet_share.csv, L64).

Usage (repository root, build environment):
    .venv-gis\\Scripts\\python scripts\\build_koppen_mediterranean_share.py [--grid-cache FILE]
"""
import argparse
import re

import numpy as np
import tifffile

import spam_grid

KOPPEN_TIF = spam_grid.EXTERNAL_DATA_DIR / "koppen_geiger_1991_2020_0p1.tif"
LEGEND = spam_grid.ROOT / "Literature" / "legend koppen_geiger_1991_2020.txt"
OUTPUT = spam_grid.DATA_DIR / "koppen_mediterranean_share.csv"
KOPPEN_ROWS, KOPPEN_COLS, KOPPEN_CELLS_PER_DEGREE = 1800, 3600, 10
NO_DATA = 0
MEDITERRANEAN_CLASSES = ("Csa", "Csb", "Csc")
# Spot checks of the map (issue #53): (place, latitude, longitude, expected class)
SPOT_CHECKS = (("Sicily", 37.5, 14.2, "Csa"), ("Seville", 37.4, -6.0, "Csa"), ("Po valley", 45.0, 10.0, "Cfa"),
               ("Madrid plateau", 40.4, -3.7, "BSk"), ("Central Valley", 37.0, -120.5, "BSh"))


def legend_codes():
    """{class symbol: code} of the legend file."""
    codes = {}
    with open(LEGEND, encoding="utf-8") as f:
        for line in f:
            match = re.match(r"\s*(\d+):\s+(\S+)\s", line)
            if match:
                codes[match.group(2)] = int(match.group(1))
    assert len(codes) == 30, codes
    return codes


def koppen_map():
    with tifffile.TiffFile(KOPPEN_TIF) as tif:
        page = tif.pages[0]
        assert page.tags["ModelPixelScaleTag"].value[:2] == (0.1, 0.1)
        assert page.tags["ModelTiepointTag"].value[3:5] == (-180.0, 90.0)
        codes = page.asarray()
    assert codes.shape == (KOPPEN_ROWS, KOPPEN_COLS) and codes.max() <= 30, (codes.shape, codes.max())
    return codes


def koppen_cell(latitude, longitude):
    return (int(np.floor((90.0 - latitude) * KOPPEN_CELLS_PER_DEGREE)),
            int(np.floor((longitude + 180.0) * KOPPEN_CELLS_PER_DEGREE)))


def to_spam_grid(codes):
    """Code of the 0.1 degree cell containing the centre of each 1/12 degree cell. Centre of SPAM row i:
    (i + 0.5) / 12 degrees below 90 N, i.e. Koppen row floor((2i + 1) x 10 / 24), exact in integers (never on a
    boundary)."""
    rows = (np.arange(spam_grid.ROWS) * 2 + 1) * KOPPEN_CELLS_PER_DEGREE // (2 * spam_grid.CELLS_PER_DEGREE)
    cols = (np.arange(spam_grid.COLS) * 2 + 1) * KOPPEN_CELLS_PER_DEGREE // (2 * spam_grid.CELLS_PER_DEGREE)
    return codes[np.ix_(rows, cols)]


def dry_cells(codes, mediterranean_codes):
    """1 for a Mediterranean cell, 0 for any other class, NaN for no data."""
    dry = np.isin(codes, list(mediterranean_codes)).astype(float)
    dry[codes == NO_DATA] = np.nan
    return dry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--grid-cache", help="npy file to store or reuse the country grid")
    args = parser.parse_args()
    legend = legend_codes()
    mediterranean = [legend[c] for c in MEDITERRANEAN_CLASSES]
    codes = koppen_map()
    for place, latitude, longitude, expected in SPOT_CHECKS:
        found = codes[koppen_cell(latitude, longitude)]
        assert found == legend[expected], (place, found, expected)
        print("spot check %s (%.1f, %.1f): code %d = %s" % (place, latitude, longitude, found, expected))
    grid, countries = spam_grid.country_grid(args.grid_cache)
    rows = spam_grid.weighted_country_means({"dry_share": dry_cells(to_spam_grid(codes), mediterranean)},
                                            grid, countries, spam_grid.read_csv("spam2020_crop_mapping.csv"))
    columns = ["crop", "country", "weights", "area_ha", "coverage", "dry_share"]
    spam_grid.write_rows(OUTPUT, rows, columns, {"area_ha": 0, "coverage": 4, "dry_share": 3})
    print("written %s (%d rows)" % (OUTPUT.relative_to(spam_grid.ROOT), len(rows)))


if __name__ == "__main__":
    main()
