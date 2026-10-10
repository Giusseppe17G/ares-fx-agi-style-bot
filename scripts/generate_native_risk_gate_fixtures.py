"""Freeze synthetic Python risk-gate references and generate MQL assertions.

This script never compiles or runs MQL, accesses a terminal, or reads market data.
Every comparable expectation is the output of the production Python RiskEngine
(with PositionSizer and PortfolioGuard) on identical inputs; native-only
expectations are declared against PROJECT_SPEC 17.12 and labelled by scope.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, getcontext
from hashlib import sha256
import inspect
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/python"))

from agi_style_forex_bot_mt5.config import BotConfig
from agi_style_forex_bot_mt5.contracts import (
    AccountState, Direction, EntryType, MarketSnapshot, PositionState, TradeSignal,
)
from agi_style_forex_bot_mt5.risk.emergency_kill_switch import KillSwitchState
from agi_style_forex_bot_mt5.risk.portfolio_guard import PortfolioGuard
from agi_style_forex_bot_mt5.risk.position_sizer import PositionSizer, normalize_lot_down, price_risk_per_lot
from agi_style_forex_bot_mt5.risk.risk_engine import RiskEngine, RiskRuntimeState

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
NOW = 1767614400000  # 2026-01-05 12:00:00 UTC, synthetic only.
VERSION = "native_risk_gate_v1"
SPECIAL_NUMBERS = {"NAN": float("nan"), "POS_INF": float("inf"), "NEG_INF": float("-inf")}
DEFAULT_JSON = ROOT / "tests/fixtures/native_risk_gate_cases.json"
DEFAULT_INCLUDE = ROOT / "tests/mt5/GeneratedRiskGateFixtures.mqh"
# Python's RiskEngine fixes the per-symbol limit; comparable cases use it.
PYTHON_PER_SYMBOL_LIMIT = 2
AMOUNT_FIELDS = ("risk_amount", "risk_pct", "open_risk_pct_after", "daily_drawdown_pct", "floating_drawdown_pct")
DECISION_FIELDS = ("accepted", "reject_code", "approved_lot", *AMOUNT_FIELDS)
# Only cases whose tick value is not an exact 1e-8 lattice member may differ by
# binary rounding of one product; they get this predeclared ULP budget.
NON_LATTICE_ULPS = 4


def _value(value):
    return SPECIAL_NUMBERS.get(value, value) if isinstance(value, str) else value


def _datetime(ms):
    return EPOCH + timedelta(milliseconds=ms)


def base_inputs():
    """Comparable baseline: BotConfig defaults, demo account, EURUSD buy."""
    return {
        "limits": dict(demo_only=True, live_trading_approved=False, max_risk_per_trade_pct=0.5,
            max_open_risk_pct=5.0, max_open_trades=10, max_open_trades_per_symbol=PYTHON_PER_SYMBOL_LIMIT,
            max_daily_drawdown_pct=3.0, max_floating_drawdown_pct=5.0, max_spread_points=25.0,
            max_signal_age_seconds=30, max_snapshot_age_seconds=5, max_consecutive_losses=3),
        "account": dict(known=True, is_demo=True, trade_allowed=True, balance=10000.0, equity=10000.0),
        "snapshot": dict(symbol="EURUSD", timestamp_utc_msc=NOW-1000, bid=1.1, ask=1.1001, spread_points=10.0,
            digits=5, point=0.00001, tick_size=0.00001, tick_value=1.0, volume_min=0.01, volume_max=100.0,
            volume_step=0.01, stops_level_points=0, freeze_level_points=0),
        "signal": dict(symbol="EURUSD", direction="BUY", created_at_utc_msc=NOW-2000, sl_price=1.0951,
            tp_price=1.1101, confidence=0.7, has_risk_pct=False, risk_pct=0.0, has_requested_lot=False,
            requested_lot=0.0),
        "positions": [],
        "state": dict(now_utc_msc=NOW, has_daily_equity_reference=True, daily_equity_reference=10000.0,
            has_floating_drawdown_reference=False, floating_drawdown_reference=0.0, audit_confirmed=True,
            symbol_allowed=True, kill_switch_active=False, kill_switch_until_utc_msc=0, consecutive_losses=0,
            cooldown_until_utc_msc=0),
    }


def _position(symbol="GBPUSD", *, volume=0.1, entry=1.25, sl=1.245, tick_size=0.00001, tick_value=1.0,
              risk_amount=None, direction="BUY"):
    return dict(symbol=symbol, direction=direction, volume=volume, entry_price=entry, sl_price=sl,
        tick_size=tick_size, tick_value=tick_value, has_risk_amount=risk_amount is not None,
        risk_amount=0.0 if risk_amount is None else risk_amount)


def declared_inputs():
    """Declare inputs, scopes and native-only policies before observing outputs."""
    cases = []

    def add(case_id, *, change=None, scope="COMPARABLE", native_reason=None, note=""):
        inputs = base_inputs()
        if change:
            change(inputs)
        cases.append(dict(case_id=case_id, inputs=inputs, comparison_scope=scope,
            declared_native_reason=native_reason, difference_note=note))

    def put(section, **values):
        def change(inputs):
            inputs[section].update(values)
        return change

    def chain(*changes):
        def change(inputs):
            for item in changes:
                item(inputs)
        return change

    sell = put("signal", direction="SELL", sl_price=1.105, tp_price=1.09)
    add("accept_buy_exact_boundary_lot")
    add("accept_sell", change=sell)
    add("requested_lot_below_risk_lot", change=put("signal", has_requested_lot=True, requested_lot=0.05))
    add("requested_lot_above_risk_lot", change=put("signal", has_requested_lot=True, requested_lot=1.0))
    add("requested_lot_below_minimum", change=put("signal", has_requested_lot=True, requested_lot=0.001))
    add("requested_lot_floored_from_nonlattice", change=put("signal", has_requested_lot=True, requested_lot=0.0549999))
    add("requested_lot_above_maximum", change=chain(put("snapshot", volume_max=0.05),
        put("signal", has_requested_lot=True, requested_lot=7.0)))
    add("requested_lot_nan", change=put("signal", has_requested_lot=True, requested_lot="NAN"))
    add("lower_requested_risk_pct", change=put("signal", has_risk_pct=True, risk_pct=0.25))
    add("risk_pct_capped_at_limit", change=put("signal", has_risk_pct=True, risk_pct=1.0))
    add("zero_risk_pct", change=put("signal", has_risk_pct=True, risk_pct=0.0))
    add("negative_risk_pct", change=put("signal", has_risk_pct=True, risk_pct=-0.1))
    add("risk_lot_below_minimum", change=put("signal", sl_price=0.5001))
    add("risk_lot_capped_at_volume_max", change=chain(put("snapshot", volume_max=3.0),
        put("signal", sl_price=1.10009)))
    add("risk_lot_floored_nonlattice_quotient", change=put("signal", sl_price=1.10003))
    add("risk_lot_floored_step_tenth", change=put("snapshot", volume_min=0.1, volume_step=0.1))
    add("minimum_not_multiple_of_step", change=chain(put("snapshot", volume_min=0.03, volume_step=0.02),
        put("signal", sl_price=1.09735)))
    add("risk_lot_just_below_step_boundary", change=put("signal", sl_price=1.09509))
    for label, tick_value, scope in (("half", 0.5, "COMPARABLE"), ("ten", 10.0, "COMPARABLE"),
                                     ("decimal_tenth", 0.1, "COMPARABLE"), ("eight_decimals", 0.91234567, "COMPARABLE"),
                                     ("non_lattice", 0.912345678912, "COMPARABLE_NON_LATTICE_TICK_VALUE")):
        add(f"tick_value_{label}", change=put("snapshot", tick_value=tick_value), scope=scope,
            note="Binary product of a non-lattice tick value may differ by one ulp; lot verified away from boundaries."
            if scope != "COMPARABLE" else "")
    usdjpy = chain(put("snapshot", symbol="USDJPY", bid=150.0, ask=150.012, digits=3, point=0.001, tick_size=0.001,
        tick_value=0.6667, spread_points=12.0), put("signal", symbol="USDJPY", sl_price=149.712, tp_price=150.612))
    add("usdjpy_three_digit_grid", change=usdjpy)
    add("usdjpy_sell", change=chain(usdjpy, put("signal", direction="SELL", sl_price=150.3, tp_price=149.5)))
    add("account_unknown", change=put("account", known=False))
    add("account_real", change=put("account", is_demo=False))
    add("account_trade_disabled", change=put("account", trade_allowed=False))
    add("equity_zero", change=put("account", equity=0.0))
    add("balance_zero", change=put("account", balance=0.0))
    add("kill_switch_without_expiry", change=put("state", kill_switch_active=True))
    add("kill_switch_until_future", change=put("state", kill_switch_active=True, kill_switch_until_utc_msc=NOW+1))
    add("kill_switch_expired_exactly_now", change=put("state", kill_switch_active=True, kill_switch_until_utc_msc=NOW))
    add("symbol_not_allowed", change=put("state", symbol_allowed=False))
    add("signal_snapshot_symbol_mismatch", change=put("signal", symbol="GBPUSD"))
    add("signal_age_at_limit", change=put("signal", created_at_utc_msc=NOW-30000))
    add("signal_age_over_limit", change=put("signal", created_at_utc_msc=NOW-30001))
    add("signal_from_future", change=put("signal", created_at_utc_msc=NOW+1))
    add("snapshot_age_at_limit", change=put("snapshot", timestamp_utc_msc=NOW-5000))
    add("snapshot_age_over_limit", change=put("snapshot", timestamp_utc_msc=NOW-5001))
    add("snapshot_from_future", change=put("snapshot", timestamp_utc_msc=NOW+1))
    add("missing_sl", change=put("signal", sl_price=0.0))
    add("missing_tp", change=put("signal", tp_price=0.0))
    add("buy_sl_above_entry", change=put("signal", sl_price=1.1002))
    add("buy_tp_below_entry", change=put("signal", tp_price=1.1001))
    add("sell_geometry_inverted", change=put("signal", direction="SELL"))
    add("confidence_above_one", change=put("signal", confidence=1.5))
    add("confidence_negative", change=put("signal", confidence=-0.1))
    add("ask_below_bid", change=put("snapshot", ask=1.09999))
    add("zero_bid_reports_market_invalid", change=put("snapshot", bid=0.0))
    add("invalid_snapshot_with_missing_sl_reports_missing_sl", change=chain(put("snapshot", bid=0.0),
        put("signal", sl_price=0.0)))
    add("negative_spread", change=put("snapshot", spread_points=-1.0))
    add("volume_min_above_max", change=put("snapshot", volume_min=2.0, volume_max=1.0))
    add("stops_level_blocks_close_sl", change=chain(put("snapshot", stops_level_points=600)))
    add("stops_level_allows_exact_distance", change=chain(put("snapshot", stops_level_points=490)))
    add("sell_stops_level_blocks_close_sl", change=chain(sell, put("snapshot", stops_level_points=500)))
    add("audit_not_confirmed", change=put("state", audit_confirmed=False))
    add("spread_at_limit", change=put("snapshot", spread_points=25.0))
    add("spread_over_limit", change=put("snapshot", spread_points=25.5))
    add("daily_reference_missing", change=put("state", has_daily_equity_reference=False))
    add("daily_reference_zero", change=put("state", daily_equity_reference=0.0))
    add("daily_drawdown_at_limit", change=put("account", equity=9700.0))
    add("daily_drawdown_below_limit", change=put("account", equity=9701.0))
    add("equity_above_daily_reference", change=put("account", equity=10100.0))
    add("floating_drawdown_at_limit", change=chain(put("account", balance=10500.0, equity=9975.0),
        put("state", daily_equity_reference=9975.0)))
    add("floating_reference_explicit", change=chain(put("account", equity=9800.0),
        put("state", has_floating_drawdown_reference=True, floating_drawdown_reference=10200.0)))
    add("floating_reference_zero_uses_balance", change=chain(put("account", equity=9800.0),
        put("state", has_floating_drawdown_reference=True, floating_drawdown_reference=0.0)))
    add("floating_reference_negative", change=put("state", has_floating_drawdown_reference=True,
        floating_drawdown_reference=-5.0))
    add("consecutive_losses_at_limit", change=put("state", consecutive_losses=3))
    add("consecutive_losses_below_limit", change=put("state", consecutive_losses=2))
    add("cooldown_active", change=put("state", cooldown_until_utc_msc=NOW+1))
    add("cooldown_expired_exactly_now", change=put("state", cooldown_until_utc_msc=NOW))

    def positions(items):
        def change(inputs):
            inputs["positions"] = items
        return change

    add("nine_open_positions_allow_tenth", change=positions(
        [_position(f"SYN{i:03d}", risk_amount=1.0) for i in range(9)]))
    add("ten_open_positions_block", change=positions(
        [_position(f"SYN{i:03d}", risk_amount=1.0) for i in range(10)]))
    add("two_same_symbol_block", change=positions(
        [_position("EURUSD", entry=1.1, sl=1.099), _position("EURUSD", entry=1.1, sl=1.099)]))
    add("one_same_symbol_priced_from_tick_metadata", change=positions([_position("EURUSD", entry=1.1, sl=1.099)]))
    add("open_risk_at_limit", change=positions([_position(risk_amount=450.0)]))
    add("open_risk_over_limit", change=positions([_position(risk_amount=450.01)]))
    add("open_risk_priced_from_metadata", change=positions([_position(volume=2.5, entry=1.25, sl=1.234)]))
    add("open_risk_jpy_metadata", change=positions([_position("USDJPY", volume=1.0, entry=150.0, sl=149.5,
        tick_size=0.001, tick_value=0.6667)]))
    add("negative_known_open_risk", change=positions([_position(risk_amount=-1.0)]))
    add("zero_volume_open_position", change=positions([_position(volume=0.0)]))
    add("sell_open_position_risk", change=positions([_position(direction="SELL", entry=1.25, sl=1.256)]))

    # Precedence: when several checks fail, the first in RiskEngine order wins.
    add("precedence_account_before_kill_switch", change=chain(put("account", known=False),
        put("state", kill_switch_active=True)))
    add("precedence_kill_switch_before_symbol", change=chain(put("state", kill_switch_active=True, symbol_allowed=False)))
    add("precedence_stale_signal_before_geometry", change=chain(put("signal", created_at_utc_msc=NOW-30001, tp_price=1.0)))
    add("precedence_geometry_before_audit", change=chain(put("signal", tp_price=1.0), put("state", audit_confirmed=False)))
    add("precedence_audit_before_spread", change=chain(put("state", audit_confirmed=False), put("snapshot", spread_points=30.0)))
    add("precedence_spread_before_drawdown", change=chain(put("snapshot", spread_points=30.0), put("account", equity=9000.0)))
    add("precedence_daily_before_floating", change=chain(put("account", equity=9000.0)))
    add("precedence_drawdown_before_losses", change=chain(put("account", equity=9000.0), put("state", consecutive_losses=5)))
    add("precedence_losses_before_cooldown", change=put("state", consecutive_losses=5, cooldown_until_utc_msc=NOW+1))
    add("precedence_risk_pct_before_lot", change=chain(put("signal", has_risk_pct=True, risk_pct=0.0,
        has_requested_lot=True, requested_lot=0.001)))
    add("precedence_lot_before_portfolio", change=chain(put("signal", has_requested_lot=True, requested_lot=0.001),
        positions([_position(f"SYN{i:03d}", risk_amount=1.0) for i in range(10)])))
    add("precedence_open_trades_before_symbol_count", change=positions(
        [_position("EURUSD", risk_amount=1.0) for _ in range(10)]))

    # Native-only policies: Python reference recorded, expectation declared.
    for label, values in (("risk_per_trade_above_ceiling", dict(max_risk_per_trade_pct=0.6)),
                          ("open_risk_above_ceiling", dict(max_open_risk_pct=5.5)),
                          ("open_trades_above_ten", dict(max_open_trades=11)),
                          ("daily_drawdown_above_ceiling", dict(max_daily_drawdown_pct=3.5)),
                          ("demo_only_disabled", dict(demo_only=False)),
                          ("live_trading_approved", dict(live_trading_approved=True))):
        add(f"limits_{label}", change=put("limits", **values), scope="NATIVE_LIMITS_CODE",
            native_reason="RISK_LIMITS_INVALID",
            note="Python rejects the same unsafe configuration with INTERNAL_ERROR from validate_safety.")
    for label, values in (("spread_limit_above_default", dict(max_spread_points=26.0)),
                          ("per_symbol_zero", dict(max_open_trades_per_symbol=0)),
                          ("consecutive_limit_zero", dict(max_consecutive_losses=0))):
        add(f"limits_{label}", change=put("limits", **values), scope="NATIVE_LIMITS_STRICTER",
            native_reason="RISK_LIMITS_INVALID",
            note="Native enforces PROJECT_SPEC ceilings and positive limits that Python's config does not check.")
    add("negative_consecutive_losses", change=put("state", consecutive_losses=-1), scope="NATIVE_STATE_STRICTER",
        native_reason="RISK_STATE_INVALID", note="Python treats a negative loss count as below the limit.")
    add("sl_off_tick_grid", change=put("signal", sl_price=1.095105), scope="NATIVE_GRID_STRICTER",
        native_reason="MARKET_DATA_INVALID", note="Python sizes off-grid stops; native requires the tick grid.")
    add("bid_off_tick_grid", change=put("snapshot", bid=1.099995), scope="NATIVE_GRID_STRICTER",
        native_reason="MARKET_DATA_INVALID", note="Python accepts an off-grid quote; native requires the tick grid.")
    add("volume_step_off_lattice", change=put("snapshot", volume_step=0.0000000015), scope="NATIVE_GRID_STRICTER",
        native_reason="MARKET_DATA_INVALID", note="Native volume arithmetic is exact on a 1e-8 lattice only.")
    add("nan_spread", change=put("snapshot", spread_points="NAN"), scope="NATIVE_NUMERIC_STRICTER",
        native_reason="MARKET_DATA_INVALID", note="Python's NaN spread passes both comparisons.")
    add("nan_daily_reference", change=put("state", daily_equity_reference="NAN"), scope="NATIVE_NUMERIC_STRICTER",
        native_reason="DAILY_DRAWDOWN_REFERENCE_MISSING", note="Python turns a NaN drawdown into zero.")
    add("infinite_risk_pct", change=put("signal", has_risk_pct=True, risk_pct="POS_INF"), scope="NATIVE_NUMERIC_STRICTER",
        native_reason="RISK_CALCULATION_UNCERTAIN", note="Python caps an infinite request at the limit.")
    add("nan_known_open_risk", change=positions([_position(risk_amount="NAN")]), scope="NATIVE_NUMERIC_STRICTER",
        native_reason="RISK_CALCULATION_UNCERTAIN", note="Python accepts with a NaN open-risk percentage.")
    add("invalid_direction", change=put("signal", direction="NONE"), scope="NATIVE_CONTRACT",
        native_reason="MARKET_DATA_INVALID", note="Python Direction cannot be constructed without BUY or SELL.")
    return cases


def _snapshot(values):
    return MarketSnapshot(values["symbol"], "M5", _datetime(values["timestamp_utc_msc"]),
        *(_value(values[key]) for key in ("bid", "ask", "spread_points", "digits", "point", "tick_value",
            "tick_size", "volume_min", "volume_max", "volume_step", "stops_level_points", "freeze_level_points")))


def python_reference(case):
    """Run the production RiskEngine; a native-only contract returns NOT_EXPRESSIBLE."""
    inputs = case["inputs"]
    limits, account, signal, state = (inputs[key] for key in ("limits", "account", "signal", "state"))
    if signal["direction"] not in ("BUY", "SELL"):
        return {"status": "NOT_EXPRESSIBLE"}
    config = BotConfig(demo_only=limits["demo_only"], live_trading_approved=limits["live_trading_approved"],
        max_open_trades=limits["max_open_trades"], max_open_risk_pct=limits["max_open_risk_pct"],
        max_risk_per_trade_pct=limits["max_risk_per_trade_pct"], max_daily_drawdown_pct=limits["max_daily_drawdown_pct"],
        max_floating_drawdown_pct=limits["max_floating_drawdown_pct"], max_spread_points_default=limits["max_spread_points"],
        max_market_snapshot_age_seconds=limits["max_snapshot_age_seconds"],
        max_signal_age_seconds=limits["max_signal_age_seconds"])
    snapshot = _snapshot(inputs["snapshot"])
    account_state = AccountState(login=1 if account["known"] else None, trade_mode="DEMO" if account["known"] else None,
        balance=_value(account["balance"]), equity=_value(account["equity"]), margin_free=_value(account["equity"]),
        is_demo=account["is_demo"], trade_allowed=account["trade_allowed"])
    trade = TradeSignal(signal_id="fixture", created_at_utc=_datetime(signal["created_at_utc_msc"]),
        symbol=signal["symbol"], timeframe="M5", direction=Direction(signal["direction"]), entry_type=EntryType.MARKET,
        sl_price=_value(signal["sl_price"]), tp_price=_value(signal["tp_price"]),
        requested_lot=_value(signal["requested_lot"]) if signal["has_requested_lot"] else None,
        risk_pct=_value(signal["risk_pct"]) if signal["has_risk_pct"] else None, confidence=_value(signal["confidence"]))
    positions, known, snapshots = [], {}, {}
    for ticket, item in enumerate(inputs["positions"], start=1):
        positions.append(PositionState(ticket=ticket, symbol=item["symbol"], direction=Direction(item["direction"]),
            volume=_value(item["volume"]), entry_price=item["entry_price"], sl_price=item["sl_price"],
            tp_price=item["entry_price"], magic_number=0))
        if item["has_risk_amount"]:
            known[ticket] = _value(item["risk_amount"])
        else:
            meta = dict(inputs["snapshot"], symbol=item["symbol"], tick_size=item["tick_size"], tick_value=item["tick_value"])
            snapshots[item["symbol"]] = _snapshot(meta)
    runtime = RiskRuntimeState(
        daily_equity_reference=_value(state["daily_equity_reference"]) if state["has_daily_equity_reference"] else None,
        floating_drawdown_reference=_value(state["floating_drawdown_reference"]) if state["has_floating_drawdown_reference"] else None,
        audit_confirmed=state["audit_confirmed"], open_positions=tuple(positions), snapshots_by_symbol=snapshots,
        open_position_risk_amounts=known, now_utc=_datetime(state["now_utc_msc"]),
        allowed_symbols=None if state["symbol_allowed"] else frozenset(),
        consecutive_losses=state["consecutive_losses"], max_consecutive_losses=limits["max_consecutive_losses"],
        cooldown_until_utc=_datetime(state["cooldown_until_utc_msc"]) if state["cooldown_until_utc_msc"] else None,
        kill_switch=KillSwitchState(active=state["kill_switch_active"], reason="fixture",
            halted_until_utc=_datetime(state["kill_switch_until_utc_msc"]) if state["kill_switch_until_utc_msc"] else None))
    decision = RiskEngine(config).evaluate(signal=trade, snapshot=snapshot, account=account_state, state=runtime)
    sizing = decision.checks.get("lot_sizing", {}) if decision.accepted else {}
    return {"status": "EVALUATED", "accepted": decision.accepted, "reject_code": decision.reject_code,
        "approved_lot": _number(decision.approved_lot), "risk_amount": _number(decision.risk_amount_account_currency),
        "risk_pct": _number(sizing.get("risk_pct", 0.0)), "open_risk_pct_after": _number(decision.open_risk_pct_after_trade),
        "daily_drawdown_pct": _number(decision.daily_drawdown_pct),
        "floating_drawdown_pct": _number(decision.floating_drawdown_pct)}


def _number(value):
    value = float(value)
    return {"status": "FINITE", "value": value} if math.isfinite(value) else {
        "status": "NAN" if math.isnan(value) else "POS_INF" if value > 0 else "NEG_INF", "value": None}


def _lattice(value):
    return Decimal(repr(float(value))) == Decimal(repr(float(value))).quantize(Decimal("1e-8"))


def expected_native(case, reference):
    """Comparable cases copy the Python decision; native-only ones are declared."""
    if case["comparison_scope"].startswith("COMPARABLE"):
        if reference["status"] != "EVALUATED" or any(reference[key]["status"] != "FINITE"
                                                    for key in ("approved_lot", *AMOUNT_FIELDS)):
            raise ValueError(f"comparable fixture has no finite Python decision: {case['case_id']}")
        result = {"accepted": reference["accepted"], "reject_code": reference["reject_code"]}
        result.update({key: reference[key]["value"] for key in ("approved_lot", *AMOUNT_FIELDS)})
    else:
        if reference["status"] == "EVALUATED" and reference["reject_code"] == case["declared_native_reason"] \
                and case["comparison_scope"] != "NATIVE_NUMERIC_STRICTER":
            raise ValueError(f"native-only scope must differ from Python: {case['case_id']}")
        result = {"accepted": False, "reject_code": case["declared_native_reason"], "approved_lot": 0.0,
            **{key: 0.0 for key in AMOUNT_FIELDS}}
    result.update(version=VERSION, execution_authorized=False, full_pipeline_verified=False)
    return result


def amount_budgets(case, expected):
    """Exact for lattice inputs; a few ulps only where the tick value is off-lattice."""
    if case["comparison_scope"] != "COMPARABLE_NON_LATTICE_TICK_VALUE":
        return {key: 0.0 for key in AMOUNT_FIELDS}
    return {key: NON_LATTICE_ULPS * math.ulp(expected[key]) for key in AMOUNT_FIELDS}


def assert_lot_robust(case):
    """A non-lattice case is valid only if one-ulp product drift cannot move the lot."""
    if case["comparison_scope"] != "COMPARABLE_NON_LATTICE_TICK_VALUE":
        return
    snapshot = _snapshot(case["inputs"]["snapshot"])
    signal = case["inputs"]["signal"]
    reference = snapshot.ask if signal["direction"] == "BUY" else snapshot.bid
    per_lot = price_risk_per_lot(reference, signal["sl_price"], snapshot)
    max_risk = case["inputs"]["account"]["equity"] * (case["inputs"]["limits"]["max_risk_per_trade_pct"] / 100.0)
    lots = {normalize_lot_down(max_risk / value, snapshot) for value in
            (per_lot, math.nextafter(per_lot, 0.0), math.nextafter(per_lot, math.inf),
             math.nextafter(math.nextafter(per_lot, 0.0), 0.0), math.nextafter(math.nextafter(per_lot, math.inf), math.inf))}
    if len(lots) != 1:
        raise ValueError(f"non-lattice fixture sits on a lot boundary: {case['case_id']}")


def fixture_document():
    cases = declared_inputs()
    for case in cases:
        case["input_sha256"] = sha256(canonical_bytes(case["inputs"])).hexdigest()
        case["python_reference"] = python_reference(case)
        case["expected_native"] = expected_native(case, case["python_reference"])
        case["absolute_tolerances"] = amount_budgets(case, case["expected_native"])
        case["tick_value_on_lattice"] = _lattice(_value(case["inputs"]["snapshot"]["tick_value"]))
        assert_lot_robust(case)
    functions = (RiskEngine, PositionSizer, PortfolioGuard, normalize_lot_down, price_risk_per_lot,
                 TradeSignal.validate_against_snapshot, MarketSnapshot.validate, BotConfig.validate_safety)
    return {"schema_version": "native_risk_gate_fixtures_v1", "risk_gate_version": VERSION,
        "scope": "SYNTHETIC_FUNCTION_REFERENCE_ONLY", "native_runtime_executed": False,
        "full_pipeline_verified": False, "execution_authorized": False,
        # IEEE binary64 and the default Decimal context make these references
        # interpreter-independent; production sources are bound by hash below.
        "reference_runtime": {"float_mant_dig": sys.float_info.mant_dig, "float_max_exp": sys.float_info.max_exp,
            "decimal_precision": getcontext().prec},
        "python_source_sha256": {f"{fn.__module__}.{fn.__qualname__}": sha256(inspect.getsource(fn).encode()).hexdigest()
            for fn in functions},
        "tolerance_policy": {"lattice_inputs": "EXACT", "non_lattice_tick_value_ulps": NON_LATTICE_ULPS,
            "lot": "EXACT", "scope": "REGRESSION_BUDGET_NOT_A_UNIVERSAL_ERROR_BOUND"},
        "cases": cases}


def canonical_bytes(document):
    return (json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _mql_literal(value):
    if value == "NAN": return "NativeRiskFixtureNonfinite(0)"
    if value == "POS_INF": return "NativeRiskFixtureNonfinite(1)"
    if value == "NEG_INF": return "NativeRiskFixtureNonfinite(-1)"
    if isinstance(value, bool): return "true" if value else "false"
    if isinstance(value, str): return json.dumps(value)
    if isinstance(value, float): return repr(value)
    return str(value)


DIRECTIONS = {"BUY": "NATIVE_RISK_BUY", "SELL": "NATIVE_RISK_SELL", "NONE": "0"}
SNAPSHOT_FIELDS = ("symbol", "timestamp_utc_msc", "bid", "ask", "spread_points", "digits", "point", "tick_size",
                   "tick_value", "volume_min", "volume_max", "volume_step", "stops_level_points", "freeze_level_points")


def render_mql(document):
    digest = sha256(canonical_bytes(document)).hexdigest()
    lines = ["// Generated by scripts/generate_native_risk_gate_fixtures.py; do not edit.",
        f"// Authoritative fixture SHA256: {digest}",
        "// Compilation does not execute these assertions or establish runtime parity.",
        "#ifndef AGI_GENERATED_RISK_GATE_FIXTURES_MQH", "#define AGI_GENERATED_RISK_GATE_FIXTURES_MQH",
        "double NativeRiskFixtureNonfinite(const int kind)", "  {",
        "   double argument=(kind==0 ? -1.0 : 1000.0);",
        "   if(kind==0) return MathSqrt(argument);",
        "   double infinite=MathExp(argument); return kind<0 ? -infinite : infinite;", "  }",
        "bool NativeRiskFixtureNear(const double actual,const double expected,const double budget)", "  {",
        "   if(!MathIsValidNumber(actual) || !MathIsValidNumber(expected) || !MathIsValidNumber(budget) || budget<0.0) return false;",
        "   if(actual==expected) return true;",
        "   return MathAbs(actual-expected)<=budget;", "  }",
        "void NativeRiskFixturePoison(NativeRiskDecision &decision)", "  {",
        '   decision.accepted=true; decision.reject_code="OLD"; decision.version="OLD";',
        "   decision.approved_lot=777.0; decision.risk_amount=777.0; decision.risk_pct=777.0;",
        "   decision.open_risk_pct_after=777.0; decision.daily_drawdown_pct=777.0; decision.floating_drawdown_pct=777.0;",
        "   decision.execution_authorized=true; decision.full_pipeline_verified=true;", "  }"]
    for index, case in enumerate(document["cases"]):
        name, inputs, expected = case["case_id"], case["inputs"], case["expected_native"]
        lines += [f"void NativeRiskRunCase{index}(NativeRiskDecision &decision)", "  {",
            f"   // {name}: {case['comparison_scope']}",
            "   NativeRiskLimits limits; NativeRiskAccount account; MarketSnapshot snapshot;",
            "   NativeRiskSignal signal; NativeRiskState state; NativeRiskPosition positions[];"]
        for section, variable in (("limits", "limits"), ("account", "account"), ("state", "state")):
            for key, value in sorted(inputs[section].items()):
                lines.append(f"   {variable}.{key}={_mql_literal(value)};")
        for key in SNAPSHOT_FIELDS:
            lines.append(f"   snapshot.{key}={_mql_literal(inputs['snapshot'][key])};")
        lines += ['   snapshot.timeframe="M5"; snapshot.timestamp_utc=(datetime)(snapshot.timestamp_utc_msc/1000);',
                  "   snapshot.source_tick_server_msc=0; snapshot.observed_at_utc=snapshot.timestamp_utc;"]
        for key, value in sorted(inputs["signal"].items()):
            literal = DIRECTIONS[value] if key == "direction" else _mql_literal(value)
            lines.append(f"   signal.{key}={literal};")
        lines.append(f"   ArrayResize(positions,{len(inputs['positions'])});")
        for i, item in enumerate(inputs["positions"]):
            for key, value in sorted(item.items()):
                if key != "direction":
                    lines.append(f"   positions[{i}].{key}={_mql_literal(value)};")
        lines += ["   NativeRiskFixturePoison(decision);",
            "   bool accepted=NativeEvaluateRisk(limits,account,snapshot,signal,positions,state,decision);",
            f'   Check(accepted=={_mql_literal(expected["accepted"])},"{name}:return");',
            f'   Check(decision.accepted=={_mql_literal(expected["accepted"])},"{name}:accepted");',
            f'   Check(decision.reject_code=={_mql_literal(expected["reject_code"])},"{name}:reject_code");',
            f'   Check(decision.version=="{VERSION}","{name}:version");',
            f'   Check(decision.approved_lot=={_mql_literal(expected["approved_lot"])},"{name}:approved_lot");',
            f'   Check(!decision.execution_authorized && !decision.full_pipeline_verified,"{name}:flags");']
        for key in AMOUNT_FIELDS:
            budget = case["absolute_tolerances"][key]
            if budget:
                lines.append(f'   Check(NativeRiskFixtureNear(decision.{key},{_mql_literal(expected[key])},{_mql_literal(budget)}),"{name}:{key}");')
            else:
                lines.append(f'   Check(decision.{key}=={_mql_literal(expected[key])},"{name}:{key}");')
        if expected["accepted"]:
            lines += ["   limits.max_open_trades=0;",
                f'   Check(!NativeEvaluateRisk(limits,account,snapshot,signal,positions,state,decision),"{name}:reset_return");',
                f'   Check(!decision.accepted && decision.reject_code=="RISK_LIMITS_INVALID" && decision.version=="{VERSION}","{name}:reset_status");',
                f'   Check(decision.approved_lot==0.0 && decision.risk_amount==0.0 && decision.risk_pct==0.0,"{name}:reset_amounts");',
                f'   Check(decision.open_risk_pct_after==0.0 && decision.daily_drawdown_pct==0.0 && decision.floating_drawdown_pct==0.0,"{name}:reset_drawdown");',
                f'   Check(!decision.execution_authorized && !decision.full_pipeline_verified,"{name}:reset_flags");']
        lines += ["  }"]
    lines += ["void RunGeneratedRiskGateFixtures(void)", "  {", "   NativeRiskDecision decision;"]
    lines += [f"   NativeRiskRunCase{i}(decision);" for i in range(len(document["cases"]))]
    lines += ["  }", "#endif", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--mql-output", type=Path, default=DEFAULT_INCLUDE)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    document = fixture_document()
    outputs = ((args.json_output, canonical_bytes(document)), (args.mql_output, render_mql(document).encode("utf-8")))
    if args.check:
        return 0 if all(path.is_file() and path.read_bytes() == data for path, data in outputs) else 1
    for path, data in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(f"Generated {len(document['cases'])} synthetic risk-gate fixtures; MQL assertions NOT EXECUTED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
