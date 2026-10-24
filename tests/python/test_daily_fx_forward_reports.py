"""Paper trades, Telegram channel messages and the weekly routine of the forward tracking (synthetic data only)."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import time

import numpy as np
import pandas as pd
import pytest

from agi_style_forex_bot_mt5.research.daily_fx import forward_routine, forward_runner
from agi_style_forex_bot_mt5.research.daily_fx.data import MT5_USD_PAIRS
from agi_style_forex_bot_mt5.research.daily_fx.forward import load_broker_daily, run_forward
from agi_style_forex_bot_mt5.research.daily_fx.forward_routine import (Completed, RoutinePaths,
    needed_inflation_year, run_routine)
from agi_style_forex_bot_mt5.research.daily_fx.forward_telegram import (DISCLAIMER, alert_message, build_messages,
    deliver)
from agi_style_forex_bot_mt5.research.daily_fx.forward_trades import ReportUnavailable, rebuild_trades
from agi_style_forex_bot_mt5.research.daily_fx.portfolio import backtest
from agi_style_forex_bot_mt5.research.trial_registry import TrialLedger
from agi_style_forex_bot_mt5.telemetry.database import TelemetryDatabase
from agi_style_forex_bot_mt5.telemetry.telegram_notifier import TelegramNotifier
from test_daily_fx_forward import PLAN, _base_csv, _base_inflation, _export, _snapshot, _supplement

NOW = datetime(2027, 4, 2, tzinfo=timezone.utc)


def _record(tmp_path, folder, plan=PLAN):
    ledger = TrialLedger(tmp_path / "ledger.jsonl")
    prices = load_broker_daily(folder, plan.currencies, plan.price_start)
    run_forward(plan, prices, _base_inflation(), plan.inflation_base_sha256, _supplement(), [], ledger, NOW)
    return prices, ledger


def _book(tmp_path, end="2027-03-31"):
    folder = _export(tmp_path / "prices", end=end)
    prices, ledger = _record(tmp_path, folder)
    return rebuild_trades(PLAN, prices, _base_inflation(), ledger), prices


def test_trades_rebuild_the_sealed_record_and_add_up(tmp_path):
    book, prices = _book(tmp_path)
    assert book.trades and book.through_day == "2027-03-31" and book.forward_start == "2026-10-26"
    assert len({trade.trade_id for trade in book.trades}) == len(book.trades)
    for trade in book.trades:
        assert trade.side in {"BUY", "SELL"} and 0.0 < trade.risk_percent <= 0.5 + 1e-9
        low, high = sorted([trade.stop_loss, trade.take_profit])
        assert low < trade.open_price < high
        assert (trade.stop_loss < trade.open_price) == (trade.side == "BUY")
        if trade.closed_on:
            assert trade.reason in {"SL", "TP", "REBALANCE"} and trade.closed_on >= book.forward_start
        assert trade.opened_before_start == (trade.opened_on < book.forward_start)
    # The trades' results add up to the book's gross return over the forward days.
    inflation = _base_inflation()
    from agi_style_forex_bot_mt5.research.daily_fx.forward import assemble_inflation
    table = assemble_inflation(inflation, 2024, {}, _supplement())[0]
    result = backtest(prices.panel.prices.loc[:book.through_day], PLAN.config, PLAN.costs, PLAN.limits,
                      inflation=table)
    gross = 100.0 * result.contributions.loc[book.forward_start:book.through_day].to_numpy().sum()
    assert sum(trade.pnl_percent for trade in book.trades) == pytest.approx(gross, abs=1e-9)


def _crash(folder, code, start, factor):
    """Move a currency's USD price by ``factor`` from ``start`` on (bars of the pair)."""

    symbol, usd_base = MT5_USD_PAIRS[code]
    path = folder / f"{symbol}_D1.csv"
    frame = pd.read_csv(path)
    later = frame["timestamp_utc"] >= start
    frame.loc[later, "close"] = frame.loc[later, "close"] / factor if usd_base else frame.loc[later, "close"] * factor
    frame.to_csv(path, index=False)


