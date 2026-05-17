"""Configuration loading with fail-closed defaults."""

from __future__ import annotations

from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "defaults.example.ini"


def _coerce(value: str) -> Any:
    lowered = value.strip().lower()
    if lowered in {"true", "yes", "1", "on"}:
        return True
    if lowered in {"false", "no", "0", "off"}:
        return False
    if value.strip() == "":
        return ""
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


@dataclass(frozen=True)
class BotConfig:
    """Runtime configuration with safe defaults."""

    demo_only: bool = True
    live_trading_approved: bool = False
    allowed_account_logins: tuple[int, ...] = ()
    max_open_trades: int = 10
    max_open_risk_pct: float = 5.0
    max_risk_per_trade_pct: float = 0.5
    max_daily_drawdown_pct: float = 3.0
    max_floating_drawdown_pct: float = 5.0
    trading_halted_until_next_day_on_dd: bool = True
    require_sl: bool = True
    require_tp: bool = True
    max_spread_points_default: float = 25.0
    max_market_snapshot_age_seconds: int = 5
    max_signal_age_seconds: int = 30
    max_tick_age_seconds: int = 5
    allow_partial_fill: bool = False
    telegram_enabled: bool = False
    database_enabled: bool = False
    log_retention_days: int = 90
    max_jsonl_file_mb: int = 50
    telegram_outbox_retention_days: int = 30
    shadow_mode: bool = True
    use_market_structure_filters: bool = True
    use_session_levels: bool = True
    use_liquidity_sweep_filters: bool = True
    use_cost_aware_scoring: bool = True
    use_advanced_setup_scoring: bool = True
    min_setup_score_by_strategy: str = ""
    min_setup_score_by_regime: str = ""
    signal_profile: str = "CONSERVATIVE"

    def validate_safety(self) -> None:
        """Raise ValueError when config weakens mandatory safety defaults."""

        if not self.demo_only:
            raise ValueError("DEMO_ONLY must remain True in the initial release")
        if self.live_trading_approved:
            raise ValueError("LIVE_TRADING_APPROVED must remain False in the initial release")
        if self.max_risk_per_trade_pct > 0.5:
            raise ValueError("max risk per trade cannot exceed 0.5%")
        if self.max_open_risk_pct > 5.0:
            raise ValueError("max open risk cannot exceed 5%")
        if not self.require_sl or not self.require_tp:
            raise ValueError("SL and TP must be required")
        if self.signal_profile.upper() not in {"CONSERVATIVE", "BALANCED", "ACTIVE", "RESEARCH_ONLY"}:
            raise ValueError("SIGNAL_PROFILE must be CONSERVATIVE, BALANCED, ACTIVE, or RESEARCH_ONLY")


def load_config(path: str | Path | None = None) -> BotConfig:
    """Load `BotConfig` from an INI-like file without requiring sections."""

    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        cfg = BotConfig()
        cfg.validate_safety()
        return cfg
    raw = "[DEFAULT]\n" + config_path.read_text(encoding="utf-8")
    parser = ConfigParser()
    parser.read_string(raw)
    values = {key.upper(): _coerce(value) for key, value in parser["DEFAULT"].items()}
    allowed = str(values.get("ALLOWED_ACCOUNT_LOGINS", "")).strip()
    allowed_logins = tuple(
        int(item.strip()) for item in allowed.split(",") if item.strip().isdigit()
    )
    cfg = BotConfig(
        demo_only=bool(values.get("DEMO_ONLY", True)),
        live_trading_approved=bool(values.get("LIVE_TRADING_APPROVED", False)),
        allowed_account_logins=allowed_logins,
        max_open_trades=int(values.get("MAX_OPEN_TRADES", 10)),
        max_open_risk_pct=float(values.get("MAX_OPEN_RISK_PCT", 5.0)),
        max_risk_per_trade_pct=float(values.get("MAX_RISK_PER_TRADE_PCT", 0.5)),
        max_daily_drawdown_pct=float(values.get("MAX_DAILY_DRAWDOWN_PCT", 3.0)),
        max_floating_drawdown_pct=float(values.get("MAX_FLOATING_DRAWDOWN_PCT", 5.0)),
        trading_halted_until_next_day_on_dd=bool(
            values.get("TRADING_HALTED_UNTIL_NEXT_DAY_ON_DD", True)
        ),
        require_sl=bool(values.get("REQUIRE_SL", True)),
        require_tp=bool(values.get("REQUIRE_TP", True)),
        max_spread_points_default=float(values.get("MAX_SPREAD_POINTS_DEFAULT", 25.0)),
        max_market_snapshot_age_seconds=int(values.get("MAX_MARKET_SNAPSHOT_AGE_SECONDS", 5)),
        max_signal_age_seconds=int(values.get("MAX_SIGNAL_AGE_SECONDS", 30)),
        max_tick_age_seconds=int(values.get("MAX_TICK_AGE_SECONDS", 5)),
        allow_partial_fill=bool(values.get("ALLOW_PARTIAL_FILL", False)),
        telegram_enabled=bool(values.get("TELEGRAM_ENABLED", False)),
        database_enabled=bool(values.get("DATABASE_ENABLED", False)),
        log_retention_days=int(values.get("LOG_RETENTION_DAYS", 90)),
        max_jsonl_file_mb=int(values.get("MAX_JSONL_FILE_MB", 50)),
        telegram_outbox_retention_days=int(values.get("TELEGRAM_OUTBOX_RETENTION_DAYS", 30)),
        use_market_structure_filters=bool(values.get("USE_MARKET_STRUCTURE_FILTERS", True)),
        use_session_levels=bool(values.get("USE_SESSION_LEVELS", True)),
        use_liquidity_sweep_filters=bool(values.get("USE_LIQUIDITY_SWEEP_FILTERS", True)),
        use_cost_aware_scoring=bool(values.get("USE_COST_AWARE_SCORING", True)),
        use_advanced_setup_scoring=bool(values.get("USE_ADVANCED_SETUP_SCORING", True)),
        min_setup_score_by_strategy=str(values.get("MIN_SETUP_SCORE_BY_STRATEGY", "")),
        min_setup_score_by_regime=str(values.get("MIN_SETUP_SCORE_BY_REGIME", "")),
        signal_profile=str(values.get("SIGNAL_PROFILE", "CONSERVATIVE")).upper(),
    )
    cfg.validate_safety()
    return cfg
