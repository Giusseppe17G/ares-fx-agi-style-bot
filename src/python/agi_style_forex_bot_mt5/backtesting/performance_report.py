"""JSON and CSV report writer for reproducible backtests."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .backtester import BacktestBatchResult, BacktestOutcome


@dataclass(frozen=True)
class ReportArtifacts:
    artifact_dir: str
    summary_json_path: str
    trades_csv_path: str
    equity_curve_csv_path: str
    config_snapshot_json_path: str


class PerformanceReportWriter:
    """Persist backtest outputs as JSON and CSV artifacts."""

    def write(self, outcome: BacktestOutcome, artifact_dir: str | Path) -> ReportArtifacts:
        path = Path(artifact_dir)
        path.mkdir(parents=True, exist_ok=True)
        summary_path = path / "summary.json"
        trades_path = path / "trades.csv"
        equity_path = path / "equity_curve.csv"
        config_path = path / "config_snapshot.json"

        summary = outcome.to_summary_dict()
        project_result = outcome.metrics.to_project_result(
            run_id=outcome.settings.run_id,
            artifact_dir=str(path),
        )
        project_result.update(
            {
                "equity_curve_path": str(equity_path),
                "trades_path": str(trades_path),
                "config_snapshot_path": str(config_path),
                "report_path": str(summary_path),
            }
        )
        summary["project_result"] = project_result
        summary_path.write_text(
            json.dumps(_jsonable(summary), indent=2, sort_keys=True),
            encoding="utf-8",
        )

        trades_frame = outcome.trades_frame()
        if trades_frame.empty:
            trades_frame = pd.DataFrame(columns=["signal_id", "profit", "r_multiple"])
        trades_frame.to_csv(trades_path, index=False)
        outcome.equity_curve.to_csv(equity_path, index=False)
        config_path.write_text(
            json.dumps(_jsonable(asdict(outcome.settings)), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return ReportArtifacts(
            artifact_dir=str(path),
            summary_json_path=str(summary_path),
            trades_csv_path=str(trades_path),
            equity_curve_csv_path=str(equity_path),
            config_snapshot_json_path=str(config_path),
        )


def write_reports(outcome: BacktestOutcome, artifact_dir: str | Path) -> ReportArtifacts:
    return PerformanceReportWriter().write(outcome, artifact_dir)


def write_batch_reports(result: BacktestBatchResult, artifact_dir: str | Path) -> tuple[str, ...]:
    """Persist Phase 4 multi-symbol report artifacts."""

    path = Path(artifact_dir)
    path.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "summary_json": path / "summary.json",
        "summary_csv": path / "summary.csv",
        "trades_csv": path / "trades.csv",
        "equity_curve_csv": path / "equity_curve.csv",
        "by_symbol_csv": path / "by_symbol.csv",
        "by_regime_csv": path / "by_regime.csv",
        "by_session_csv": path / "by_session.csv",
        "by_weekday_csv": path / "by_weekday.csv",
        "by_hour_utc_csv": path / "by_hour_utc.csv",
        "by_setup_quality_csv": path / "by_setup_quality.csv",
        "by_component_score_bucket_csv": path / "by_component_score_bucket.csv",
        "by_blocking_reason_csv": path / "by_blocking_reason.csv",
        "report_html": path / "report.html",
    }
    summary_payload = {
        **dict(result.summary),
        "data_quality": [asdict(item) for item in result.data_quality],
        "strategy_promotion_gate": {
            symbol: asdict(decision) for symbol, decision in result.promotion.items()
        },
        "by_symbol": result.by_symbol.to_dict("records"),
        "by_regime": result.by_regime.to_dict("records"),
        "by_session": result.by_session.to_dict("records"),
        "by_weekday": result.by_weekday.to_dict("records"),
        "by_hour_utc": result.by_hour_utc.to_dict("records"),
    }
    artifacts["summary_json"].write_text(
        json.dumps(_jsonable(summary_payload), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    pd.DataFrame([result.summary]).to_csv(artifacts["summary_csv"], index=False)
    _safe_frame(result.trades).to_csv(artifacts["trades_csv"], index=False)
    _safe_frame(result.equity_curve).to_csv(artifacts["equity_curve_csv"], index=False)
    _safe_frame(result.by_symbol).to_csv(artifacts["by_symbol_csv"], index=False)
    _safe_frame(result.by_regime).to_csv(artifacts["by_regime_csv"], index=False)
    _safe_frame(result.by_session).to_csv(artifacts["by_session_csv"], index=False)
    _safe_frame(result.by_weekday).to_csv(artifacts["by_weekday_csv"], index=False)
    _safe_frame(result.by_hour_utc).to_csv(artifacts["by_hour_utc_csv"], index=False)
    _setup_quality_frame(result.trades).to_csv(artifacts["by_setup_quality_csv"], index=False)
    _component_bucket_frame(result.trades).to_csv(artifacts["by_component_score_bucket_csv"], index=False)
    _blocking_reason_frame(result.trades).to_csv(artifacts["by_blocking_reason_csv"], index=False)
    _write_html_report(result, artifacts["report_html"])
    return tuple(str(item) for item in artifacts.values())


def _safe_frame(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.copy() if frame is not None and not frame.empty else pd.DataFrame()


def _setup_quality_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty or "setup_quality" not in frame.columns:
        return pd.DataFrame(columns=["setup_quality", "trades"])
    return frame.groupby("setup_quality").size().reset_index(name="trades")


def _component_bucket_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["component", "bucket", "trades"])
    return pd.DataFrame(columns=["component", "bucket", "trades"])


def _blocking_reason_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["blocking_reason", "count"])
    return pd.DataFrame(columns=["blocking_reason", "count"])


def _write_html_report(result: BacktestBatchResult, path: Path) -> None:
    summary = dict(result.summary)
    rows = "\n".join(
        f"<tr><th>{key}</th><td>{_jsonable(value)}</td></tr>" for key, value in summary.items()
    )
    promotion_rows = "\n".join(
        f"<tr><td>{symbol}</td><td>{decision.status}</td><td>{'; '.join(decision.reasons)}</td></tr>"
        for symbol, decision in result.promotion.items()
    )
    html = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Backtest Report</title></head>
<body>
<h1>AGI_STYLE_FOREX_BOT_MT5 Backtest Report</h1>
<p>Research-only report. No real or demo orders are enabled.</p>
<h2>Summary</h2>
<table>{rows}</table>
<h2>Strategy Promotion Gate</h2>
<table><tr><th>Symbol</th><th>Status</th><th>Reasons</th></tr>{promotion_rows}</table>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if value == float("inf"):
        return "Infinity"
    if value == float("-inf"):
        return "-Infinity"
    return value
