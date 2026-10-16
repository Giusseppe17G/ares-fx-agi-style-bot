"""Operating a live forward-shadow run: integrity stop, skip notices, stop requests.

Real ForwardShadowBot, lifecycle, decisions and storage; only MT5 is faked.
Paper only: the fake client fails any broker order call.
"""
from dataclasses import replace
import signal
from types import SimpleNamespace

import pytest

from agi_style_forex_bot_mt5.paper_trading import forward_shadow_bot as forward_module
from agi_style_forex_bot_mt5.paper_trading.paper_state import request_stop_shadow, resume_shadow
from agi_style_forex_bot_mt5.utils.mt5_server_time import server_offset_seconds

from test_forward_lifecycle_review import forward_bot, review_case  # noqa: F401
from test_stateful_replay import replay_case  # noqa: F401


def _events(database, event_type):
    return [row for row in database.fetch_all("events") if row["event_type"] == event_type]


def _shift_ticks(client, seconds):
    original = client.symbol_info_tick

    def shifted(symbol):
        tick = original(symbol)
        return SimpleNamespace(bid=tick.bid, ask=tick.ask, time=tick.time + int(seconds),
                               time_msc=tick.time_msc + int(seconds * 1000))

    client.symbol_info_tick = shifted


def test_future_dated_ticks_stop_the_run_without_latching(review_case, tmp_path, monkeypatch):
    bot, database, client, _ = forward_bot(review_case, tmp_path, monkeypatch, cycles=3)
    try:
        _shift_ticks(client, 120)
        summary = bot.run()
        assert summary.exit_reason == "MARKET_DATA_INTEGRITY_FAILED"
        assert summary.lifecycle_halted is False and summary.cycles_skipped == 0
        assert summary.paper_trades_opened == 0
        stop = _events(database, "FORWARD_SHADOW_INTEGRITY_STOP")
        assert len(stop) == 1 and stop[0]["severity"] == "CRITICAL"
        state = database.get_operational_state()
        assert not state.get("paper_lifecycle_halted") and not state.get("paper_cycle_in_progress")
    finally:
        database.close()


def test_integrity_stop_keeps_the_book_and_a_corrected_restart_continues(review_case, tmp_path, monkeypatch):
    bot, database, _, _ = forward_bot(review_case, tmp_path, monkeypatch)
    try:
        assert bot.run().paper_trades_opened == 1
    finally:
        database.close()
    bot, database, client, _ = forward_bot(review_case, tmp_path, monkeypatch)
    try:
        _shift_ticks(client, 3600)
        summary = bot.run()
        assert summary.exit_reason == "MARKET_DATA_INTEGRITY_FAILED" and summary.lifecycle_halted is False
        assert summary.open_trades == 1
    finally:
        database.close()
    bot, database, _, _ = forward_bot(review_case, tmp_path, monkeypatch)
    try:
        summary = bot.run()
        assert summary.cycles_completed == 1 and summary.lifecycle_halted is False
    finally:
        database.close()


def test_small_clock_skew_is_skipped_with_the_rejection_reason(review_case, tmp_path, monkeypatch):
    bot, database, client, _ = forward_bot(review_case, tmp_path, monkeypatch, cycles=2)
    try:
        _shift_ticks(client, 1)
        summary = bot.run()
        assert summary.exit_reason == "PAPER_CYCLE_SKIPPED" and summary.skip_reason == "EVENT_QUOTES_MISSING"
        assert summary.lifecycle_halted is False and summary.cycles_skipped == 2
        import json
        payload = json.loads(_events(database, "PAPER_CYCLE_SKIPPED")[0]["payload_json"])
        assert payload["quote_rejections"]["EURUSD"]["tick_time_status"] == "FUTURE_TOO_FAR"
        assert payload["quote_rejections"]["EURUSD"]["integrity_failure"] is False
    finally:
        database.close()


