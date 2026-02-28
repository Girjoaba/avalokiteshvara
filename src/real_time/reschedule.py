"""
Reschedule logic when a product order fails during the pipeline.

When move_pipeline returns STATUS_BROKEN, we persist the failure to failed_order.json,
ask the user whether to skip the failed order or restart it from phase 1,
then reschedule accordingly and return an updated schedule list.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from step3_4_create_order_schedule import (
    reschedule_orders_from_time,
    restart_order_as_new,
)

FAILED_ORDER_JSON = Path(__file__).resolve().parent.parent / "failed_order.json"


def _json_serial(obj):
    """Convert datetime (and similar) to JSON-serializable form."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def save_failed_order(
    log_entry: dict,
    schedule_index: int,
    failed_phase_id: str,
    failed_phase_name: str,
    filepath: Optional[Path] = None,
) -> None:
    """Persist failed order info to failed_order.json for reschedule."""
    path = filepath or FAILED_ORDER_JSON
    payload = {
        "schedule_index": schedule_index,
        "log_entry": log_entry,
        "failed_phase_id": failed_phase_id,
        "failed_phase_name": failed_phase_name,
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=_json_serial)


def load_failed_order(filepath: Optional[Path] = None) -> Optional[dict]:
    """Load failed order info from failed_order.json. Returns None if missing or invalid."""
    path = filepath or FAILED_ORDER_JSON
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def ask_user_skip_or_restart(
    log_entry: dict,
    failed_phase_name: str,
    prompt_fn=None,
) -> str:
    """
    Ask user whether to skip the failed product order or restart from phase 1.
    Returns "skip" or "restart".
    prompt_fn(s) can be overridden for testing or Telegram (e.g. send message, wait for reply).
    """
    so_id = log_entry.get("so_id", "?")
    product_id = log_entry.get("product_id", "?")
    msg = (
        f"\n⚠️  Order {so_id} ({product_id}) failed at phase « {failed_phase_name} ».\n"
        "  [1] Skip this product order and continue with the next from current time\n"
        "  [2] Restart this product order from phase 1 as of current time\n"
        "Choice [1=skip / 2=restart]: "
    )
    if prompt_fn is not None:
        return prompt_fn(msg)
    while True:
        choice = input(msg).strip().lower()
        if choice in ("1", "skip"):
            return "skip"
        if choice in ("2", "restart"):
            return "restart"
        print("  Please enter 1 (skip) or 2 (restart).")


def get_current_time() -> datetime:
    """Current time in UTC for rescheduling from 'now'."""
    return datetime.now(timezone.utc)


def reschedule_after_failure(
    token: str,
    schedule_log: list[dict],
    failed_order_info: dict,
    choice: str,
    current_time: Optional[datetime] = None,
) -> list:
    """
    Reschedule the order list based on user feedback after a failure.

    - skip: Remove the failed order from the schedule; reschedule the remaining
      orders (after the failed one) to run from current_time onwards.
    - restart: Reschedule the failed order from phase 1 at current_time, then
      reschedule all following orders to run after it. The failed order stays
      in the list at the same index.

    Returns the updated schedule_log (same length for restart; one shorter for skip).
    """
    idx = failed_order_info["schedule_index"]
    log_entry = failed_order_info["log_entry"]
    now = current_time if current_time is not None else get_current_time()

    if choice == "skip":
        # New schedule = entries before failed + entries after failed (rescheduled from now)
        before = schedule_log[:idx]
        after = schedule_log[idx + 1 :]
        if not after:
            return before
        _, updated_after = reschedule_orders_from_time(token, after, now)
        return before + updated_after

    if choice == "restart":
        # Reschedule failed order from phase 1 at now; then reschedule the rest after it
        end_after_failed, updated_failed_entry = restart_order_as_new(
            token, log_entry, now
        )
        before = schedule_log[:idx]
        after = schedule_log[idx + 1 :]
        if not after:
            return before + [updated_failed_entry]
        _, updated_after = reschedule_orders_from_time(
            token, after, end_after_failed
        )
        return before + [updated_failed_entry] + updated_after

    raise ValueError(f"Invalid choice: {choice}. Use 'skip' or 'restart'.")
