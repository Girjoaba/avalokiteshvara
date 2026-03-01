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
    ProductionOrder,
    ProductionPhase,
    SalesOrder,
    SalesOrderLine,
    Schedule,
    ScheduleEntry,
)
from src.ai_scheduler_helper.gemini_replanner import (
    build_ai_input,
    propose_schedule_revision,
)

load_dotenv()


# ------------------------------------------------------------------
# Synthetic data from the NovaBoard problem description
# ------------------------------------------------------------------

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


def build_existing_entries(all_so: list[SalesOrder]) -> list[ScheduleEntry]:
    """SO-001 and SO-002 are already in production."""
    entries = []
    so_001, so_002 = all_so[0], all_so[1]

    po_001 = ProductionOrder(
        id="po-uuid-001", internal_id="PO-001",
        product_id="pid-pcb-ind-100", product_name="PCB-IND-100",
        quantity=2, starts_at=_dt(3, 1, 8), ends_at=_dt(3, 1, 12),
        status="in_progress", product_internal_id="PCB-IND-100",
        sales_order_id=so_001.id,
        phases=[
            ProductionPhase("ph-1", "SMT", "completed", _dt(3,1,8), _dt(3,1,9)),
            ProductionPhase("ph-2", "Reflow", "in_progress", _dt(3,1,9), _dt(3,1,9)),
        ],
    )
    entries.append(ScheduleEntry(
        production_order=po_001, sales_order=so_001,
        planned_start=_dt(3, 1, 8), planned_end=_dt(3, 1, 12),
        deadline=so_001.deadline, on_time=True, slack_hours=20.0,
        is_existing=True,
    ))

    po_002 = ProductionOrder(
        id="po-uuid-002", internal_id="PO-002",
        product_id="pid-med-300", product_name="MED-300",
        quantity=1, starts_at=_dt(3, 1, 12), ends_at=_dt(3, 2, 8),
        status="in_progress", product_internal_id="MED-300",
        sales_order_id=so_002.id,
        phases=[
            ProductionPhase("ph-3", "SMT", "not_ready", _dt(3,1,12), _dt(3,1,13)),
        ],
    )
    entries.append(ScheduleEntry(
        production_order=po_002, sales_order=so_002,
        planned_start=_dt(3, 1, 12), planned_end=_dt(3, 2, 8),
        deadline=so_002.deadline, on_time=True, slack_hours=24.0,
        is_existing=True,
    ))
    return entries


# ------------------------------------------------------------------
# Test runner
# ------------------------------------------------------------------

