"""FASE 80 - core invariants and deterministic runtime foundation.

Covers the four cross-cutting contracts introduced in this phase (SafetyEnvelope,
WorkspacePaths, Clock, RunManifest) plus the three properties they exist to
guarantee: CWD independence, run reproducibility, and no writes to production
evidence during the test session.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from agi_style_forex_bot_mt5.backtesting import run_backtest_for_symbols
from agi_style_forex_bot_mt5.config import BotConfig, load_config
from agi_style_forex_bot_mt5.core import (
    DATA_ROOT_ENV,
    FULL_SAFETY_FLAGS,
    PROJECT_ROOT_ENV,
    REQUIRED_SAFETY_FLAGS,
    FrozenClock,
    RunManifest,
    SafetyEnvelope,
    SafetyInvariantError,
    SystemClock,
    WorkspacePaths,
    assert_safety_flags,
    hash_config,
    hash_paths,
    redact_mapping,
    resolve_clock,
    seal_report,
    workspace_paths,
)
from agi_style_forex_bot_mt5.operational_readiness.operator_drill import run_dry_run_market_open
from agi_style_forex_bot_mt5.persistence import create_backup
from agi_style_forex_bot_mt5.telemetry import TelemetryDatabase

from conftest import baseline_production_fingerprint, production_data_fingerprint

FROZEN = datetime(2026, 9, 4, 18, 30, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- SafetyEnvelope


def test_envelope_default_is_paper_only() -> None:
    envelope = SafetyEnvelope()
    assert envelope.paper_only is True
    assert envelope.as_dict() == {
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
        "demo_only": True,
        "live_trading_approved": False,
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"order_send_called": True},
        {"order_check_called": True},
        {"order_send_called": True, "order_check_called": True},
    ],
)
def test_envelope_rejects_order_calls_without_execution_attempt(kwargs: dict[str, bool]) -> None:
    with pytest.raises(SafetyInvariantError):
        SafetyEnvelope(**kwargs)


def test_envelope_rejects_live_approval_while_demo_only() -> None:
    with pytest.raises(SafetyInvariantError):
        SafetyEnvelope(demo_only=True, live_trading_approved=True)


def test_envelope_rejects_non_boolean_flags() -> None:
    with pytest.raises(SafetyInvariantError):
        SafetyEnvelope(execution_attempted="false")  # type: ignore[arg-type]


def test_seal_overrides_a_contradictory_copied_literal() -> None:
    sealed = seal_report({"mode": "audit", "execution_attempted": True})
    assert sealed["execution_attempted"] is False
    assert sealed["mode"] == "audit"


def test_seal_full_includes_demo_and_approval_flags() -> None:
    sealed = seal_report({"mode": "gate"}, full=True)
    assert set(FULL_SAFETY_FLAGS).issubset(sealed)
    assert sealed["demo_only"] is True
    assert sealed["live_trading_approved"] is False


def test_assert_safety_flags_rejects_report_missing_a_flag() -> None:
    payload = {"mode": "gate", "execution_attempted": False, "order_send_called": False}
    with pytest.raises(SafetyInvariantError) as excinfo:
        assert_safety_flags(payload, context="gate report")
    assert "order_check_called" in str(excinfo.value)


def test_assert_safety_flags_rejects_a_report_claiming_execution() -> None:
    payload = {flag: True for flag in REQUIRED_SAFETY_FLAGS}
    with pytest.raises(SafetyInvariantError):
        assert_safety_flags(payload, context="gate report")


def test_envelope_from_config_reflects_bot_config() -> None:
    envelope = SafetyEnvelope.from_config(BotConfig())
    assert envelope.demo_only is True
    assert envelope.live_trading_approved is False
    assert envelope.paper_only is True


# --------------------------------------------------------------------------- WorkspacePaths


def test_project_root_is_independent_of_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before = workspace_paths().project_root
    monkeypatch.chdir(tmp_path)
    assert workspace_paths().project_root == before
    assert (before / "pyproject.toml").exists()


def test_data_root_follows_environment_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DATA_ROOT_ENV, str(tmp_path / "sandbox_data"))
    paths = workspace_paths()
    assert paths.data_root == (tmp_path / "sandbox_data").resolve()
    assert paths.sqlite_dir == paths.data_root / "sqlite"
    assert paths.logs_dir == paths.data_root / "logs"
    assert paths.reports_dir == paths.data_root / "reports"
    assert paths.runtime_dir == paths.data_root / "runtime"
    assert paths.backups_dir == paths.data_root / "backups"


def test_explicit_roots_win_over_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PROJECT_ROOT_ENV, str(tmp_path / "ignored"))
    monkeypatch.setenv(DATA_ROOT_ENV, str(tmp_path / "ignored_data"))
    paths = WorkspacePaths.resolve(project_root=tmp_path / "proj", data_root=tmp_path / "evidence")
    assert paths.project_root == (tmp_path / "proj").resolve()
    assert paths.data_root == (tmp_path / "evidence").resolve()


def test_resolve_path_splits_data_from_project(tmp_path: Path) -> None:
    paths = WorkspacePaths.resolve(project_root=tmp_path / "proj", data_root=tmp_path / "evidence")
    assert paths.resolve_path("data/reports/x") == paths.data_root / "reports" / "x"
    assert paths.resolve_path("data") == paths.data_root
    assert paths.resolve_path("scripts/run.ps1") == paths.project_root / "scripts" / "run.ps1"
    absolute = (tmp_path / "elsewhere" / "f.json").resolve()
    assert paths.resolve_path(absolute) == absolute


# --------------------------------------------------------------------------- Clock


def test_frozen_clock_is_stable_and_utc() -> None:
    clock = FrozenClock(FROZEN)
    assert clock.now_utc() == clock.now_utc() == FROZEN
    assert clock.current_operational_day().isoformat() == "2026-09-04"
    assert clock.current_operational_day_iso() == "2026-09-04"


def test_frozen_clock_normalizes_to_utc_and_advances() -> None:
    clock = FrozenClock(datetime(2026, 9, 4, 21, 30, tzinfo=timezone(timedelta(hours=3))))
    assert clock.now_utc() == FROZEN
    clock.advance(timedelta(days=1))
    assert clock.current_operational_day_iso() == "2026-09-05"


def test_frozen_clock_requires_timezone_aware_instant() -> None:
    with pytest.raises(ValueError):
        FrozenClock(datetime(2026, 9, 4, 18, 30))


def test_resolve_clock_defaults_to_system_clock() -> None:
    assert isinstance(resolve_clock(None), SystemClock)
    frozen = FrozenClock(FROZEN)
    assert resolve_clock(frozen) is frozen


def test_system_clock_is_timezone_aware_utc() -> None:
    now = SystemClock().now_utc()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


# --------------------------------------------------------------------------- RunManifest


def _manifest(clock: FrozenClock, **overrides) -> RunManifest:
    kwargs = {
        "mode": "backtest",
        "clock": clock,
        "config": {"profile": "BALANCED_STABLE_MICRO_V2", "risk_pct": 0.25},
        "symbols": ["EURUSD", "GBPUSD"],
        "timeframe": "M5",
        "seed": 42,
    }
    kwargs.update(overrides)
    return RunManifest.build(**kwargs)


def test_manifest_is_reproducible_for_identical_inputs() -> None:
    clock = FrozenClock(FROZEN)
    assert _manifest(clock).as_dict() == _manifest(FrozenClock(FROZEN)).as_dict()


def test_manifest_run_id_changes_with_seed_config_and_time() -> None:
    clock = FrozenClock(FROZEN)
    base = _manifest(clock).run_id
    assert _manifest(clock, seed=43).run_id != base
    assert _manifest(clock, config={"profile": "OTHER"}).run_id != base
    assert _manifest(FrozenClock(FROZEN + timedelta(seconds=1))).run_id != base


def test_manifest_records_required_provenance() -> None:
    manifest = _manifest(FrozenClock(FROZEN)).as_dict()
    for key in (
        "manifest_version",
        "mode",
        "run_id",
        "git_commit_sha",
        "project_root",
        "data_root",
        "config_hash",
        "reference_time_utc",
        "python_version",
        "package_versions",
        "symbols",
        "timeframe",
        "seed",
        "safety",
    ):
        assert key in manifest
    assert manifest["reference_time_utc"] == FROZEN.isoformat()
    assert manifest["symbols"] == ["EURUSD", "GBPUSD"]
    assert manifest["safety"]["execution_attempted"] is False


def test_manifest_never_carries_secrets() -> None:
    secret_config = {
        "profile": "BALANCED_STABLE_MICRO_V2",
        "telegram_bot_token": "SUPER_SECRET_TOKEN",
        "mt5_password": "hunter2",
        "chat_id": "123456",
        "nested": {"api_key": "AKIA_SECRET"},
    }
    serialized = json.dumps(_manifest(FrozenClock(FROZEN), config=secret_config).as_dict())
    for secret in ("SUPER_SECRET_TOKEN", "hunter2", "123456", "AKIA_SECRET"):
        assert secret not in serialized
    assert "telegram_bot_token" not in redact_mapping(secret_config)
    assert redact_mapping(secret_config)["profile"] == "BALANCED_STABLE_MICRO_V2"


def test_config_hash_ignores_secret_values_only() -> None:
    base = {"profile": "A", "telegram_bot_token": "one"}
    same_but_new_secret = {"profile": "A", "telegram_bot_token": "two"}
    different_profile = {"profile": "B", "telegram_bot_token": "one"}
    assert hash_config(base) == hash_config(same_but_new_secret)
    assert hash_config(base) != hash_config(different_profile)


def test_dataset_hash_tracks_file_content(tmp_path: Path) -> None:
    dataset = tmp_path / "EURUSD_M5.csv"
    dataset.write_text("time,open\n2026-01-01T00:00:00Z,1.1\n", encoding="utf-8")
    first = hash_paths([dataset])
    assert first == hash_paths([dataset])
    dataset.write_text("time,open\n2026-01-01T00:00:00Z,1.2\n", encoding="utf-8")
    assert hash_paths([dataset]) != first
    assert hash_paths([tmp_path / "missing.csv"]) != first


def test_manifest_attach_seals_safety_flags() -> None:
    attached = _manifest(FrozenClock(FROZEN)).attach({"mode": "backtest", "execution_attempted": True})
    assert attached["execution_attempted"] is False
    assert attached["run_manifest"]["mode"] == "backtest"
    assert_safety_flags(attached, context="attached report")


# --------------------------------------------------------------------------- operator drill / CWD independence


def _readiness_fixture(tmp_path: Path) -> tuple[Path, Path]:
    reports = tmp_path / "reports"
    for relative in (
        "market_open_checklist/commands.ps1",
        "ec2_deployment_pack/EC2_COMMANDS.ps1",
        "stable_gate/stable_gate_summary.json",
        "stability_repair/balanced_stable.ini",
    ):
        target = reports / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")
    sqlite = tmp_path / "forward.sqlite3"
    database = TelemetryDatabase(sqlite)
    try:
        database.set_shadow_paused(True, reason="weekend", paused_by="test")
    finally:
        database.close()
    return reports, sqlite


def test_operator_drill_verdict_is_identical_from_any_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reports, sqlite = _readiness_fixture(tmp_path)
    first = run_dry_run_market_open(sqlite_path=sqlite, reports_root=reports, output_dir=tmp_path / "out_a", config=BotConfig())

    other_cwd = tmp_path / "somewhere_else"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    second = run_dry_run_market_open(sqlite_path=sqlite, reports_root=reports, output_dir=tmp_path / "out_b", config=BotConfig())

    assert first["classification"] == second["classification"] == "DRY_RUN_MARKET_OPEN_READY"
    assert [check["check_name"] for check in first["checks"]] == [check["check_name"] for check in second["checks"]]
    assert [check["status"] for check in first["checks"]] == [check["status"] for check in second["checks"]]
    assert_safety_flags(first, context="dry-run market open")
    assert_safety_flags(second, context="dry-run market open")


def test_operator_drill_script_checks_resolve_from_project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reports, sqlite = _readiness_fixture(tmp_path)
    monkeypatch.chdir(tmp_path)
    summary = run_dry_run_market_open(sqlite_path=sqlite, reports_root=reports, output_dir=tmp_path / "out", config=BotConfig())
    script_checks = [check for check in summary["checks"] if check["check_name"].startswith("script_")]
    assert script_checks
    assert all(check["status"] == "PASS" for check in script_checks)
    assert all(str(workspace_paths().scripts_dir) in check["detail"] for check in script_checks)


def test_operator_drill_accepts_an_injected_workspace(tmp_path: Path) -> None:
    reports, sqlite = _readiness_fixture(tmp_path)
    empty_project = tmp_path / "empty_project"
    empty_project.mkdir()
    summary = run_dry_run_market_open(
        sqlite_path=sqlite,
        reports_root=reports,
        output_dir=tmp_path / "out",
        config=BotConfig(),
        workspace=WorkspacePaths.resolve(project_root=empty_project, data_root=tmp_path / "data"),
    )
    script_checks = [check for check in summary["checks"] if check["check_name"].startswith("script_")]
    assert all(check["status"] == "FAIL" for check in script_checks)
    assert summary["classification"] == "DRY_RUN_MARKET_OPEN_BLOCKED"


# --------------------------------------------------------------------------- reproducibility


def _historical_csv(path: Path, *, rows: int = 260) -> None:
    timestamps = pd.date_range("2026-01-01", periods=rows, freq="5min", tz="UTC")
    price = 1.1000
    rows_out = []
    for index, timestamp in enumerate(timestamps):
        price += 0.00005
        open_ = price
        close = price + (0.00003 if index % 2 == 0 else -0.00002)
        rows_out.append(
            {
                "time": timestamp.isoformat(),
                "open": open_,
                "high": max(open_, close) + 0.00010,
                "low": min(open_, close) - 0.00010,
                "close": close,
                "tick_volume": 1000 + index,
                "spread": 10,
            }
        )
    pd.DataFrame(rows_out).to_csv(path, index=False)


def test_same_dataset_config_clock_and_seed_reproduce_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "historical"
    data_dir.mkdir()
    dataset = data_dir / "EURUSD_M5.csv"
    _historical_csv(dataset)
    clock = FrozenClock(FROZEN)

    first = run_backtest_for_symbols(data_dir=data_dir, symbols=("EURUSD",), report_dir=tmp_path / "reports_a")
    manifest_a = RunManifest.build(mode="backtest", clock=clock, config={"profile": "TEST"}, dataset_paths=[dataset], symbols=["EURUSD"], timeframe="M5", seed=7)

    # A different working directory must not change either the decision or the manifest.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    second = run_backtest_for_symbols(data_dir=data_dir, symbols=("EURUSD",), report_dir=tmp_path / "reports_b")
    manifest_b = RunManifest.build(mode="backtest", clock=FrozenClock(FROZEN), config={"profile": "TEST"}, dataset_paths=[dataset], symbols=["EURUSD"], timeframe="M5", seed=7)

    decision_keys = ("mode", "trades", "win_rate", "profit_factor", "expectancy", "max_drawdown_pct", "net_profit")
    assert {key: first.summary.get(key) for key in decision_keys} == {key: second.summary.get(key) for key in decision_keys}
    assert manifest_a.as_dict() == manifest_b.as_dict()
    assert manifest_a.dataset_hash == hash_paths([dataset]) != ""
    assert first.summary["execution_attempted"] is False
    assert second.summary["execution_attempted"] is False


def test_manifest_dataset_hash_detects_a_changed_dataset(tmp_path: Path) -> None:
    dataset = tmp_path / "EURUSD_M5.csv"
    _historical_csv(dataset, rows=60)
    before = RunManifest.build(mode="backtest", clock=FrozenClock(FROZEN), dataset_paths=[dataset], seed=1)
    _historical_csv(dataset, rows=61)
    after = RunManifest.build(mode="backtest", clock=FrozenClock(FROZEN), dataset_paths=[dataset], seed=1)
    assert before.dataset_hash != after.dataset_hash
    assert before.run_id != after.run_id


# --------------------------------------------------------------------------- no production writes


def test_session_runs_outside_the_repository() -> None:
    assert Path.cwd() != workspace_paths().project_root
    assert os.environ[DATA_ROOT_ENV]
    assert workspace_paths().data_root != workspace_paths().project_root / "data"


def test_production_evidence_is_untouched_by_the_test_session() -> None:
    assert production_data_fingerprint() == baseline_production_fingerprint()


def test_default_backup_never_writes_into_production_data(tmp_path: Path) -> None:
    production_backups = workspace_paths().project_root / "data" / "backups"
    before = sorted(path.name for path in production_backups.glob("*")) if production_backups.exists() else []

    source = tmp_path / "forward.sqlite3"
    TelemetryDatabase(source).close()
    report = create_backup(sqlite_path=source, log_dir=None)

    after = sorted(path.name for path in production_backups.glob("*")) if production_backups.exists() else []
    assert before == after
    assert report["backup_files"]
    assert all(str(workspace_paths().data_root) in path for path in report["backup_files"])
    assert_safety_flags(report, context="backup report")


def test_backup_rotation_stays_inside_the_injected_workspace(tmp_path: Path) -> None:
    workspace = WorkspacePaths.resolve(project_root=tmp_path / "proj", data_root=tmp_path / "evidence")
    source = tmp_path / "forward.sqlite3"
    TelemetryDatabase(source).close()
    for minute in range(3):
        create_backup(
            sqlite_path=source,
            log_dir=None,
            workspace=workspace,
            keep_last=2,
            clock=FrozenClock(FROZEN + timedelta(minutes=minute)),
        )
    kept = sorted(path.name for path in workspace.backups_dir.glob("*.sqlite3"))
    assert len(kept) == 2
    assert not (workspace.project_root / "data").exists()


# --------------------------------------------------------------------------- CLI


def test_core_invariants_cli_reports_the_four_contracts(capsys: pytest.CaptureFixture[str]) -> None:
    from agi_style_forex_bot_mt5.cli import main

    assert main(["--mode", "core-invariants", "--reference-time-utc", "2026-09-04T18:30:00Z"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["workspace"]["project_root"] == str(workspace_paths().project_root)
    assert payload["scripts_dir"] == str(workspace_paths().scripts_dir)
    assert payload["clock_type"] == "FrozenClock"
    assert payload["clock_now_utc"] == "2026-09-04T18:30:00+00:00"
    assert payload["current_operational_day"] == "2026-09-04"
    assert payload["run_manifest"]["manifest_version"]
    assert payload["run_manifest"]["run_id"]
    assert payload["paper_only"] is True
    assert_safety_flags(payload, context="core-invariants CLI")


def test_core_invariants_cli_is_reproducible_across_cwds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from agi_style_forex_bot_mt5.cli import main

    argv = ["--mode", "core-invariants", "--reference-time-utc", "2026-09-04T18:30:00Z"]
    assert main(argv) == 0
    first = json.loads(capsys.readouterr().out)

    elsewhere = tmp_path / "another_cwd"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert main(argv) == 0
    second = json.loads(capsys.readouterr().out)

    assert first["run_manifest"]["run_id"] == second["run_manifest"]["run_id"]
    assert first["workspace"] == second["workspace"]
    assert first["scripts_dir"] == second["scripts_dir"]


# --------------------------------------------------------------------------- global safety


def test_global_safety_defaults_intact() -> None:
    config = load_config(None)
    assert config.demo_only is True
    assert config.live_trading_approved is False
    envelope = SafetyEnvelope.from_config(config)
    assert envelope.paper_only is True
