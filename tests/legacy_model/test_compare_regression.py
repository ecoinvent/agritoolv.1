"""Decision O13: scripts/compare_regression.py exits non-zero when a case differs from its snapshot (used by the CI).

The snapshots are copied to a temporary folder (--expected-dir); the committed snapshots are never changed.
"""
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

import regression_support as rs

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def compare():
    spec = importlib.util.spec_from_file_location("compare_regression", ROOT / "scripts" / "compare_regression.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def expected_copy(tmp_path):
    for name in rs.case_names():
        shutil.copy(rs.CASES_DIR / (name + ".expected.json"), tmp_path)
    return tmp_path


def _change_one_value(folder, name="wheat_IT"):
    """Multiply the first non-zero numeric value of a snapshot copy by 1.01; return its key."""
    path = folder / (name + ".expected.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    key = next(k for k, v in sorted(data.items()) if isinstance(v, (int, float)) and not isinstance(v, bool) and v)
    data[key] = data[key] * 1.01
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return key


def test_exit_zero_when_the_snapshots_match(compare, expected_copy, capsys):
    assert compare.main(["--expected-dir", str(expected_copy)]) == 0
    out = capsys.readouterr().out
    assert all("=== %s: 0 changed key(s) ===" % name in out for name in rs.case_names())


def test_exit_non_zero_when_a_value_differs(compare, expected_copy, capsys):
    key = _change_one_value(expected_copy)
    assert compare.main(["--expected-dir", str(expected_copy)]) == 1
    out = capsys.readouterr().out
    assert "=== wheat_IT: 1 changed key(s) ===" in out and key in out


def test_exit_non_zero_when_a_snapshot_is_missing(compare, expected_copy):
    (expected_copy / "rice_IN.expected.json").unlink()
    assert compare.main(["--expected-dir", str(expected_copy)]) == 1


def test_keys_restrict_the_exit_status(compare, expected_copy):
    key = _change_one_value(expected_copy)
    other = next(k for k in rs.load_expected("wheat_IT") if k != key)
    assert compare.main(["--expected-dir", str(expected_copy), "--keys", other]) == 0
    assert compare.main(["--expected-dir", str(expected_copy), "--keys", key]) == 1


def test_update_cannot_target_another_folder(compare, expected_copy):
    with pytest.raises(SystemExit):
        compare.main(["--update", "--expected-dir", str(expected_copy)])
