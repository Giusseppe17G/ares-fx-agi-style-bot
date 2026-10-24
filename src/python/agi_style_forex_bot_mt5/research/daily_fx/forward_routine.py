"""The weekly routine of the forward paper tracking in one command (research only).

    python -m agi_style_forex_bot_mt5.research.daily_fx.forward_routine \\
        --project C:\\ruta\\ares-fx-agi-style-bot --worktree C:\\ruta\\ares-forward-v1 \\
        --config C:\\ares-config\\bot.ini

The steps, in order:

1. Export the D1 bars of the nine pairs (``--mode export-history``). The
   routine stops unless all nine files were written, because a stale pair
   would refuse the run anyway.
2. Capture the broker's swap terms (``--mode capture-swap-snapshot``). A
   failure only lowers the broker-swap coverage, so the routine continues.
3. Download the World Bank inflation when the year the signal now needs is
   missing (``forward_runner fetch-inflation``).
4. Run the tracker from the worktree pinned at the freeze commit, and keep
   its output under ``data/runtime/forward/runs``.
5. Rebuild the paper trades from the sealed record (``forward_trades``).
   Write the Telegram messages (``forward_telegram``) and the alerts for
   anything that stopped the routine.
6. Queue every message in the durable outbox. Each is sent once when
   Telegram is on (``--telegram`` or ``TELEGRAM_ENABLED=True``) and the
   ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` environment variables are
   set. While Telegram is off nothing is queued, so turning it on later
   sends every message not sent yet, in order. Every message is also written
   to ``data/runtime/forward/telegram_messages.txt``.

Only one routine runs at a time (``data/runtime/forward/routine.lock``), so
two runs can never append to the ledger together.

Exit codes:

- 0: done.
- 2: stopped or no report: an incomplete export, a tracker refusal, a report
  that cannot describe the record, another routine running or an invalid
  configuration. The alert says why.
- 3: MT5 unavailable.
- 4: done, but a Telegram message could not be sent; it is retried, in order,
  on the next run.

``--test-telegram`` only sends a test message (exit 0 if it arrived, 4 if
not). The configuration must keep ``DEMO_ONLY=True``. Nothing here reads an
account or sends an order.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable, Sequence

from ...config import load_config
from ...telemetry.database import TelemetryDatabase
from ...telemetry.telegram_notifier import TelegramNotifier
from ..trial_registry import TrialLedger
from .data import WORLD_BANK_COUNTRIES, load_worldbank_inflation
from .forward import load_broker_daily, read_inflation_supplement
from .forward_telegram import Message, alert_message, build_messages, check_message, deliver
from .forward_trades import ReportUnavailable, rebuild_trades
from .plans import value_forward_v1

SYMBOLS = "AUDUSD,USDCAD,USDCHF,USDDKK,GBPUSD,USDJPY,USDNOK,NZDUSD,USDSEK"
PLAN_FILE = Path("docs/research/daily_fx_value_forward_v1/plan.json")
INFLATION_BASE_LAST_YEAR = 2024
PUBLICATION_MONTH = 7
STALE_LOCK_SECONDS = 3 * 3600


@dataclass(frozen=True)
class RoutinePaths:
    project: Path
    worktree: Path
    config: Path

    @property
    def prices(self) -> Path:
        return self.project / "data" / "historical" / "forward"

    @property
    def worldbank(self) -> Path:
        return self.project / "data" / "historical" / "worldbank"

    @property
    def runtime(self) -> Path:
        return self.project / "data" / "runtime" / "forward"

    @property
    def symbol_map(self) -> Path:
        return self.project / "data" / "runtime" / "symbol_map_forward.json"

    @property
    def ledger(self) -> Path:
        return self.runtime / "value_forward_v1.jsonl"

    @property
    def outbox(self) -> Path:
        return self.project / "data" / "sqlite" / "forward_telegram.sqlite3"


@dataclass(frozen=True)
class Completed:
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[Sequence[str], Path, dict[str, str]], Completed]


def subprocess_runner(args: Sequence[str], cwd: Path, env: dict[str, str]) -> Completed:
    try:
        done = subprocess.run(list(args), cwd=str(cwd), env=env, capture_output=True, text=True, errors="replace",
                              timeout=1800)
    except subprocess.TimeoutExpired:
        return Completed(124, "", json.dumps({"error": "timed out after 1800 s"}))
    return Completed(done.returncode, done.stdout, done.stderr)


def _last_json(text: str) -> dict[str, Any]:
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    try:
        return json.loads(text)
    except ValueError:
        return {}


def needed_inflation_year(now: datetime) -> int:
    """The latest year the signal uses on ``now`` (year Y counts from 1 July of Y+1)."""

    return now.year - 1 if now.month >= PUBLICATION_MONTH else now.year - 2


def latest_supplement(folder: Path) -> Path | None:
    """The inflation download written last (by time, then name; manual and routine names differ)."""

    files = list(folder.glob("inflation-*.csv"))
    return max(files, key=lambda path: (path.stat().st_mtime, path.name)) if files else None


def _has_year(path: Path | None, year: int) -> bool:
    if path is None:
        return False
    try:
        table, _ = read_inflation_supplement(path, tuple(code for code in WORLD_BANK_COUNTRIES.values()
                                                         if code != "USD"))
    except (OSError, ValueError):
        return False
    return year in table.index and not table.loc[year].isna().any()


def _acquire(lock: Path) -> bool:
    """Create the lock file, replacing one left by a run that died hours ago."""

    for _ in range(2):
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            return True
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime < STALE_LOCK_SECONDS:
                    return False
                lock.unlink()
            except FileNotFoundError:
                continue
    return False


def _notifier(paths: RoutinePaths, telegram: bool) -> TelegramNotifier:
    config = load_config(paths.config)
    return TelegramNotifier.from_env(database=TelemetryDatabase(paths.outbox),
                                     enabled=bool(telegram or config.telegram_enabled))


def run_routine(paths: RoutinePaths, *, python: str = sys.executable, runner: Runner = subprocess_runner,
                now: datetime | None = None, skip_mt5: bool = False, telegram: bool = False,
                notifier: Any | None = None, pause_seconds: float = 3.0) -> dict[str, Any]:
    """Run every step, deliver the messages and return the routine's summary (with ``exit_code``)."""

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    paths.runtime.mkdir(parents=True, exist_ok=True)
    lock = paths.runtime / "routine.lock"
    if not _acquire(lock):
        return {"routine": "forward_value_v1", "started_at_utc": now.isoformat(), "alerts": [],
                "error": "ROUTINE_ALREADY_RUNNING", "execution_authorized": False, "exit_code": 2}
    try:
        return _run_steps(paths, python, runner, now, skip_mt5, telegram, notifier, pause_seconds)
    finally:
        lock.unlink(missing_ok=True)