def test_declared_ny_close_server_time_accepts_server_stamped_ticks(review_case, tmp_path, monkeypatch):
    case = {**review_case, "config": replace(review_case["config"], mt5_server_time="NY_CLOSE")}
    bot, database, client, clock = forward_bot(case, tmp_path, monkeypatch)
    try:
        offset = server_offset_seconds("NY_CLOSE", clock.now_utc())
        assert offset == 7200  # January: New York standard time
        _shift_ticks(client, offset)
        summary = bot.run()
        assert summary.cycles_completed == 1 and summary.paper_trades_opened == 1
    finally:
        database.close()
    # The same server-stamped ticks under the default UTC declaration are an integrity stop.
    bot, database, client, _ = forward_bot(review_case, tmp_path / "utc", monkeypatch)
    try:
        _shift_ticks(client, offset)
        assert bot.run().exit_reason == "MARKET_DATA_INTEGRITY_FAILED"
    finally:
        database.close()


class ScriptedClient:
    """Wraps the review client: scripted initialize() results and connectivity."""

    def __init__(self, client, initialize_results, connected_by_account_read):
        self.client, self.initialize_results = client, list(initialize_results)
        self.connected_by_account_read = connected_by_account_read

    def __getattr__(self, name):
        return getattr(self.client, name)

    def initialize(self):
        return self.initialize_results.pop(0) if self.initialize_results else True

    def terminal_info(self):
        connected = self.connected_by_account_read(self.client.account_reads)
        return SimpleNamespace(connected=connected, trade_allowed=True)


def _telegram(database):
    """Real notifier (severity filter, formatting, outbox) with a recording sender."""
    from agi_style_forex_bot_mt5.telemetry import TelegramNotifier

    sent = []

    def sender(_url, payload, _timeout):
        sent.append(payload["text"])
        return SimpleNamespace(status_code=200, text="ok", headers={})

    return TelegramNotifier(database=database, enabled=True, bot_token="123456:test-token-value",
                            chat_id="42", sender=sender), sent


