"""A diagnostic must identify its own source and expose supplied cost limits."""

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "replay_backtest_correctness.py"
SPEC = importlib.util.spec_from_file_location("correctness_diagnostic", SCRIPT)
DIAGNOSTIC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DIAGNOSTIC)


def test_zero_spreads_are_counted_but_never_certify_costs():
    result = DIAGNOSTIC.spread_observations([0, 0, 2, 8])
    assert result["zero_count"] == 2
    assert result["zero_pct"] == 50
    assert result["maximum_points"] == 8
    assert result["cost_verified"] is False
    assert DIAGNOSTIC.spread_observations([2, 3])["cost_verified"] is False


@pytest.mark.parametrize("values", [[], [-1], [float("nan")], [float("inf")], [float("-inf")]])
def test_invalid_spread_evidence_does_not_become_finite_cost(values):
    with pytest.raises(ValueError):
        DIAGNOSTIC.spread_observations(values)


def test_cli_refuses_to_fall_back_to_an_installed_package(tmp_path):
    output = tmp_path / "output"
    result = subprocess.run([
        sys.executable, "-B", str(SCRIPT), "--source-root", str(tmp_path),
        "--data-dir", str(tmp_path), "--output-dir", str(output), "--code-commit", "invalid",
    ], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert "installed packages are not a fallback" in result.stderr
    assert not output.exists()