def _run_steps(paths: RoutinePaths, python: str, runner: Runner, now: datetime, skip_mt5: bool,
               telegram: bool, notifier: Any | None, pause_seconds: float) -> dict[str, Any]:
    stamp = now.strftime("%Y%m%d-%H%M%S")
    day = now.strftime("%Y-%m-%d")
    (paths.runtime / "runs").mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONPATH": "src/python"}
    summary: dict[str, Any] = {"routine": "forward_value_v1", "started_at_utc": now.isoformat(), "steps": {},
                               "alerts": [], "execution_authorized": False}
    alerts: list[Message] = []
    exit_code = 0

    def alert(code: str, detail: str = "") -> None:
        alerts.append(alert_message(code, detail, day))
        summary["alerts"].append(code)

    if not (paths.worktree / PLAN_FILE).is_file():
        alert("WORKTREE_MISSING", str(paths.worktree))
        exit_code = 2
    if exit_code == 0 and not skip_mt5:
        export = runner([python, "-m", "agi_style_forex_bot_mt5.cli", "--mode", "export-history", "--symbols", SYMBOLS,
                         "--timeframes", "D1", "--bars", "6000", "--output-dir", str(paths.prices),
                         "--config", str(paths.config)], paths.project, env)
        exported = _last_json(export.stdout)
        summary["steps"]["export"] = {"exit_code": export.returncode, "files_created": exported.get("files_created")}
        if export.returncode == 3 or exported.get("mt5_connected") is False:
            alert("MT5_UNAVAILABLE")
            exit_code = 3
        elif export.returncode != 0 or exported.get("files_created") != len(SYMBOLS.split(",")):
            alert("EXPORT_INCOMPLETE", f"files_created={exported.get('files_created')}")
            exit_code = 2
        if exit_code == 0:
            swap = runner([python, "-m", "agi_style_forex_bot_mt5.cli", "--mode", "capture-swap-snapshot",
                           "--broker-symbol-map", str(paths.symbol_map), "--swap-snapshot-output",
                           str(paths.runtime / f"swap_snapshot-{stamp}.json"), "--config", str(paths.config)],
                          paths.project, env)
            summary["steps"]["swap_snapshot"] = {"exit_code": swap.returncode}
            if swap.returncode != 0:
                alert("SWAP_CAPTURE_FAILED", f"exit {swap.returncode}")
    if exit_code == 0:
        year = needed_inflation_year(now)
        supplement = latest_supplement(paths.worldbank)
        if year > INFLATION_BASE_LAST_YEAR and not _has_year(supplement, year):
            target = paths.worldbank / f"inflation-{stamp}.csv"
            fetched = runner([python, "-m", "agi_style_forex_bot_mt5.research.daily_fx.forward_runner",
                              "fetch-inflation", "--output", str(target)], paths.project, env)
            summary["steps"]["fetch_inflation"] = {"exit_code": fetched.returncode, "year_needed": year}
            if fetched.returncode != 0:
                alert("INFLATION_FETCH_FAILED", _last_json(fetched.stderr).get("error", ""))
            supplement = latest_supplement(paths.worldbank)
        args = [python, "-m", "agi_style_forex_bot_mt5.research.daily_fx.forward_runner", "run",
                "--plan-file", str(PLAN_FILE), "--prices-dir", str(paths.prices),
                "--inflation-base", str(paths.worldbank / "cpi.csv"), "--swap-snapshots-dir", str(paths.runtime),
                "--ledger", str(paths.ledger)]
        if supplement is not None:
            args += ["--inflation-supplement", str(supplement)]
        tracked = runner(args, paths.worktree, env)
        (paths.runtime / "runs" / f"run-{stamp}.json").write_text(
            tracked.stdout if tracked.returncode == 0 else tracked.stderr, encoding="utf-8")
        result = _last_json(tracked.stdout) if tracked.returncode == 0 else _last_json(tracked.stderr)
        summary["steps"]["tracker"] = {"exit_code": tracked.returncode,
                                       "through_day": result.get("through_day"),
                                       "appended": result.get("appended"), "refused": result.get("refused")}
        if tracked.returncode != 0:
            alert(result.get("refused") or "TRACKER_FAILED", str(result.get("error", ""))[:300])
            exit_code = 2
        elif result.get("waiting_for_inputs_on"):
            alert("WAITING_FOR_INFLATION", f"rebalance of {result['waiting_for_inputs_on']}")
    messages: list[Message] = []
    if (paths.worktree / PLAN_FILE).is_file():
        try:
            frozen = json.loads((paths.worktree / PLAN_FILE).read_text(encoding="utf-8"))
            plan = value_forward_v1()
            prices = load_broker_daily(paths.prices, plan.currencies, plan.price_start)
            base, _ = load_worldbank_inflation(paths.worldbank / "cpi.csv", plan.currencies)
            book = rebuild_trades(plan, prices, base, TrialLedger(paths.ledger), plan_hash=frozen["plan_hash"])
            messages = build_messages(book)
            summary["report"] = {"trades": len(book.trades), "closed": len(book.closed()),
                                 "open": len(book.open()), "through_day": book.through_day,
                                 "rule": book.rule.get("status")}
        except ReportUnavailable as error:
            summary["report"] = {"unavailable": error.code}
            if error.code != "NO_RECORD":  # nothing sealed yet (before the first forward day)
                alert(error.code, str(error))
                exit_code = exit_code or 2
        except Exception as error:  # the report never touches the ledger; say why it is missing
            summary["report"] = {"unavailable": type(error).__name__}
            alert("REPORT_FAILED", f"{type(error).__name__}: {error}")
            exit_code = exit_code or 2
    try:
        notifier = notifier if notifier is not None else _notifier(paths, telegram)
        summary["telegram"] = deliver([*messages, *alerts], notifier,
                                      preview=paths.runtime / "telegram_messages.txt", pause_seconds=pause_seconds)
        if summary["telegram"]["failed"]:
            exit_code = exit_code or 4
    except Exception as error:  # the summary file below still records the run
        summary["telegram"] = {"error": f"{type(error).__name__}: {error}"}
        exit_code = exit_code or 4
    summary["exit_code"] = exit_code
    (paths.runtime / "runs" / f"routine-{stamp}.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Weekly routine of the forward paper tracking (research only)")
    parser.add_argument("--project", type=Path, default=Path.cwd(), help="the bot's project folder")
    parser.add_argument("--worktree", type=Path, help="the worktree pinned at the freeze commit")
    parser.add_argument("--config", type=Path, required=True, help="the bot configuration (DEMO_ONLY=True)")
    parser.add_argument("--skip-mt5", action="store_true", help="use the exports and snapshots already on disk")
    parser.add_argument("--telegram", action="store_true",
                        help="send the messages (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from the environment)")
    parser.add_argument("--test-telegram", action="store_true", help="only send a test message and exit")
    args = parser.parse_args(argv)
    project = args.project.resolve()
    worktree = (args.worktree or project.parent / "ares-forward-v1").resolve()
    paths = RoutinePaths(project, worktree, args.config.resolve())
    try:
        load_config(args.config)  # refuses a missing file or DEMO_ONLY=False before any step
        if args.test_telegram:
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
            result = _notifier(paths, True).send_text(idempotency_key=f"forward:test:{stamp}",
                                                      text=check_message(stamp[:10]).text)
            print(json.dumps({"routine": "forward_value_v1", "telegram_test": result.status,
                              "error": result.error}))
            return 0 if result.status == "SENT" else 4
        summary = run_routine(paths, skip_mt5=args.skip_mt5, telegram=args.telegram)
    except (OSError, ValueError) as error:
        print(json.dumps({"routine": "forward_value_v1", "error": f"{type(error).__name__}: {error}"}), file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return int(summary["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
