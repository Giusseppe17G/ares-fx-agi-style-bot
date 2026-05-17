from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from agi_style_forex_bot_mt5 import cli
from agi_style_forex_bot_mt5.real_data_research import load_latest_run_summary
from agi_style_forex_bot_mt5.robustness_validation import run_robustness_fast, run_stable_robustness_gate


def test_robustness_fast_accepts_balanced_stable(tmp_path: Path) -> None:
    run = _write_stable_run(tmp_path, _robust_trades(124))
    ini = _stable_ini(tmp_path)

    summary = run_robustness_fast(
        runs_root=tmp_path / "runs",
        profile_runs_dir=tmp_path / "profile_runs",
        profile="BALANCED_STABLE",
        profile_config=ini,
        output_dir=tmp_path / "robustness",
        simulations=100,
        seed=3,
    )

    assert summary["profile"] == "BALANCED_STABLE"
    assert summary["trades_source"].endswith("trades.csv")
    assert summary["stable_filters_applied"] is True
    assert summary["execution_attempted"] is False
    assert run.exists()


def test_robustness_fast_uses_balanced_stable_final_summary_fallback(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "20260101-000000-real-data-research"
    run.mkdir(parents=True)
    (run / "final_summary_compact.json").write_text(
        json.dumps({"signal_profile_used": "BALANCED_STABLE", "total_trades": 124, "profit_factor": 2.64, "expectancy_r": 0.373, "winrate": 41.94, "execution_attempted": False}),
        encoding="utf-8",
    )

    summary = run_robustness_fast(
        runs_root=tmp_path / "runs",
        profile_runs_dir=tmp_path / "profile_runs",
        profile="BALANCED_STABLE",
        profile_config=_stable_ini(tmp_path),
        output_dir=tmp_path / "robustness",
        simulations=10,
    )

    assert summary["total_trades"] == 124
    assert summary["metrics_source"] == "profile_summary"


def test_stable_robustness_gate_returns_paper_shadow_ready(tmp_path: Path) -> None:
    _write_robustness_summary(tmp_path / "robustness", walk_forward="WALK_FORWARD_WARNING")

    summary = run_stable_robustness_gate(
        runs_root=tmp_path / "runs",
        robustness_dir=tmp_path / "robustness",
        stability_dir=tmp_path / "stability",
        profile="BALANCED_STABLE",
        output_dir=tmp_path / "stable_gate",
    )

    assert summary["stable_gate_decision"] == "PAPER_SHADOW_READY"
    assert summary["paper_shadow_ready"] is True
    assert summary["order_send_called"] is False
    assert summary["order_check_called"] is False


def test_stable_robustness_gate_rejects_critical_walk_forward(tmp_path: Path) -> None:
    _write_robustness_summary(tmp_path / "robustness", walk_forward="NEEDS_MORE_WALK_FORWARD_DATA")

    summary = run_stable_robustness_gate(robustness_dir=tmp_path / "robustness", output_dir=tmp_path / "stable_gate")

    assert summary["stable_gate_decision"] == "NEEDS_STABILITY_REWORK"
    assert summary["execution_attempted"] is False


def test_stable_robustness_gate_rejects_cost_failure(tmp_path: Path) -> None:
    _write_robustness_summary(tmp_path / "robustness", cost="NEEDS_COST_RECALIBRATION")

    summary = run_stable_robustness_gate(robustness_dir=tmp_path / "robustness", output_dir=tmp_path / "stable_gate")

    assert summary["stable_gate_decision"] == "NEEDS_COST_RECALIBRATION"


def test_cli_accepts_stable_robustness_gate(tmp_path: Path, capsys) -> None:
    _write_robustness_summary(tmp_path / "robustness")

    assert cli.main(["--mode", "stable-robustness-gate", "--robustness-dir", str(tmp_path / "robustness"), "--output-dir", str(tmp_path / "stable_gate"), "--profile", "BALANCED_STABLE"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["mode"] == "stable-robustness-gate"
    assert payload["execution_attempted"] is False


def test_scripts_are_balanced_stable_shadow_only() -> None:
    run_script = Path("scripts/run_forward_shadow_balanced_stable.ps1").read_text(encoding="utf-8")
    watchdog = Path("scripts/watchdog_forward_shadow_balanced_stable.ps1").read_text(encoding="utf-8")

    assert "--signal-profile\", \"BALANCED_STABLE" in run_script
    assert "LIVE_TRADING_APPROVED=False" in run_script
    assert "order_send=false" in run_script
    assert "BALANCED_STABLE" in watchdog
    assert "LIVE_TRADING_APPROVED=False" in watchdog


def test_latest_run_summary_includes_stable_gate_decision(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "20260101-000000-real-data-research"
    gate = run / "reports" / "stable_gate"
    gate.mkdir(parents=True)
    (run / "final_summary_compact.json").write_text(json.dumps({"run_id": run.name, "execution_attempted": False}), encoding="utf-8")
    (gate / "stable_gate_summary.json").write_text(
        json.dumps({"stable_gate_decision": "PAPER_SHADOW_READY", "paper_shadow_ready": True, "classification": "PAPER_SHADOW_READY", "execution_attempted": False}),
        encoding="utf-8",
    )

    summary = load_latest_run_summary(tmp_path / "runs")

    assert summary["stable_gate_decision"] == "PAPER_SHADOW_READY"
    assert summary["paper_shadow_ready"] is True
    assert "forward-shadow with BALANCED_STABLE" in summary["recommended_next_action"]


def _write_stable_run(root: Path, trades: pd.DataFrame) -> Path:
    run = root / "runs" / "20260101-000000-real-data-research"
    backtests = run / "reports" / "backtests"
    backtests.mkdir(parents=True)
    trades.to_csv(backtests / "trades.csv", index=False)
    (run / "final_summary_compact.json").write_text(
        json.dumps({"run_id": run.name, "signal_profile_used": "BALANCED_STABLE", "stable_filters_applied": {"enabled": True}, "execution_attempted": False}),
        encoding="utf-8",
    )
    return run


def _write_robustness_summary(path: Path, *, walk_forward: str = "WALK_FORWARD_WARNING", cost: str = "COST_SENSITIVITY_OK") -> None:
    path.mkdir(parents=True, exist_ok=True)
    payload = {
        "profile": "BALANCED_STABLE",
        "stable_filters_applied": True,
        "total_trades": 124,
        "sample_status": "USABLE_SAMPLE",
        "profit_factor": 2.64,
        "expectancy_r": 0.373,
        "winrate": 41.94,
        "monte_carlo_classification": "MONTE_CARLO_OK",
        "stress_classification": "STRESS_WARNING",
        "walk_forward_classification": walk_forward,
        "cost_sensitivity_classification": cost,
        "not_for_demo_live": True,
        "execution_attempted": False,
    }
    (path / "robustness_summary.json").write_text(json.dumps(payload), encoding="utf-8")


def _stable_ini(tmp_path: Path) -> Path:
    path = tmp_path / "balanced_stable.ini"
    path.write_text(
        "\n".join(
            [
                "SIGNAL_PROFILE=BALANCED_STABLE",
                "PROFILE_TYPE=RESEARCH_BACKTEST_ONLY",
                "NOT_FOR_DEMO_LIVE=true",
                "REQUIRES_ROBUSTNESS_RERUN=true",
                "APPLY_STABILITY_FILTERS=true",
                "DISABLED_SYMBOLS=GBPUSD",
                "DISABLED_STRATEGIES=mean_reversion",
                "BLOCKED_SESSIONS=ROLLOVER",
                "BLOCKED_REGIMES=HIGH_VOLATILITY",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _robust_trades(count: int) -> pd.DataFrame:
    rows = []
    for index in range(count):
        rows.append(
            {
                "signal_id": f"s{index}",
                "symbol": "EURUSD" if index % 2 else "USDJPY",
                "strategy_name": "trend_pullback",
                "session": "LONDON",
                "regime": "TREND_UP",
                "entry_time": f"2024-01-{(index % 28) + 1:02d}T00:00:00Z",
                "exit_time": f"2024-01-{(index % 28) + 1:02d}T01:00:00Z",
                "profit": 75.0 if index % 2 == 0 else -25.0,
                "r_multiple": 0.75 if index % 2 == 0 else -0.25,
            }
        )
    return pd.DataFrame(rows)