def test_a_crash_against_a_position_closes_it_at_its_stop(tmp_path):
    book, _ = _book(tmp_path / "first", end="2026-11-27")
    held = next(trade for trade in book.open() if trade.opened_before_start)
    long_currency = (held.side == "BUY") != MT5_USD_PAIRS[held.currency][1]
    crashed = _export(tmp_path / "crash", end="2027-01-29")
    _crash(crashed, held.currency, "2026-11-04", 0.85 if long_currency else 1.0 / 0.85)
    prices, ledger = _record(tmp_path / "crash_run", crashed)
    rebuilt = rebuild_trades(PLAN, prices, _base_inflation(), ledger)
    stopped = next(trade for trade in rebuilt.trades if trade.trade_id == held.trade_id)
    assert stopped.closed_on == "2026-11-04" and stopped.reason == "SL" and stopped.pnl_percent < 0
    assert (stopped.pips < 0) and stopped.opened_before_start


def test_a_loss_halt_that_keeps_a_position_keeps_its_stop_and_take_profit(tmp_path):
    # Tight halts block many rebalances: the engine keeps those weights and their old levels.
    plan = replace(PLAN, limits=replace(PLAN.limits, daily_loss_halt=0.002, floating_loss_halt=0.002))
    folder = _export(tmp_path / "prices", end="2027-03-31")
    prices, ledger = _record(tmp_path, folder, plan=plan)
    from agi_style_forex_bot_mt5.research.daily_fx.forward import assemble_inflation
    table = assemble_inflation(_base_inflation(), 2024, {}, _supplement())[0]
    result = backtest(prices.panel.prices.loc[:"2027-03-31"], plan.config, plan.costs, plan.limits,
                      inflation=table)
    assert result.blocked_rebalances > 0 and result.stops > 0
    # The derived stop-loss and take-profit closes must match the engine's, or it refuses (TRADES_MISMATCH).
    book = rebuild_trades(plan, prices, _base_inflation(), ledger)
    assert book.trades


def test_the_report_refuses_a_book_that_does_not_reproduce_the_record(tmp_path):
    folder = _export(tmp_path / "prices", end="2027-01-29")
    prices = load_broker_daily(folder, PLAN.currencies, PLAN.price_start)
    with pytest.raises(ReportUnavailable, match="NO_RECORD"):
        rebuild_trades(PLAN, prices, _base_inflation(), TrialLedger(tmp_path / "empty.jsonl"))
    prices, ledger = _record(tmp_path, folder)
    other = replace(PLAN, costs=replace(PLAN.costs, financing_bps_per_year=10.0))
    with pytest.raises(ReportUnavailable, match="RECORD_MISMATCH"):
        rebuild_trades(other, prices, _base_inflation(), ledger, plan_hash=PLAN.plan_hash())
    with pytest.raises(ReportUnavailable, match="LEDGER_MISMATCH"):
        rebuild_trades(other, prices, _base_inflation(), ledger)


def test_messages_read_like_a_trading_channel_and_always_say_paper(tmp_path):
    book, _ = _book(tmp_path)
    messages = build_messages(book)
    kinds = [message.kind for message in messages]
    assert kinds[0] == "start" and "week" in kinds and "open" in kinds
    assert all("papel" in message.text and message.text.endswith(DISCLAIMER) for message in messages)
    assert [message.on for message in messages] == sorted(message.on for message in messages)
    opened = next(message for message in messages if message.kind == "open")
    assert ("COMPRA" in opened.text or "VENTA" in opened.text) and "Stop loss" in opened.text
    assert "Take profit" in opened.text and "Riesgo hasta el stop:" in opened.text and "(máximo 0,50%)" in opened.text
    week = [message for message in messages if message.kind == "week"]
    assert week[0].text.startswith("📊 Resumen semanal 26-10-2026 a 30-10-2026")
    assert "Acumulado" in week[-1].text and "Abiertas (" in week[-1].text and "Regla: EN CURSO" in week[-1].text
    assert "No es dinero real" in week[-1].text
    closes = [message for message in messages if message.kind == "close"]
    for message in closes:
        assert "CERRADA" in message.text and "pips" in message.text and "del capital" in message.text
    early = [trade for trade in book.closed() if trade.opened_before_start]
    assert early and all("desde el inicio del seguimiento (26-10-2026)" in message.text for message in closes
                         if message.key in {f"forward:close:{trade.trade_id}" for trade in early})
    # Their pips count from the last close before the start, like their result.
    for trade in early:
        sign = 1.0 if trade.side == "BUY" else -1.0
        assert trade.start_price is not None
        assert trade.pips == pytest.approx(sign * (trade.close_price - trade.start_price) / trade.pip_size)
    assert all(trade.start_price is None for trade in book.trades if not trade.opened_before_start)
    assert len({message.key for message in messages}) == len(messages)


