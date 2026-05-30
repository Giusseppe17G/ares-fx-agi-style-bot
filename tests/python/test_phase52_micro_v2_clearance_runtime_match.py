from __future__ import annotations

import json
from pathlib import Path

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.micro_v2_clearance import run_micro_v2_clearance_runtime_check
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase


def test_v2_with_v2_ledger_passes(tmp_path: Path, monkeypatch) -> None:
    paths = _fixture(tmp_path, monkeypatch)
    summary = _run(paths)

    assert summary["micro_v2_clearance_runtime_check_status"] == "MICRO_V2_CLEARANCE_RUNTIME_MATCH_OK"
    assert summary["clearance_profile_match"] is True
    assert summary["requested_profile_canonical"] == "BALANCED_STABLE_MICRO_V2"
    assert summary["cleared_for_profile_canonical"] == "BALANCED_STABLE_MICRO_V2"
    assert summary["execution_attempted"] is False


def test_v2_with_base_ledger_fails(tmp_path: Path, monkeypatch) -> None:
    paths = _fixture(tmp_path, monkeypatch)
    paths["clearance"] = _base_ledger(Path("base_ledger.json"))

    summary = _run(paths)

    assert summary["micro_v2_clearance_runtime_check_status"] in {"MICRO_V2_CLEARANCE_RUNTIME_MATCH_FAILED", "MICRO_V2_CLEARANCE_SCOPE_INVALID"}
    assert summary["clearance_profile_match"] is False


def test_base_with_v2_ledger_fails(tmp_path: Path, monkeypatch) -> None:
    paths = _fixture(tmp_path, monkeypatch)
    paths["signal_profile"] = "BALANCED_STABLE_MICRO"
    paths["profile"] = _base_profile(Path("balanced_stable_micro.ini"))

    summary = _run(paths)

    assert summary["micro_v2_clearance_runtime_check_status"] in {"MICRO_V2_CLEARANCE_RUNTIME_MATCH_FAILED", "MICRO_V2_CLEARANCE_PATH_GUARD_FAILED"}
    assert summary["clearance_profile_match"] is False


def test_v2_ledger_approved_for_demo_true_fails(tmp_path: Path, monkeypatch) -> None:
    paths = _fixture(tmp_path, monkeypatch, ledger_overrides={"approved_for_demo": True})
    summary = _run(paths)
    assert summary["micro_v2_clearance_runtime_check_status"] == "MICRO_V2_CLEARANCE_LEDGER_INVALID"


def test_v2_ledger_approved_for_live_true_fails(tmp_path: Path, monkeypatch) -> None:
    paths = _fixture(tmp_path, monkeypatch, ledger_overrides={"approved_for_live": True})
    summary = _run(paths)
    assert summary["micro_v2_clearance_runtime_check_status"] == "MICRO_V2_CLEARANCE_LEDGER_INVALID"


def test_v2_ledger_wrong_scope_fails(tmp_path: Path, monkeypatch) -> None:
    paths = _fixture(tmp_path, monkeypatch, ledger_overrides={"clearance_scope": "PAPER_SHADOW"})
    summary = _run(paths)
    assert summary["micro_v2_clearance_runtime_check_status"] == "MICRO_V2_CLEARANCE_SCOPE_INVALID"


def test_v2_with_stable_sqlite_fails(tmp_path: Path, monkeypatch) -> None:
    paths = _fixture(tmp_path, monkeypatch)
    paths["sqlite"] = Path("data/sqlite/forward-shadow-stable.sqlite3")
    summary = _run(paths)
    assert summary["micro_v2_clearance_runtime_check_status"] == "MICRO_V2_CLEARANCE_PATH_GUARD_FAILED"


def test_v2_with_stable_log_dir_fails(tmp_path: Path, monkeypatch) -> None:
    paths = _fixture(tmp_path, monkeypatch)
    paths["log_dir"] = Path("data/logs/forward-shadow-stable")
    summary = _run(paths)
    assert summary["micro_v2_clearance_runtime_check_status"] == "MICRO_V2_CLEARANCE_PATH_GUARD_FAILED"


def test_daily_risk_ledger_is_required(tmp_path: Path, monkeypatch) -> None:
    paths = _fixture(tmp_path, monkeypatch)
    paths["daily"] = Path("missing_daily_ledger.json")
    summary = _run(paths)
    assert summary["micro_v2_clearance_runtime_check_status"] == "MICRO_V2_CLEARANCE_RUNTIME_MATCH_FAILED"
    assert summary["blocking_reason"] == "DAILY_RISK_LEDGER_MISSING"


def test_cli_runtime_check_generates_reports(tmp_path: Path, monkeypatch, capsys) -> None:
    paths = _fixture(tmp_path, monkeypatch)
    result = cli.main(
        [
            "--mode",
            "micro-v2-clearance-runtime-check",
            "--sqlite",
            str(paths["sqlite"]),
            "--log-dir",
            str(paths["log_dir"]),
            "--reports-root",
            "data/reports",
            "--signal-profile",
            "BALANCED_STABLE_MICRO_V2",
            "--profile-config",
            str(paths["profile"]),
            "--paper-risk-clearance",
            str(paths["clearance"]),
            "--daily-risk-ledger",
            str(paths["daily"]),
            "--output-dir",
            str(paths["out"]),
        ]
    )
    assert result == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["micro_v2_clearance_runtime_check_status"] == "MICRO_V2_CLEARANCE_RUNTIME_MATCH_OK"
    assert (paths["out"] / "micro_v2_clearance_runtime_check_summary.json").exists()
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_runtime_check_does_not_modify_sqlite_or_ledgers(tmp_path: Path, monkeypatch) -> None:
    paths = _fixture(tmp_path, monkeypatch)
    db = TelemetryDatabase(paths["sqlite"])
    db.close()
    sqlite_before = paths["sqlite"].read_bytes()
    clearance_before = paths["clearance"].read_bytes()
    daily_before = paths["daily"].read_bytes()

    _run(paths)

    assert paths["sqlite"].read_bytes() == sqlite_before
    assert paths["clearance"].read_bytes() == clearance_before
    assert paths["daily"].read_bytes() == daily_before


