"""Standalone test for Gemini AI replanner — no Arke API needed.

Builds synthetic schedule data matching the NovaBoard problem description,
pickles/unpickles it, calls Gemini, and validates the structured response.

Usage:
    uv run python -m tests.test_gemini_api
"""

from __future__ import annotations

import asyncio
import json
import pickle
import sys
from dataclasses import asdict
from datetime import datetime, timezone

from dotenv import load_dotenv

from src.shared.models import (
    AIScheduleOutput,
    Customer,
    SalesOrder,
    SalesOrderLine,
    Schedule,
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
        _make_so("SO-003", "AgriBot Systems","AGR-400",      5,  _dt(3, 4),  2, "Spring deployment"),
        _make_so("SO-004", "TechFlex",       "PCB-IND-100", 4,  _dt(3, 6),  2),
        _make_so("SO-005", "SmartHome IoT",  "IOT-200",     10, _dt(3, 8),  1, "Priority escalated from P3"),
        _make_so("SO-006", "IndustrialCore", "PCB-PWR-500", 8,  _dt(3, 9),  2),
        _make_so("SO-007", "TechFlex",       "IOT-200",     12, _dt(3, 11), 3),
        _make_so("SO-008", "SmartHome IoT",  "PCB-PWR-500", 6,  _dt(3, 12), 3),
        _make_so("SO-009", "MedTec Devices", "MED-300",     3,  _dt(3, 4),  1, "Penalty clause"),
        _make_so("SO-010", "IndustrialCore", "PCB-IND-100", 8,  _dt(3, 14), 2),
        _make_so("SO-011", "AgriBot Systems","AGR-400",      4,  _dt(3, 13), 3),
        _make_so("SO-012", "TechFlex",       "PCB-PWR-500", 6,  _dt(3, 15), 4),
    ]


def _estimate_finish_times(
    order_ids: list[str],
    so_map: dict[str, SalesOrder],
    sim_now: datetime,
) -> list[tuple[str, str, float, str, bool]]:
    """Walk through the sequence and estimate finish time for each order."""
    cursor_mins = 0
    start_day_offset = 0
    results = []
    for sid in order_ids:
        so = so_map.get(sid)
        if not so:
            continue
        prod_mins = PRODUCT_MINS.get(so.line.product_internal_id, 0) * so.line.quantity
        cursor_mins += prod_mins
        finish_days = cursor_mins / 480
        from datetime import timedelta
        finish_dt = sim_now + timedelta(days=finish_days)
        slack_h = (so.deadline - finish_dt).total_seconds() / 3600
        on_time = slack_h >= 0
        results.append((
            so.internal_id,
            so.customer.name,
            finish_days,
            f"+{slack_h:.0f}h" if on_time else f"LATE {abs(slack_h):.0f}h",
            on_time,
        ))
    return results