class _Response:
    def __init__(self, status):
        self.status_code = status
        self.text = "error"

    def json(self):
        return {}


def test_each_message_is_sent_once_in_order_and_a_failure_is_retried(tmp_path):
    book, _ = _book(tmp_path, end="2026-12-31")
    messages = build_messages(book)
    calls = []

    def sender(status):
        def send(url, payload, timeout):
            calls.append(payload["text"])
            return _Response(status)
        return send

    def notifier(status, database):
        return TelegramNotifier(database=database, enabled=True, bot_token="123:abc", chat_id="42",
                                sender=sender(status))

    database = TelemetryDatabase(tmp_path / "outbox.sqlite3")
    preview = tmp_path / "preview.txt"
    # The first failure stops the run, so the channel never shows messages out of order.
    first = deliver(messages, notifier(500, database), preview=preview, pause_seconds=0)
    assert first == {"sent": 0, "skipped": 0, "disabled": 0, "failed": 1, "deferred": len(messages) - 1}
    assert preview.read_text(encoding="utf-8").count("(DEFERRED)") == len(messages) - 1
    # The retry sends the text stored when the message was first queued.
    changed = [replace(messages[0], text=messages[0].text + "\nmodificado"), *messages[1:]]
    pauses = []
    second = deliver(changed, notifier(200, database), preview=preview, pause_seconds=3.0, sleep=pauses.append)
    assert second["sent"] == len(messages) and calls[1] == messages[0].text and pauses == [3.0] * len(messages)
    third = deliver(messages, notifier(200, database), preview=preview, pause_seconds=0)
    assert third == {"sent": 0, "skipped": len(messages), "disabled": 0, "failed": 0, "deferred": 0}
    assert len(calls) == 1 + len(messages)
    text = preview.read_text(encoding="utf-8")
    assert "Resumen semanal" in text and text.count("(SKIPPED)") == len(messages)


def test_nothing_is_queued_while_telegram_is_off(tmp_path):
    book, _ = _book(tmp_path, end="2026-12-31")
    messages = build_messages(book)
    database = TelemetryDatabase(tmp_path / "outbox.sqlite3")
    quiet = TelegramNotifier(database=database, enabled=False)
    assert deliver(messages, quiet, pause_seconds=0)["disabled"] == len(messages)
    assert deliver(messages, quiet, pause_seconds=0)["disabled"] == len(messages)
    # Turning Telegram on later sends every message not sent yet.
    sent = []
    loud = TelegramNotifier(database=database, enabled=True, bot_token="123:abc", chat_id="42",
                            sender=lambda url, payload, timeout: sent.append(payload["text"]) or _Response(200))
    assert deliver(messages, loud, pause_seconds=0)["sent"] == len(messages)
    assert sent == [message.text for message in messages]


def test_alerts_say_what_to_do():
    message = alert_message("PRICES_STALE", "USDDKK", "2027-01-09")
    assert message.key == "forward:alert:PRICES_STALE:2027-01-09"
    assert "Repite la exportación" in message.text and "papel" in message.text and "USDDKK" in message.text
    assert message.text.endswith(DISCLAIMER)


def test_needed_inflation_year_follows_the_publication_rule():
    assert needed_inflation_year(datetime(2027, 6, 30, tzinfo=timezone.utc)) == 2025
    assert needed_inflation_year(datetime(2027, 7, 1, tzinfo=timezone.utc)) == 2026


# --- the weekly routine, with MT5 and the network replaced by fakes ---------------------------------------------


def _setup(tmp_path, monkeypatch):
    project, worktree = tmp_path / "project", tmp_path / "worktree"
    paths = RoutinePaths(project, worktree, tmp_path / "bot.ini")
    paths.worldbank.mkdir(parents=True)
    base = _base_csv(paths.worldbank / "cpi.csv")
    plan = replace(PLAN, inflation_base_sha256=hashlib.sha256(base.read_bytes()).hexdigest())
    monkeypatch.setitem(forward_runner.PLANS, "value_forward_v1", lambda: plan)
    plan_file = worktree / "docs/research/daily_fx_value_forward_v1/plan.json"
    assert forward_runner.main(["freeze", "--plan-file", str(plan_file)]) == 0
    return paths


