from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.backtesting import run_backtest_for_symbols
from agi_style_forex_bot_mt5.calibration import effective_profile_config, profile_allowed_for_shadow
from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.real_data_research import RealDataResearchConfig, run_real_data_research


def test_config_validate_accepts_balanced_stable_with_profile_config(tmp_path: Path) -> None:
    ini = _stable_ini(tmp_path)
    cfg = BotConfig(signal_profile="BALANCED_STABLE", profile_config=str(ini), stability_filters_applied=True, profile_type="RESEARCH_BACKTEST_ONLY", requires_robustness_rerun=True)

    cfg.validate_safety()


def test_balanced_stable_without_profile_config_fails_safely() -> None:
    with pytest.raises(ValueError, match="STABLE_PROFILE_CONFIG_REQUIRED"):
        BotConfig(signal_profile="BALANCED_STABLE").validate_safety()


def test_run_real_data_research_balanced_stable_without_config_returns_safe_json() -> None:
    cfg = RealDataResearchConfig(symbols=("EURUSD",), signal_profile="BALANCED_STABLE", quick=True)

    summary = run_real_data_research(cfg)

    assert summary["classification"] == "STABLE_PROFILE_CONFIG_REQUIRED"
    assert summary["execution_attempted"] is False


def test_effective_profile_hash_differs_from_balanced_with_filters(tmp_path: Path) -> None:
    ini = _stable_ini(tmp_path, disabled_symbols="GBPUSD")

    balanced = effective_profile_config("BALANCED")
    stable = effective_profile_config("BALANCED_STABLE", profile_config=ini)

    assert stable.profile_hash != balanced.profile_hash
    assert stable.filters["disabled_symbols"] == ["GBPUSD"]
    assert stable.allowed_for_shadow is False
    assert stable.not_for_demo_live is True


def test_real_data_research_accepts_balanced_stable_with_profile_config(tmp_path: Path) -> None:
    ini = _stable_ini(tmp_path)
    cfg = RealDataResearchConfig(symbols=("EURUSD",), output_root=str(tmp_path / "runs"), run_id="stable-run", signal_profile="BALANCED_STABLE", profile_config=str(ini), quick=True)

    summary = run_real_data_research(cfg, stage_overrides=_quick_stage_overrides())

    assert summary["signal_profile_used"] == "BALANCED_STABLE"
    assert summary["stable_filters_applied"]["enabled"] is True
    assert summary["profile_not_for_demo_live"] is True
    assert summary["execution_attempted"] is False


def test_balanced_stable_generates_stable_blockers(tmp_path: Path) -> None:
    data_dir = tmp_path / "historical"
    data_dir.mkdir()
    _history().to_csv(data_dir / "EURUSD_M5.csv", index=False)
    ini = _stable_ini(tmp_path, disabled_symbols="EURUSD")
    cfg = BotConfig(signal_profile="BALANCED_STABLE", profile_config=str(ini), stability_filters_applied=True, profile_type="RESEARCH_BACKTEST_ONLY", requires_robustness_rerun=True)

    result = run_backtest_for_symbols(data_dir=data_dir, symbols=("EURUSD",), config=cfg)

    blockers = {item["blocking_reason"] for item in result.summary["top_blocking_reasons"]}
    assert "STABLE_SYMBOL_DISABLED" in blockers
    assert result.summary["execution_attempted"] is False


def test_balanced_stable_not_allowed_for_shadow() -> None:
    assert profile_allowed_for_shadow("BALANCED_STABLE") is False


def test_cli_real_data_research_accepts_balanced_stable_with_config(tmp_path: Path, monkeypatch, capsys) -> None:
    ini = _stable_ini(tmp_path)

    def fake_run(config, *, bot_config=None, stage_overrides=None):
        return {"mode": "real-data-research", "signal_profile_used": config.signal_profile, "profile_config": config.profile_config, "execution_attempted": False, "order_send_called": False, "order_check_called": False}

    monkeypatch.setattr(cli, "run_real_data_research", fake_run)
    assert cli.main(["--mode", "real-data-research", "--symbols", "EURUSD", "--signal-profile", "BALANCED_STABLE", "--profile-config", str(ini), "--quick"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["signal_profile_used"] == "BALANCED_STABLE"
    assert payload["execution_attempted"] is False
    assert payload["order_send_called"] is False
    assert payload["order_check_called"] is False


def _stable_ini(tmp_path: Path, *, disabled_symbols: str = "") -> Path:
    path = tmp_path / "balanced_stable.ini"
    path.write_text(
        "\n".join(
            [
                "SIGNAL_PROFILE=BALANCED_STABLE",
                "PROFILE_TYPE=RESEARCH_BACKTEST_ONLY",
                "NOT_FOR_DEMO_LIVE=true",
                "REQUIRES_ROBUSTNESS_RERUN=true",
                "APPLY_STABILITY_FILTERS=true",
                f"DISABLED_SYMBOLS={disabled_symbols}",
                "DISABLED_STRATEGIES=mean_reversion",
                "BLOCKED_SESSIONS=ROLLOVER",
                "BLOCKED_REGIMES=HIGH_VOLATILITY",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _quick_stage_overrides():
    base = {"classification": "OK", "reports_created": [], "execution_attempted": False}
    return {
        "MT5_DIAGNOSE": lambda: {**base, "mt5_connected": True},
        "EXPORT_HISTORY": lambda: {**base, "symbols_exported": 1},
        "HISTORICAL_DATA_AUDIT": lambda: {**base, "feature_availability": {"classification": "OK"}},
        "DATA_CONTRACT_AUDIT": lambda: {**base, "data_contract_status": "OK"},
        "STRATEGY_DIAGNOSE": lambda: base,
        "BACKTEST": lambda: {**base, "total_trades": 0, "signals_generated": 0, "trades_generated": 0, "sample_status": "LOW_SAMPLE"},
    }


def _history() -> pd.DataFrame:
    rows = []
    base = pd.Timestamp("2024-01-01T00:00:00Z")
    for index in range(260):
        price = 1.10 + index * 0.00001
        rows.append(
            {
                "time": (base + pd.Timedelta(minutes=5 * index)).isoformat(),
                "open": price,
                "high": price + 0.0002,
                "low": price - 0.0002,
                "close": price + 0.00005,
                "tick_volume": 100,
                "spread": 10,
            }
        )
    return pd.DataFrame(rows)