async def run_test() -> bool:
    print("=" * 60)
    print("Gemini AI Replanner — Standalone Test")
    print("=" * 60)

    all_so = build_all_sales_orders()
    existing = build_existing_entries(all_so)
    pending = all_so[2:]  # SO-003 through SO-012
    sim_now = _dt(3, 1, 14)

    existing_schedule = Schedule(
        id="test-schedule-id",
        entries=existing,
        generated_at=sim_now,
        status="accepted",
    )

    # --- Pickle round-trip ---
    print("\n1. Pickling schedule + pending orders...")
    blob = pickle.dumps((existing_schedule, pending))
    print(f"   Pickled size: {len(blob):,} bytes")

    unpickled_schedule, unpickled_pending = pickle.loads(blob)
    assert len(unpickled_schedule.entries) == 2
    assert len(unpickled_pending) == 10
    print("   Unpickle OK — 2 existing entries, 10 pending orders")

    # --- Build AI input ---
    print("\n2. Building structured AI input...")
    ai_input = build_ai_input(
        unpickled_schedule.entries,
        unpickled_pending,
        user_feedback=(
            "SO-005 was escalated to P1 by SmartHome IoT (product launch moved up). "
            "However, SO-003 (AgriBot, deadline Mar 4) and SO-009 (MedTec, deadline Mar 4) "
            "must not be delayed — their deadlines are tighter. "
            "Please reorder if needed and explain the trade-offs."
        ),
        sim_now=sim_now,
    )

    payload = json.dumps(asdict(ai_input), indent=2)
    print(f"   Payload size: {len(payload):,} chars")
    print(f"   Existing entries: {len(ai_input.current_schedule)}")
    print(f"   Pending orders:   {len(ai_input.pending_orders)}")
    pending_ids = {o.sales_order_id for o in ai_input.pending_orders}
    print(f"   Pending IDs:      {[o.sales_order_internal_id for o in ai_input.pending_orders]}")

    # --- Call Gemini ---
    print("\n3. Calling Gemini API...")
    ai_output = await propose_schedule_revision(ai_input)

    # --- Validate response ---
    print("\n4. Validating response...")
    ok = True

    print(f"\n   AI Comment: {ai_output.ai_comment}")
    if not ai_output.ai_comment:
        print("   FAIL: ai_comment is empty")
        ok = False
    else:
        print("   PASS: ai_comment present")

    print(f"\n   Reordered IDs ({len(ai_output.reordered_so_ids)}):")
    for i, sid in enumerate(ai_output.reordered_so_ids, 1):
        label = next((o.sales_order_internal_id for o in ai_input.pending_orders
                       if o.sales_order_id == sid), sid)
        print(f"     {i:2d}. {label} ({sid[:12]}...)")

    returned_set = set(ai_output.reordered_so_ids)
    missing = pending_ids - returned_set
    extra = returned_set - pending_ids
    if missing:
        print(f"   WARN: Missing IDs in reorder: {missing}")
    if extra:
        print(f"   WARN: Extra IDs in reorder: {extra}")
        ok = False
    if not missing and not extra and len(ai_output.reordered_so_ids) == len(pending_ids):
        print("   PASS: reordered_so_ids is a valid permutation of all pending IDs")
    elif not extra:
        print("   WARN: reordered_so_ids incomplete but no invalid IDs")

    print(f"\n   Priority Updates ({len(ai_output.priority_updates)}):")
    for pu in ai_output.priority_updates:
        label = next((o.sales_order_internal_id for o in ai_input.pending_orders
                       if o.sales_order_id == pu.sales_order_id), pu.sales_order_id)
        print(f"     {label} -> P{pu.new_priority} ({pu.reason})")
        if not (1 <= pu.new_priority <= 4):
            print(f"   FAIL: invalid priority {pu.new_priority}")
            ok = False

    print(f"\n   Conflicts ({len(ai_output.conflicts)}):")
    for c in ai_output.conflicts:
        print(f"     - {c}")

    # --- EDF sanity: SO-003/SO-009 should come before SO-005 ---
    id_003 = "uuid-so-003"
    id_009 = "uuid-so-009"
    id_005 = "uuid-so-005"
    if ai_output.reordered_so_ids:
        ids = ai_output.reordered_so_ids
        pos = {sid: i for i, sid in enumerate(ids)}
        if id_003 in pos and id_005 in pos:
            if pos[id_003] < pos[id_005]:
                print("\n   PASS: SO-003 (deadline Mar 4) ordered before SO-005 (deadline Mar 8) — EDF respected")
            else:
                print("\n   WARN: SO-003 ordered AFTER SO-005 — EDF may be violated")
        if id_009 in pos and id_005 in pos:
            if pos[id_009] < pos[id_005]:
                print("   PASS: SO-009 (deadline Mar 4) ordered before SO-005 (deadline Mar 8) — EDF respected")
            else:
                print("   WARN: SO-009 ordered AFTER SO-005 — EDF may be violated")

    print("\n" + "=" * 60)
    if ok:
        print("RESULT: PASS — Gemini API call succeeded with valid structured output")
    else:
        print("RESULT: FAIL — see warnings above")
    print("=" * 60)
    return ok


def main() -> None:
    success = asyncio.run(run_test())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