class _Fake:
    """Answers the routine's subprocess calls: MT5 commands, the inflation download and the tracker."""

    def __init__(self, end="2027-03-31", files=9, export_code=0, refuse=None, fetch_code=0):
        self.end, self.files, self.export_code, self.refuse, self.fetch_code = end, files, export_code, refuse, fetch_code
        self.calls = []

    def __call__(self, args, cwd, env):
        args = list(args)
        self.calls.append(args)
        if "export-history" in args:
            _export(Path(args[args.index("--output-dir") + 1]), end=self.end)
            return Completed(self.export_code, json.dumps({"mode": "export-history", "files_created": self.files,
                                                           "mt5_connected": self.export_code != 3}), "")
        if "capture-swap-snapshot" in args:
            target = Path(args[args.index("--swap-snapshot-output") + 1])
            target.write_text(json.dumps(_snapshot(datetime(2026, 10, 25, tzinfo=timezone.utc), {})))
            return Completed(0, "{}", "")
        if "fetch-inflation" in args:
            if self.fetch_code:
                return Completed(self.fetch_code, "", json.dumps({"error": "download failed: URLError"}))
            target = Path(args[args.index("--output") + 1])
            target.write_text("Country,Country Code,Year,CPI\n" + "".join(
                f"N,{iso3},2025,2.5\n" for iso3 in ("USA", "AUS", "CAN", "CHE", "DNK", "GBR", "JPN", "NOR", "NZL",
                                                    "SWE")))
            return Completed(0, "{}", "")
        if "run" in args:
            if self.refuse:
                return Completed(2, "", json.dumps({"phase": "run", "refused": self.refuse, "error": "x"}))
            position = args.index("--plan-file") + 1
            args[position] = str(Path(cwd) / args[position])
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = forward_runner.main(args[args.index("run"):])
            return Completed(code, out.getvalue(), err.getvalue())
        raise AssertionError(f"unexpected command {args}")


def test_the_routine_runs_every_step_and_reports(tmp_path, monkeypatch):
    paths = _setup(tmp_path, monkeypatch)
    fake = _Fake()
    quiet = TelegramNotifier(database=TelemetryDatabase(tmp_path / "outbox.sqlite3"), enabled=False)
    summary = run_routine(paths, runner=fake, now=NOW, notifier=quiet)
    assert summary["exit_code"] == 0 and summary["alerts"] == []
    assert summary["steps"]["export"]["files_created"] == 9 and summary["steps"]["fetch_inflation"]["exit_code"] == 0
    assert summary["steps"]["tracker"]["appended"] is True and summary["report"]["trades"] > 0
    assert summary["telegram"]["disabled"] > 0
    assert "Resumen semanal" in (paths.runtime / "telegram_messages.txt").read_text(encoding="utf-8")
    assert list((paths.runtime / "runs").glob("routine-*.json"))
    assert [call[call.index("--mode") + 1] if "--mode" in call else call[3] for call in fake.calls] == [
        "export-history", "capture-swap-snapshot", "fetch-inflation", "run"]
    assert not (paths.runtime / "routine.lock").exists()
    # The next week, with Telegram on, the backlog goes out once and in order.
    sent = []
    loud = TelegramNotifier(database=TelemetryDatabase(tmp_path / "outbox.sqlite3"), enabled=True,
                            bot_token="123:abc", chat_id="42",
                            sender=lambda url, payload, timeout: sent.append(payload["text"]) or _Response(200))
    later = datetime(2027, 5, 1, tzinfo=timezone.utc)
    again = run_routine(paths, runner=_Fake(end="2027-04-30"), now=later, notifier=loud, pause_seconds=0)
    assert again["exit_code"] == 0 and again["telegram"]["sent"] == len(sent) > summary["telegram"]["disabled"]
    once_more = run_routine(paths, runner=_Fake(end="2027-04-30"), now=later, notifier=loud, pause_seconds=0)
    assert once_more["telegram"]["sent"] == 0 and once_more["telegram"]["skipped"] == len(sent)