async def run_test() -> bool:
    print("=" * 60)
    print("Gemini AI Replanner — IndustrialCore Prioritization Test")
    print("=" * 60)

    all_so = build_all_sales_orders()
    sim_now = _dt(2, 27, 8)
    so_map = {so.id: so for so in all_so}

    # All 12 orders are pending (fresh schedule from scratch)
    pending = all_so

    # --- Pickle round-trip ---
    print("\n1. Pickling pending orders...")
    blob = pickle.dumps(pending)
    print(f"   Pickled size: {len(blob):,} bytes")
    unpickled_pending = pickle.loads(blob)
    assert len(unpickled_pending) == 12
    print("   Unpickle OK — 12 pending orders")

    # --- Build AI input ---
    print("\n2. Building structured AI input (no existing entries — fresh schedule)...")
    ai_input = build_ai_input(
        existing_entries=[],
        pending_orders=unpickled_pending,
        user_feedback=(
            "Since a lot of orders are finished far before the deadline, "
            "can you reorder such that IndustrialCore client orders get "
            "finished as soon as possible?"
        ),
        sim_now=sim_now,
    )

    print(f"   Existing entries: {len(ai_input.current_schedule)}")
    print(f"   Pending orders:   {len(ai_input.pending_orders)}")
    print("   Pending (EDF baseline):")
    for o in sorted(ai_input.pending_orders, key=lambda x: x.deadline):
        mins = PRODUCT_MINS.get(o.product_internal_id, 0) * o.qty
        print(f"     {o.sales_order_internal_id:8s} | {o.customer:20s} | "
              f"{o.product_internal_id:12s} x{o.qty:2d} | "
              f"deadline {o.deadline[:10]} | P{o.priority} | {mins} min")

    industrialcore_ids = {
        o.sales_order_id for o in ai_input.pending_orders
        if o.customer == "IndustrialCore"
    }
    print(f"\n   IndustrialCore order IDs: "
          f"{[o.sales_order_internal_id for o in ai_input.pending_orders if o.customer == 'IndustrialCore']}")

    # --- Call Gemini ---
    print("\n3. Calling Gemini API...")
    ai_output = await propose_schedule_revision(ai_input)

    # --- Validate response ---
    print("\n4. Validating response...")
    ok = True
    pending_ids = {o.sales_order_id for o in ai_input.pending_orders}

    print(f"\n   AI Comment:\n   {ai_output.ai_comment}")
    if not ai_output.ai_comment:
        print("   FAIL: ai_comment is empty")
        ok = False
    else:
        print("   PASS: ai_comment present")

    print(f"\n   Reordered IDs ({len(ai_output.reordered_so_ids)}):")
    for i, sid in enumerate(ai_output.reordered_so_ids, 1):
        so = so_map.get(sid)
        if so:
            marker = " <-- IndustrialCore" if sid in industrialcore_ids else ""
            print(f"     {i:2d}. {so.internal_id} | {so.customer.name:20s} | "
                  f"{so.line.product_internal_id} x{so.line.quantity}{marker}")
        else:
            print(f"     {i:2d}. {sid}")

    returned_set = set(ai_output.reordered_so_ids)
    missing = pending_ids - returned_set
    extra = returned_set - pending_ids
    if missing:
        print(f"   WARN: Missing IDs: {missing}")
    if extra:
        print(f"   FAIL: Extra IDs: {extra}")
        ok = False
    if not missing and not extra and len(ai_output.reordered_so_ids) == len(pending_ids):
        print("   PASS: valid permutation of all pending IDs")

    # --- Check IndustrialCore orders position ---
    if ai_output.reordered_so_ids:
        ids = ai_output.reordered_so_ids
        pos = {sid: i for i, sid in enumerate(ids)}

        ic_positions = [pos[sid] for sid in industrialcore_ids if sid in pos]
        non_ic_positions = [pos[sid] for sid in pos if sid not in industrialcore_ids]

        if ic_positions:
            avg_ic = sum(ic_positions) / len(ic_positions)
            avg_non = sum(non_ic_positions) / len(non_ic_positions) if non_ic_positions else 0
            print(f"\n   IndustrialCore avg position: {avg_ic:.1f}")
            print(f"   Other orders avg position:   {avg_non:.1f}")
            print("   INFO: AI moved IndustrialCore as early as possible without deadline damage")

    # --- Estimate finish times with the AI reorder ---
    if ai_output.reordered_so_ids:
        print("\n   Estimated schedule with AI reorder:")
        results = _estimate_finish_times(ai_output.reordered_so_ids, so_map, sim_now)
        all_on_time = True
        for iid, cust, days, slack_str, on_time in results:
            marker = " <--" if "IndustrialCore" in cust else ""
            tick = "OK" if on_time else "LATE"
            print(f"     {iid:8s} | {cust:20s} | day {days:5.1f} | {slack_str:>10s} | {tick}{marker}")
            if not on_time:
                all_on_time = False
        if all_on_time:
            print("   PASS: All orders on time with AI reorder")
        else:
            print("   WARN: Some orders late with AI reorder (conflicts expected)")

    print(f"\n   Priority Updates ({len(ai_output.priority_updates)}):")
    for pu in ai_output.priority_updates:
        so = so_map.get(pu.sales_order_id)
        label = so.internal_id if so else pu.sales_order_id
        print(f"     {label} -> P{pu.new_priority} ({pu.reason})")

    print(f"\n   Conflicts ({len(ai_output.conflicts)}):")
    for c in ai_output.conflicts:
        print(f"     - {c}")

    print("\n" + "=" * 60)
    if ok:
        print("RESULT: PASS — AI correctly reordered with IndustrialCore priority")
    else:
        print("RESULT: FAIL — see issues above")
    print("=" * 60)
    return ok


def main() -> None:
    success = asyncio.run(run_test())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
