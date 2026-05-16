"""Command line entry point for shadow/demo runs."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .bot import ShadowDemoBot
from .config import load_config
from .contracts import AccountState, MarketSnapshot, utc_now
from .mt5_data_bot import MT5DataOnlyBot, summary_to_json
from .telemetry import JsonlAuditLogger, TelegramNotifier, TelemetryDatabase


def build_sample_snapshot() -> MarketSnapshot:
    """Build a deterministic demo snapshot for smoke testing."""

    return MarketSnapshot(
        symbol="EURUSD",
        timeframe="M5",
        timestamp_utc=utc_now(),
        bid=1.10000,
        ask=1.10010,
        spread_points=10,
        digits=5,
        point=0.00001,
        tick_value=1.0,
        tick_size=0.00001,
        volume_min=0.01,
        volume_max=100,
        volume_step=0.01,
        stops_level_points=10,
        freeze_level_points=5,
    )


def build_sample_features() -> dict[str, object]:
    """Build deterministic trend-pullback features for a shadow smoke run."""

    return {
        "regime": "TREND_UP",
        "ema20": 1.1010,
        "ema50": 1.1000,
        "ema200": 1.0980,
        "ema_fast": 1.10130,
        "ema_slow": 1.10030,
        "rsi": 48,
        "rsi14": 48,
        "atr14": 0.0010,
        "atr": 0.0010,
        "atr_points": 18,
        "atr_mean_points": 12,
        "atr_percent": 0.09,
        "ema_slope": 0.0002,
        "trend_slope": 0.00030,
        "trend_strength": 1.4,
        "momentum": 0.0004,
        "momentum_points": 12,
        "range_points": 25,
        "body_ratio": 0.62,
        "previous_close": 1.10080,
        "close": 1.10120,
        "prior_high": 1.10100,
        "lower_wick": 0.0003,
        "upper_wick": 0.0001,
        "spread_points": 10,
        "max_strategy_spread_points": 25,
        "session": "LONDON",
        "volatility": 0.0002,
    }


def main(argv: list[str] | None = None) -> int:
    """Run one shadow/demo cycle and print a JSON summary."""

    parser = argparse.ArgumentParser(description="Run AGI_STYLE_FOREX_BOT_MT5 safely.")
    parser.add_argument("--config", type=Path, default=None, help="Path to config INI.")
    parser.add_argument("--mode", choices=["shadow", "demo", "mt5-data"], default="shadow")
    parser.add_argument("--log-dir", type=Path, default=Path("data/logs"))
    parser.add_argument("--sqlite", type=Path, default=None, help="Optional telemetry SQLite path.")
    parser.add_argument("--symbols", default="EURUSD", help="Comma-separated symbols for mt5-data.")
    parser.add_argument("--bars", type=int, default=260, help="Bars per timeframe for mt5-data.")
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Enable optional Telegram notifications using TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if args.mode == "mt5-data" and args.sqlite is None:
        parser.error("--mode mt5-data requires --sqlite for durable shadow-order audit")
    database = TelemetryDatabase(args.sqlite) if args.sqlite else None
    try:
        if args.mode == "mt5-data":
            bot = MT5DataOnlyBot(
                config=config,
                symbols=tuple(item.strip() for item in args.symbols.split(",") if item.strip()),
                bars=args.bars,
                audit_logger=JsonlAuditLogger(args.log_dir, max_file_mb=config.max_jsonl_file_mb),
                database=database,
                telegram_notifier=TelegramNotifier.from_env(
                    database=database,
                    enabled=bool(args.telegram or config.telegram_enabled),
                ),
            )
            print(summary_to_json(bot.run()))
            return 0

        bot = ShadowDemoBot(
            config=config,
            audit_logger=JsonlAuditLogger(args.log_dir, max_file_mb=config.max_jsonl_file_mb),
            database=database,
            telegram_notifier=TelegramNotifier.from_env(
                database=database,
                enabled=bool(args.telegram or config.telegram_enabled),
            ),
        )
        result = bot.run_once(
            snapshot=build_sample_snapshot(),
            features=build_sample_features(),
            account=AccountState(
                login=100001,
                trade_mode="DEMO",
                balance=10_000,
                equity=10_000,
                margin_free=9_000,
                is_demo=True,
                trade_allowed=True,
            ),
            mode=args.mode,
        )
        print(json.dumps(asdict(result), ensure_ascii=True, sort_keys=True))
        return 0
    finally:
        if database is not None:
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())
