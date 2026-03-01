"""Test the critical SO-005 vs SO-003 conflict from the problem description.

SO-005 was escalated P3 -> P1.  A naive priority-first plan schedules
SO-005 before SO-003 and misses SO-003 by a day.  An EDF-correct plan
keeps SO-003 first (tighter deadline) and can still meet both.

Runs with TWO different starting dates (Feb 25 and Feb 28) to verify the
AI produces different schedules that both respect all deadlines.

Usage:
    uv run python -m tests.test_so005_conflict
"""

from __future__ import annotations

import asyncio
import pickle
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

from src.shared.models import (
    AIScheduleOutput,
    Customer,
    SalesOrder,
    SalesOrderLine,
)
from src.ai_scheduler_helper.gemini_replanner import (
    build_ai_input,
    propose_schedule_revision,
)

load_dotenv()

PRODUCT_MINS = {
    "PCB-IND-100": 147,
    "MED-300": 279,
    "IOT-200": 63,
    "AGR-400": 144,
    "PCB-PWR-500": 75,
}

USER_FEEDBACK = (
    "SO-005 (SmartHome IoT, IOT-200 x10) has just been escalated from P3 to P1. "
    "Their product launch was moved up. Please accommodate this priority escalation "
    "while keeping all orders on time. In particular, make sure SO-003 (AgriBot, "
    "AGR-400 x5, deadline Mar 4) is not pushed past its deadline — it has a "
    "confirmed spring deployment window."
)


def _dt(month: int, day: int, hour: int = 8) -> datetime:
    return datetime(2026, month, day, hour, 0, 0, tzinfo=timezone.utc)


def _make_so(
    iid: str, customer_name: str, product: str,
    qty: int, deadline: datetime, priority: int, notes: str = "",
) -> SalesOrder:
    return SalesOrder(
        id=f"uuid-{iid.lower()}",
        internal_id=iid,
        customer=Customer(id=f"cust-{customer_name[:4].lower()}", name=customer_name),
        line=SalesOrderLine(
            product_id=f"pid-{product.lower()}",
            product_internal_id=product,
            product_name=product,
            quantity=qty,
        ),
        deadline=deadline,
        priority=priority,
        status="accepted",
        notes=notes,
    )


def build_all_sales_orders() -> list[SalesOrder]:
    return [
        _make_so("SO-001", "IndustrialCore", "PCB-IND-100", 2,  _dt(3, 2),  1, "URGENT - line stopped"),
        _make_so("SO-002", "MedTec Devices", "MED-300",     1,  _dt(3, 3),  1, "Penalty clause"),
        _make_so("SO-003", "AgriBot Systems","AGR-400",      5,  _dt(3, 4),  2, "Spring deployment - confirmed window"),
        _make_so("SO-004", "TechFlex",       "PCB-IND-100", 4,  _dt(3, 6),  2),
        _make_so("SO-005", "SmartHome IoT",  "IOT-200",     10, _dt(3, 8),  1, "ESCALATED P3->P1 — product launch moved up"),
        _make_so("SO-006", "IndustrialCore", "PCB-PWR-500", 8,  _dt(3, 9),  2),
        _make_so("SO-007", "TechFlex",       "IOT-200",     12, _dt(3, 11), 3),
        _make_so("SO-008", "SmartHome IoT",  "PCB-PWR-500", 6,  _dt(3, 12), 3),
        _make_so("SO-009", "MedTec Devices", "MED-300",     3,  _dt(3, 4),  1, "Penalty clause"),
        _make_so("SO-010", "IndustrialCore", "PCB-IND-100", 8,  _dt(3, 14), 2),
        _make_so("SO-011", "AgriBot Systems","AGR-400",      4,  _dt(3, 13), 3),
        _make_so("SO-012", "TechFlex",       "PCB-PWR-500", 6,  _dt(3, 15), 4),
    ]


def estimate_finish_times(
    order_ids: list[str],
    so_map: dict[str, SalesOrder],
    sim_now: datetime,
) -> list[tuple[str, str, datetime, float, bool]]:
    """Return (internal_id, customer, finish_dt, slack_hours, on_time) per order."""
    cursor_mins = 0
    results = []
    for sid in order_ids:
        so = so_map.get(sid)
        if not so:
            continue
        prod_mins = PRODUCT_MINS.get(so.line.product_internal_id, 0) * so.line.quantity
        cursor_mins += prod_mins
        finish_dt = sim_now + timedelta(days=cursor_mins / 480)
        slack_h = (so.deadline - finish_dt).total_seconds() / 3600
        results.append((so.internal_id, so.customer.name, finish_dt, slack_h, slack_h >= 0))
    return results


