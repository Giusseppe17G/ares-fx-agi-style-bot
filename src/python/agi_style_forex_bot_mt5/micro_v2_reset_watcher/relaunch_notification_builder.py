"""Manual relaunch notification builder."""

from __future__ import annotations

from typing import Any, Mapping


def build_relaunch_notification(recheck: Mapping[str, Any]) -> dict[str, Any]:
    ready = recheck.get("reset_gate_recheck_status") == "MICRO_V2_RESET_WATCHER_READY_FOR_MANUAL_RELAUNCH"
    return {
        "notification_status": "MICRO_V2_READY_FOR_MANUAL_RELAUNCH_NOTIFICATION" if ready else "MICRO_V2_RESET_NOT_READY_NOTIFICATION",
        "relaunch_command_available": ready,
        "message": "Micro V2 is ready for manual relaunch." if ready else "Micro V2 is not ready; keep stopped and rerun watcher later.",
        "recommended_next_action": "MANUAL_RELAUNCH_V2_PAPER_DRY_RUN" if ready else "KEEP_V2_STOPPED_AND_RERUN_RESET_WATCHER_LATER",
        "execution_attempted": False,
        "order_send_called": False,
        "order_check_called": False,
    }
