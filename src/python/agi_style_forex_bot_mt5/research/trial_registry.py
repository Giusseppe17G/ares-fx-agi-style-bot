"""Append-only ledger of every research trial (research only).

Each line is one JSON record chained to the previous line by sha256, so a
removed, reordered or edited trial is detected on read. The ledger is what
makes the number of trials honest (it feeds the deflated Sharpe ratio) and
what makes a holdout single-use: a plan whose holdout is already recorded
cannot be scored again, whatever output path a caller chooses.
Nothing here builds, checks or sends an order.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterator, Mapping

LEDGER_VERSION = "trial_ledger_v1"
GENESIS = "0" * 64


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=float)


class TrialLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def records(self) -> Iterator[dict[str, Any]]:
        """Yield every record after checking the hash chain (ValueError if broken)."""

        if not self.path.exists():
            return
        previous = GENESIS
        with self.path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    raise ValueError(f"blank line {number} in trial ledger")
                record = json.loads(line)
                body = {key: value for key, value in record.items() if key != "record_sha256"}
                if record.get("previous_sha256") != previous or \
                        sha256(_canonical(body).encode("utf-8")).hexdigest() != record.get("record_sha256"):
                    raise ValueError(f"trial ledger chain broken at line {number}")
                previous = record["record_sha256"]
                yield record

    def _last_hash(self) -> str:
        last = GENESIS
        for record in self.records():
            last = record["record_sha256"]
        return last

    def append(self, kind: str, plan_hash: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = {"ledger_version": LEDGER_VERSION, "kind": kind, "plan_hash": plan_hash,
                "recorded_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "previous_sha256": self._last_hash(), "payload": dict(payload)}
        # Round-trip so the stored body hashes exactly as it will be read back.
        body = json.loads(_canonical(body))
        record = {**body, "record_sha256": sha256(_canonical(body).encode("utf-8")).hexdigest()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical(record) + "\n")
        return record

    def has(self, kind: str, plan_hash: str) -> bool:
        return any(record["kind"] == kind and record["plan_hash"] == plan_hash for record in self.records())

    def count(self, kind: str) -> int:
        return sum(1 for record in self.records() if record["kind"] == kind)