def test_the_routine_reports_failures_instead_of_hiding_them(tmp_path, monkeypatch):
    paths = _setup(tmp_path, monkeypatch)
    quiet = TelegramNotifier(database=TelemetryDatabase(tmp_path / "outbox.sqlite3"), enabled=False)
    # A Telegram failure: the record is done, the messages wait for the next run (exit 4).
    failing = TelegramNotifier(database=TelemetryDatabase(tmp_path / "outbox.sqlite3"), enabled=True,
                               bot_token="123:abc", chat_id="42",
                               sender=lambda url, payload, timeout: _Response(403))
    summary = run_routine(paths, runner=_Fake(), now=NOW, notifier=failing)
    assert summary["exit_code"] == 4 and summary["telegram"]["failed"] == 1 and summary["telegram"]["deferred"] > 0
    # A report that cannot be written says so (exit 2) and never touches the ledger.
    ledger = paths.ledger.read_bytes()

    def broken(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(forward_routine, "rebuild_trades", broken)
    failed = run_routine(paths, runner=_Fake(), now=NOW, notifier=quiet)
    assert failed["exit_code"] == 2 and failed["alerts"] == ["REPORT_FAILED"]
    assert "RuntimeError: disk full" in (paths.runtime / "telegram_messages.txt").read_text(encoding="utf-8")
    assert paths.ledger.read_bytes() == ledger


def test_only_one_routine_runs_at_a_time_and_the_worktree_must_exist(tmp_path, monkeypatch):
    paths = _setup(tmp_path, monkeypatch)
    quiet = TelegramNotifier(database=TelemetryDatabase(tmp_path / "outbox.sqlite3"), enabled=False)
    lock = paths.runtime / "routine.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("")
    fake = _Fake()
    busy = run_routine(paths, runner=fake, now=NOW, notifier=quiet)
    assert busy["exit_code"] == 2 and busy["error"] == "ROUTINE_ALREADY_RUNNING" and fake.calls == [] and lock.exists()
    # A lock left by a run that died hours ago is replaced.
    old = time.time() - 4 * 3600
    os.utime(lock, (old, old))
    assert run_routine(paths, runner=fake, now=NOW, notifier=quiet)["exit_code"] == 0 and not lock.exists()
    moved = RoutinePaths(paths.project, tmp_path / "elsewhere", paths.config)
    missing = run_routine(moved, runner=_Fake(), now=NOW, notifier=quiet)
    assert missing["exit_code"] == 2 and missing["alerts"] == ["WORKTREE_MISSING"]


def test_the_routine_stops_and_alerts_on_an_incomplete_export_or_a_refusal(tmp_path, monkeypatch):
    paths = _setup(tmp_path, monkeypatch)
    quiet = TelegramNotifier(database=TelemetryDatabase(tmp_path / "outbox.sqlite3"), enabled=False)
    short = _Fake(files=8)
    summary = run_routine(paths, runner=short, now=NOW, notifier=quiet)
    assert summary["exit_code"] == 2 and summary["alerts"] == ["EXPORT_INCOMPLETE"] and len(short.calls) == 1
    offline = run_routine(paths, runner=_Fake(export_code=3), now=NOW, notifier=quiet)
    assert offline["exit_code"] == 3 and offline["alerts"] == ["MT5_UNAVAILABLE"]
    assert "MT5_UNAVAILABLE" in (paths.runtime / "telegram_messages.txt").read_text(encoding="utf-8")
    refused = run_routine(paths, runner=_Fake(refuse="FORWARD_HISTORY_CHANGED"), now=NOW, notifier=quiet)
    assert refused["exit_code"] == 2 and "FORWARD_HISTORY_CHANGED" in refused["alerts"]
    assert "No borres nada" in (paths.runtime / "telegram_messages.txt").read_text(encoding="utf-8")


def test_the_routine_waits_for_a_missing_inflation_year(tmp_path, monkeypatch):
    paths = _setup(tmp_path, monkeypatch)
    quiet = TelegramNotifier(database=TelemetryDatabase(tmp_path / "outbox.sqlite3"), enabled=False)
    run_routine(paths, runner=_Fake(), now=NOW, notifier=quiet)
    later = run_routine(paths, runner=_Fake(end="2027-09-30", fetch_code=3),
                        now=datetime(2027, 10, 2, tzinfo=timezone.utc), notifier=quiet)
    assert later["exit_code"] == 0
    assert later["alerts"] == ["INFLATION_FETCH_FAILED", "WAITING_FOR_INFLATION"]
