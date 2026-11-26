"""Build data/hwsd2_leaching_soil_shares.csv: shares of the soil classes of the nitrate leaching coefficient (Sio et al.
2008, Taula 6) per crop and country, from the Harmonized World Soil Database v2.0 (decision L77).

Source: FAO & IIASA (2023) Harmonized World Soil Database version 2.0. data/external_data/HWSD2_RASTER.zip (HWSD2.bil,
30 arc-seconds, soil mapping unit per cell) and HWSD2_DB.zip (HWSD2.mdb, table HWSD2_LAYERS: soil units of each
mapping unit with their SHARE; layer D1 = topsoil 0-20 cm). Licence CC BY-NC-SA 3.0 IGO (see data/sources.csv).

Classes (data/hwsd2_sio2008_class_mapping.csv, codes of the HWSD2 lookup tables D_ROOT_DEPTH, D_TEXTURE_USDA and
D_DRAINAGE): soil depth 90, 60 or 30 cm from the rootable soil depth ROOT_DEPTH; texture clay, silty, loam or sandy from
the USDA texture class of D1 (footnotes (1)-(4) of Taula 6); drainage group well, moderately_well or poorly from the
reference soil drainage class DRAINAGE. 3 x 4 x 3 = 36 classes, column share_d<depth>_<texture>_<drainage>.

Method (weighting of hwsd2_soil.csv, decisions L60 and L63):
1. Soil units with data in D1 (the units left out by build_hwsd_soil.py: rock outcrops, water bodies and other units
   without values) and with a rootable depth, a USDA texture and a drainage class; the others are left out.
2. Mapping unit = SHARE-weighted shares of the classes of its soil units (renormalised over the units kept).
3. SPAM cell (1/12 degree = 10 x 10 HWSD cells) = mean of the HWSD cells with data; then the weighted mean over the
   SPAM physical area of the crop in the country (spam_grid.py). The shares of a row sum to 1.
HWSD2.mdb is extracted to --workdir (about 90 MB) and deleted after use; it is read with the Microsoft Access ODBC
driver (pyodbc).

Usage (repository root, build environment):
    .venv-gis\\Scripts\\python scripts\\build_hwsd_leaching_soil.py --workdir DIR [--grid-cache FILE]
"""
import argparse
import zipfile
from pathlib import Path

import numpy as np
import pyodbc

import spam_grid
from build_hwsd_soil import DB_ZIP, HWSD_COLS, NODATA, RASTER_ZIP, BLOCK

OUTPUT = spam_grid.DATA_DIR / "hwsd2_leaching_soil_shares.csv"
MAPPING = "hwsd2_sio2008_class_mapping.csv"
DEPTHS = ("90", "60", "30")
TEXTURES = ("clay", "silty", "loam", "sandy")
DRAINAGE_GROUPS = ("well", "moderately_well", "poorly")
CLASSES = ["share_d%s_%s_%s" % (d, t, g) for d in DEPTHS for t in TEXTURES for g in DRAINAGE_GROUPS]


def class_mapping():
    """{variable: {hwsd_code (str): class}} of hwsd2_sio2008_class_mapping.csv."""
    out = {}
    for row in spam_grid.read_csv(MAPPING):
        out.setdefault(row["variable"], {})[row["hwsd_code"]] = row["sio2008_class"]
    return out


def mapping_unit_table(mdb_path):
    """Array [mapping unit id, class] of the SHARE-weighted class shares, NaN for units without data."""
    mapping = class_mapping()
    index = {name: i for i, name in enumerate(CLASSES)}
    connection = pyodbc.connect(r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=" + str(mdb_path))
    sums, weights = {}, {}
    for smu, share, root_depth, drainage, texture, *values in connection.cursor().execute(
            "SELECT HWSD2_SMU_ID, SHARE, ROOT_DEPTH, DRAINAGE, TEXTURE_USDA, CLAY, SILT, SAND, COARSE, ORG_CARBON, "
            "PH_WATER FROM HWSD2_LAYERS WHERE LAYER = 'D1'"):
        # same soil units as hwsd2_soil.csv (D1 with values), plus the three class variables
        if any(v is None or v < 0 for v in values + [texture]) or not share:
            continue
        if root_depth is None or drainage is None:
            continue
        name = "share_d%s_%s_%s" % (mapping["root_depth"][str(int(root_depth))],
                                    mapping["texture_usda"][str(int(texture))],
                                    mapping["drainage"][drainage.strip()])
        vector = sums.setdefault(smu, np.zeros(len(CLASSES)))
        vector[index[name]] += share
        weights[smu] = weights.get(smu, 0.0) + share
    connection.close()
    table = np.full((NODATA + 1, len(CLASSES)), np.nan, dtype=np.float32)
    for smu, vector in sums.items():
        table[smu] = vector / weights[smu]
    return table


def spam_cell_means(table):
    """[class] arrays on the SPAM grid: mean of the HWSD cells with data in each SPAM cell (as build_hwsd_soil.py)."""
    n = len(CLASSES)
    out = np.full((n, spam_grid.ROWS, spam_grid.COLS), np.nan, dtype=np.float32)
    row_bytes = HWSD_COLS * 2
    with zipfile.ZipFile(RASTER_ZIP) as zf, zf.open("HWSD2.bil") as raster:
        for r in range(spam_grid.ROWS):
            ids = np.frombuffer(raster.read(BLOCK * row_bytes), dtype="<u2").reshape(BLOCK, HWSD_COLS)
            values = table[ids]  # BLOCK x HWSD_COLS x classes
            valid = np.isfinite(values[..., 0])
            blocks = np.where(valid[..., None], values, 0.0).reshape(BLOCK, spam_grid.COLS, BLOCK, n)
            total = blocks.sum(axis=(0, 2), dtype=np.float64)
            count = valid.reshape(BLOCK, spam_grid.COLS, BLOCK).sum(axis=(0, 2))
            with np.errstate(invalid="ignore", divide="ignore"):
                out[:, r, :] = np.where(count[:, None] > 0, total / count[:, None], np.nan).T
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", required=True, help="folder for the extracted HWSD2.mdb")
    parser.add_argument("--grid-cache", help="npy file to store or reuse the country grid")
    args = parser.parse_args()
    grid, countries = spam_grid.country_grid(args.grid_cache)
    with zipfile.ZipFile(DB_ZIP) as zf:
        path = Path(zf.extract("HWSD2.mdb", args.workdir)).resolve()
    try:
        table = mapping_unit_table(path)
    finally:
        path.unlink()
    maps = spam_cell_means(table)
    rows = spam_grid.weighted_country_means(dict(zip(CLASSES, maps)), grid, countries,
                                            spam_grid.read_csv("spam2020_crop_mapping.csv"))
    columns = ["crop", "country", "weights", "area_ha", "coverage"] + CLASSES
    digits = dict({"area_ha": 0, "coverage": 4}, **{name: 6 for name in CLASSES})
    spam_grid.write_rows(OUTPUT, rows, columns, digits)
    print("written %s (%d rows)" % (OUTPUT.relative_to(spam_grid.ROOT), len(rows)))


if __name__ == "__main__":
    main()