def test_skip_streak_notifies_once_per_reason_and_again_on_resume(review_case, tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    bot, database, client, _ = forward_bot(review_case, tmp_path, monkeypatch, cycles=5)
    bot.telegram_notifier, sent = _telegram(database)
    # Attempts: 1-2 disconnected, 3 initialize fails, 4 completes, 5 disconnected.
    bot.mt5_client = ScriptedClient(client, [True, True, False, True], lambda reads: reads == 3)
    try:
        summary = bot.run()
        assert summary.cycles_completed == 1 and summary.cycles_skipped == 4
        assert summary.lifecycle_halted is False
        sequence = [text.split(" | ")[0] + " " + next((part for part in text.split(" | ")
                    if part.startswith("reject_code=")), "") for text in sent
                    if "PAPER_CYCLE_SKIPPED" in text or "PAPER_CYCLE_RESUMED" in text]
        assert sequence == ["[WARNING] PAPER_CYCLE_SKIPPED reject_code=MT5_CONNECTION_UNVERIFIED",
                            "[WARNING] PAPER_CYCLE_SKIPPED reject_code=MT5_CONNECT_FAILED",
                            "[INFO] PAPER_CYCLE_RESUMED ",
                            "[WARNING] PAPER_CYCLE_SKIPPED reject_code=MT5_CONNECTION_UNVERIFIED"]
        assert any("FORWARD_SHADOW_STARTED" in text for text in sent)
        assert any("FORWARD_SHADOW_STOPPED" in text for text in sent)
        assert len(_events(database, "PAPER_CYCLE_SKIPPED")) == 4
    finally:
        database.close()


def test_unpopulated_quote_after_reconnect_is_skipped_not_an_integrity_stop(review_case, tmp_path, monkeypatch):
    bot, database, client, _ = forward_bot(review_case, tmp_path, monkeypatch, cycles=2)
    original, reads = client.symbol_info_tick, []

    def first_empty(symbol):
        reads.append(symbol)
        if len(reads) == 1:
            return SimpleNamespace(bid=0.0, ask=0.0, time=0, time_msc=0)
        return original(symbol)

    client.symbol_info_tick = first_empty
    try:
        summary = bot.run()
        assert summary.exit_reason != "MARKET_DATA_INTEGRITY_FAILED"
        assert summary.cycles_skipped == 1 and summary.cycles_completed == 1
    finally:
        database.close()


def test_a_symbol_failing_integrity_is_notified_once_while_others_continue(review_case, tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    bot, database, client, _ = forward_bot(review_case, tmp_path, monkeypatch, symbols=("EURUSD", "GBPUSD"), cycles=3)
    bot.telegram_notifier, sent = _telegram(database)
    original = client.symbol_info_tick

    def gbpusd_ahead(symbol):
        tick = original(symbol)
        if symbol != "GBPUSD":
            return tick
        return SimpleNamespace(bid=tick.bid, ask=tick.ask, time=tick.time + 3600, time_msc=tick.time_msc + 3_600_000)

    client.symbol_info_tick = gbpusd_ahead
    try:
        summary = bot.run()
        assert summary.cycles_completed == 3 and summary.exit_reason != "MARKET_DATA_INTEGRITY_FAILED"
        notices = [text for text in sent if "QUOTE_INTEGRITY_REJECTED" in text]
        assert len(notices) == 1 and "symbol=GBPUSD" in notices[0]
        assert len(_events(database, "QUOTE_INTEGRITY_REJECTED")) == 1
    finally:
        database.close()


def test_real_account_behind_a_disconnected_terminal_latches(review_case, tmp_path, monkeypatch):
    bot, database, client, _ = forward_bot(review_case, tmp_path, monkeypatch, cycles=3)
    client.trade_mode, client.connected = 2, False
    try:
        summary = bot.run()
        assert summary.lifecycle_halted is True and summary.cycles_skipped == 0
        assert database.get_operational_state()["halt_reason"] == "ACCOUNT_REAL_DETECTED_READ_ONLY"
    finally:
        database.close()


def test_unbounded_skip_backoff_has_a_floor_and_honours_a_stop(review_case, tmp_path, monkeypatch):
    bot, database, client, _ = forward_bot(review_case, tmp_path, monkeypatch, cycles=None)
    client.connected = False
    slept = []

    def fake_sleep(seconds):
        slept.append(seconds)
        if sum(slept) >= 15:
            request_stop_shadow(database=database, reason="test")

    monkeypatch.setattr(forward_module, "sleep", fake_sleep)
    try:
        summary = bot.run()  # cycle_seconds=0: the floor still waits 5 s, then 10 s
        assert summary.exit_reason == "STOP_REQUESTED" and summary.cycles_skipped == 2
        assert all(value <= 1 for value in slept) and sum(slept) == 15
        assert not database.get_operational_state().get("forward_shadow_stop_requested")
    finally:
        database.close()


def test_stop_request_is_honoured_between_cycles_and_cleared_by_resume(review_case, tmp_path, monkeypatch):
    bot, database, _, _ = forward_bot(review_case, tmp_path, monkeypatch, cycles=None)
    bot.cycle_seconds = 30
    monkeypatch.setattr(forward_module, "sleep", lambda _seconds: request_stop_shadow(database=database, reason="test"))
    try:
        summary = bot.run()
        assert summary.cycles_completed == 1 and summary.exit_reason == "STOP_REQUESTED"
        assert summary.lifecycle_halted is False and not database.get_operational_state().get("paper_cycle_in_progress")
        assert [row for row in _events(database, "FORWARD_SHADOW_STOPPED") if "STOP_REQUESTED" in row["payload_json"]]
        request_stop_shadow(database=database, reason="stale")
        resume_shadow(database=database, reason="test")
        assert not database.get_operational_state().get("forward_shadow_stop_requested")
    finally:
        database.close()


def test_request_made_after_start_prevents_any_cycle(review_case, tmp_path, monkeypatch):
    bot, database, client, _ = forward_bot(review_case, tmp_path, monkeypatch, cycles=None)
    request_stop_shadow(database=database, reason="while starting")
    try:
        summary = bot.run()
        assert summary.cycles_completed == 0 and client.account_reads == 0
        assert summary.exit_reason == "STOP_REQUESTED"
    finally:
        database.close()


def test_request_left_by_an_earlier_process_is_cleared(review_case, tmp_path, monkeypatch):
    bot, database, _, _ = forward_bot(review_case, tmp_path, monkeypatch, cycles=1)
    database.update_operational_state({"forward_shadow_stop_requested": "2026-01-01T00:00:00+00:00"})
    try:
        summary = bot.run()
        assert summary.cycles_completed == 1 and summary.exit_reason != "STOP_REQUESTED"
        assert not database.get_operational_state().get("forward_shadow_stop_requested")
        assert _events(database, "FORWARD_SHADOW_STALE_STOP_CLEARED")
    finally:
        database.close()


def test_a_requested_stop_exits_zero_even_without_mt5(monkeypatch, tmp_path):
    from agi_style_forex_bot_mt5 import cli

    class StoppedBot:
        def __init__(self, **_kwargs):
            pass

        def run(self):
            return SimpleNamespace(mode="forward-shadow", mt5_connected=False, cycles_completed=0, open_trades=0,
                paper_trades_opened=0, paper_trades_closed=0, execution_attempted=False, lifecycle_halted=False,
                exit_reason="STOP_REQUESTED")

    monkeypatch.setattr(cli, "ForwardShadowBot", StoppedBot)
    assert cli.main(["--mode", "forward-shadow", "--sqlite", str(tmp_path / "f.sqlite3")]) == 0


def test_first_ctrl_c_finishes_the_cycle_and_the_handler_is_restored(review_case, tmp_path, monkeypatch):
    bot, database, _, _ = forward_bot(review_case, tmp_path, monkeypatch, cycles=None)
    bot.cycle_seconds = 30
    original = signal.getsignal(signal.SIGINT)
    monkeypatch.setattr(forward_module, "sleep", lambda _seconds: signal.raise_signal(signal.SIGINT))
    try:
        summary = bot.run()
        assert summary.cycles_completed == 1 and summary.exit_reason == "STOP_REQUESTED"
        assert not database.get_operational_state().get("paper_cycle_in_progress")
        assert signal.getsignal(signal.SIGINT) is original
    finally:
        database.close()


def test_second_ctrl_c_aborts(review_case, tmp_path, monkeypatch):
    bot, database, _, _ = forward_bot(review_case, tmp_path, monkeypatch)
    restore = bot._install_sigint_handler()
    try:
        signal.raise_signal(signal.SIGINT)
        assert bot._interrupt_requested is True
        with pytest.raises(KeyboardInterrupt):
            signal.raise_signal(signal.SIGINT)
    finally:
        restore()
        database.close()


def test_two_symbols_with_the_same_integrity_rejection_each_get_their_notice(review_case, tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    bot, database, client, _ = forward_bot(review_case, tmp_path, monkeypatch,
                                           symbols=("EURUSD", "GBPUSD", "USDJPY"), cycles=1)
    bot.telegram_notifier, sent = _telegram(database)
    original = client.symbol_info_tick

    def crossed(symbol):
        tick = original(symbol)
        if symbol == "EURUSD":
            return tick
        return SimpleNamespace(bid=tick.ask, ask=tick.bid, time=tick.time, time_msc=tick.time_msc)

    client.symbol_info_tick = crossed
    try:
        assert bot.run().cycles_completed == 1
        rows = _events(database, "QUOTE_INTEGRITY_REJECTED")
        assert sorted(row["symbol"] for row in rows) == ["GBPUSD", "USDJPY"]
        outbox = database.fetch_all("telegram_outbox")
        assert sum("QUOTE_INTEGRITY_REJECTED" in row["message_redacted"] for row in outbox) == 2
    finally:
        database.close()