def _run(paths: dict[str, Path | str]) -> dict[str, object]:
    db = TelemetryDatabase(paths["sqlite"])
    try:
        return run_micro_v2_clearance_runtime_check(
            database=db,
            log_dir=paths["log_dir"],
            reports_root="data/reports",
            signal_profile=str(paths.get("signal_profile", "BALANCED_STABLE_MICRO_V2")),
            profile_config=paths["profile"],
            paper_risk_clearance=paths["clearance"],
            daily_risk_ledger=paths["daily"],
            output_dir=paths["out"],
        )
    finally:
        db.close()


def _fixture(tmp_path: Path, monkeypatch, *, ledger_overrides: dict[str, object] | None = None) -> dict[str, Path]:
    monkeypatch.chdir(tmp_path)
    Path("data/sqlite").mkdir(parents=True)
    Path("data/logs/forward-shadow-v2-dryrun").mkdir(parents=True)
    Path("data/reports").mkdir(parents=True)
    return {
        "sqlite": Path("data/sqlite/forward-shadow-v2-dryrun.sqlite3"),
        "log_dir": Path("data/logs/forward-shadow-v2-dryrun"),
        "profile": _v2_profile(Path("data/reports/paper_risk/balanced_stable_micro_v2.ini")),
        "clearance": _v2_ledger(Path("data/reports/micro_v2_clearance/paper_risk_clearance_v2_ledger.json"), overrides=ledger_overrides),
        "daily": _daily_ledger(Path("data/reports/paper_daily_risk/paper_daily_risk_ledger.json")),
        "out": Path("data/reports/micro_v2_clearance_runtime_check"),
    }


def _v2_profile(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "PROFILE_NAME=BALANCED_STABLE_MICRO_V2",
                "SIGNAL_PROFILE=BALANCED_STABLE_MICRO_V2",
                "PROFILE_TYPE=PAPER_SHADOW_ONLY",
                "PAPER_ONLY=true",
                "NOT_FOR_DEMO_LIVE=true",
                "NOT_FOR_LIVE=true",
                "APPROVED_FOR_PAPER_DRY_RUN_ONLY=true",
                "APPROVED_FOR_DEMO=false",
                "APPROVED_FOR_LIVE=false",
                "REQUIRES_STABLE_GATE=true",
                "REQUIRES_PAPER_RISK_CLEARANCE=true",
                "REQUIRES_DAILY_RISK_LEDGER=true",
                "PAPER_RISK_MULTIPLIER=0.1",
                "MAX_OPEN_PAPER_TRADES=1",
                "MAX_PAPER_TRADES_PER_DAY=3",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _base_profile(path: Path) -> Path:
    path.write_text("SIGNAL_PROFILE=BALANCED_STABLE_MICRO\nPROFILE_TYPE=PAPER_SHADOW_ONLY\nPAPER_ONLY=true\nNOT_FOR_DEMO_LIVE=true\nPAPER_RISK_MULTIPLIER=0.1\nMAX_OPEN_PAPER_TRADES=1\n", encoding="utf-8")
    return path


def _v2_ledger(path: Path, *, overrides: dict[str, object] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "clearance_id": "v2",
        "created_at_utc": "2026-05-30T00:00:00+00:00",
        "cleared_for_profile": "BALANCED_STABLE_MICRO_V2",
        "canonical_cleared_for_profile": "BALANCED_STABLE_MICRO_V2",
        "cleared_for_profile_canonical": "BALANCED_STABLE_MICRO_V2",
        "clearance_scope": "PAPER_DRY_RUN_ONLY",
        "cleared_for_paper_shadow": True,
        "approved_for_demo": False,
        "approved_for_live": False,
        "not_for_demo_live": True,
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
    entry.update(overrides or {})
    path.write_text(json.dumps({"clearances": [entry], "execution_attempted": False}), encoding="utf-8")
    return path


def _base_ledger(path: Path) -> Path:
    path.write_text(json.dumps({"clearances": [{"clearance_id": "base", "created_at_utc": "2026-05-30T00:00:00+00:00", "cleared_for_profile": "BALANCED_STABLE_MICRO", "canonical_cleared_for_profile": "BALANCED_STABLE_MICRO", "cleared_for_paper_shadow": True}]}), encoding="utf-8")
    return path


def _daily_ledger(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"daily_risk_clearances": [{"daily_risk_clearance_id": "daily", "created_at_utc": "2026-05-30T00:01:00+00:00", "cleared_for_profile": "BALANCED_STABLE_MICRO", "cleared_for_paper_shadow": True}]}), encoding="utf-8")
    return path