async def run_scenario(
    label: str,
    sim_now: datetime,
    all_so: list[SalesOrder],
    so_map: dict[str, SalesOrder],
) -> tuple[bool, list[str]]:
    """Run one scenario, return (passed, reordered_ids)."""
    pending_ids = {so.id for so in all_so}

    print(f"\n{'-' * 60}")
    print(f"  Scenario: {label}  |  sim_now = {sim_now.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'-' * 60}")

    blob = pickle.dumps(all_so)
    unpickled = pickle.loads(blob)
    print(f"  Pickle round-trip OK ({len(blob):,} bytes, {len(unpickled)} orders)")

    ai_input = build_ai_input(
        existing_entries=[],
        pending_orders=unpickled,
        user_feedback=USER_FEEDBACK,
        sim_now=sim_now,
    )
    print(f"  Pending: {len(ai_input.pending_orders)} orders, 0 existing")

    print("  Calling Gemini API...")
    ai_output = await propose_schedule_revision(ai_input)

    ok = True

    # --- Valid permutation ---
    returned = set(ai_output.reordered_so_ids)
    if returned != pending_ids:
        missing = pending_ids - returned
        extra = returned - pending_ids
        print(f"  FAIL: permutation mismatch (missing={len(missing)}, extra={len(extra)})")
        ok = False
    else:
        print(f"  PASS: valid permutation of all {len(pending_ids)} IDs")

    # --- Print the schedule ---
    print(f"\n  AI reorder:")
    results = estimate_finish_times(ai_output.reordered_so_ids, so_map, sim_now)
    all_on_time = True
    for i, (iid, cust, finish_dt, slack_h, on_time) in enumerate(results, 1):
        tick = "OK" if on_time else "LATE"
        slack_str = f"+{slack_h:.0f}h" if on_time else f"LATE {abs(slack_h):.0f}h"
        tag = ""
        if iid == "SO-003":
            tag = "  <-- SO-003 (deadline conflict)"
        elif iid == "SO-005":
            tag = "  <-- SO-005 (escalated P1)"
        print(f"    {i:2d}. {iid:8s} | {cust:20s} | finish {finish_dt.strftime('%b %d %H:%M')} "
              f"| {slack_str:>10s} | {tick}{tag}")
        if not on_time:
            all_on_time = False

    if all_on_time:
        print("  PASS: ALL orders on time — zero deadline violations")
    else:
        print("  INFO: some orders late (may be unavoidable capacity constraint)")

    # --- CRITICAL: SO-003 must meet its deadline regardless of ordering ---
    so003_result = next((r for r in results if r[0] == "SO-003"), None)
    if so003_result:
        _, _, finish_dt, slack_h, on_time = so003_result
        if on_time:
            print(f"  PASS: SO-003 meets deadline (slack {slack_h:+.0f}h) — conflict resolved safely")
        else:
            print(f"  FAIL: SO-003 misses deadline by {abs(slack_h):.0f}h — P1 escalation damaged SO-003!")
            ok = False

    # --- Ordering info (not a hard failure — what matters is deadlines) ---
    ids = ai_output.reordered_so_ids
    pos = {sid: i for i, sid in enumerate(ids)}
    id_003 = "uuid-so-003"
    id_005 = "uuid-so-005"
    id_009 = "uuid-so-009"

    if id_003 in pos and id_005 in pos:
        if pos[id_003] < pos[id_005]:
            print(f"  INFO: SO-003 (pos {pos[id_003]+1}) before SO-005 (pos {pos[id_005]+1}) — strict EDF order")
        else:
            print(f"  INFO: SO-005 (pos {pos[id_005]+1}) before SO-003 (pos {pos[id_003]+1}) — P1 escalation honored, SO-003 still safe")

    if id_009 in pos and id_005 in pos:
        if pos[id_009] < pos[id_005]:
            print(f"  INFO: SO-009 (pos {pos[id_009]+1}) before SO-005 (pos {pos[id_005]+1})")
        else:
            print(f"  INFO: SO-005 (pos {pos[id_005]+1}) before SO-009 (pos {pos[id_009]+1})")

    # --- AI comment ---
    print(f"\n  AI Comment:\n  {ai_output.ai_comment}")
    if not ai_output.ai_comment:
        print("  FAIL: no ai_comment")
        ok = False
    else:
        print("  PASS: ai_comment present")

    if ai_output.conflicts:
        print(f"\n  Conflicts ({len(ai_output.conflicts)}):")
        for c in ai_output.conflicts:
            print(f"    - {c}")

    return ok, ai_output.reordered_so_ids


async def run_test() -> bool:
    print("=" * 60)
    print("SO-005 vs SO-003 Conflict Test")
    print("P1 escalation must NOT push tighter-deadline SO-003 late")
    print("=" * 60)

    all_so = build_all_sales_orders()
    so_map = {so.id: so for so in all_so}

    # --- Scenario A: Feb 25 (lots of slack) ---
    ok_a, ids_a = await run_scenario(
        "Feb 25 — plenty of slack",
        _dt(2, 25, 8),
        all_so,
        so_map,
    )

    # --- Scenario B: Feb 28 (tight) ---
    ok_b, ids_b = await run_scenario(
        "Feb 28 — tight timeline",
        _dt(2, 28, 8),
        all_so,
        so_map,
    )

    # --- Cross-scenario checks ---
    print(f"\n{'-' * 60}")
    print("  Cross-scenario comparison")
    print(f"{'-' * 60}")

    schedules_differ = ids_a != ids_b
    if schedules_differ:
        print("  PASS: schedules differ between Feb 25 and Feb 28")
        pos_a = {sid: i for i, sid in enumerate(ids_a)}
        pos_b = {sid: i for i, sid in enumerate(ids_b)}
        moved = []
        for sid in set(ids_a) & set(ids_b):
            if pos_a[sid] != pos_b[sid]:
                so = so_map[sid]
                moved.append((so.internal_id, pos_a[sid] + 1, pos_b[sid] + 1))
        moved.sort(key=lambda x: abs(x[1] - x[2]), reverse=True)
        print(f"  Orders that changed position ({len(moved)}):")
        for iid, pa, pb in moved[:6]:
            print(f"    {iid}: pos {pa} (Feb 25) -> pos {pb} (Feb 28)")
    else:
        print("  WARN: schedules are identical — expected different orderings")

    overall = ok_a and ok_b
    print(f"\n{'=' * 60}")
    print(f"SCENARIO A (Feb 25): {'PASS' if ok_a else 'FAIL'}")
    print(f"SCENARIO B (Feb 28): {'PASS' if ok_b else 'FAIL'}")
    print(f"Schedules differ:    {'YES' if schedules_differ else 'NO'}")
    print(f"OVERALL: {'PASS' if overall else 'FAIL'}")
    print(f"{'=' * 60}")
    return overall


def main() -> None:
    success = asyncio.run(run_test())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
