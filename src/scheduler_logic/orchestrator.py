"""Top-level scheduling orchestrator.

``compute_schedule`` is the single entry-point called by the Telegram bot.
It reads the current API state, runs EDF on pending orders, creates POs,
generates a Gantt chart, and returns everything in a ``ScheduleResult``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from src.shared.models import (
    Customer,
    ProductionOrder,
    SalesOrder,
    SalesOrderLine,
    Schedule,
    ScheduleEntry,
    ScheduleResult,
)

from .constants import MINUTES_PER_DAY, PHASE_DURATIONS
from .gantt import generate_gantt_image
from .planning import sort_orders_edf
from .scheduling import (
    add_working_minutes,
    build_product_map,
    schedule_single_order,
    snap_to_working_hours,
)

if TYPE_CHECKING:
    from src.telegram_control.api_client import ArkeAPIClient

logger = logging.getLogger(__name__)


def _build_text_summary(entries: list[ScheduleEntry]) -> str:
    lines = ["Production Schedule (EDF)\n"]

    for i, e in enumerate(entries, 1):
        so = e.sales_order
        po = e.production_order
        status = "ON TIME" if e.on_time else "LATE"
        tag = " (existing)" if e.is_existing else ""
        slack = f"+{e.slack_hours:.0f}h" if e.on_time else f"{e.slack_hours:.0f}h"
        lines.append(
            f"{i:02d}. {so.internal_id} | {so.line.product_internal_id} "
            f"x{so.line.quantity} | "
            f"{e.planned_start.strftime('%b %d %H:%M')} -> "
            f"{e.planned_end.strftime('%b %d %H:%M')} | "
            f"Deadline: {e.deadline.strftime('%b %d')} | "
            f"{slack} | P{so.priority} | {status}{tag}"
        )

    on_time = sum(1 for e in entries if e.on_time)
    late = [e for e in entries if not e.on_time]
    lines.append(f"\nOn time: {on_time}/{len(entries)}")

    if late:
        total_work = sum(
            sum(v * e.sales_order.line.quantity
                for v in PHASE_DURATIONS.get(e.sales_order.line.product_internal_id, {}).values())
            for e in entries if not e.is_existing
        )
        lines.append(
            f"Total work for new orders: {total_work:,} min "
            f"= {total_work / MINUTES_PER_DAY:.1f} working days"
        )
        for e in late:
            late_h = abs(e.slack_hours)
            lines.append(
                f"  LATE: {e.sales_order.internal_id} | "
                f"{e.sales_order.line.product_internal_id} "
                f"x{e.sales_order.line.quantity} | late by {late_h:.1f}h"
            )

    return "\n".join(lines)


def _match_existing_pos(
    existing_pos: list[ProductionOrder],
    sales_orders: list[SalesOrder],
    so_po_map: dict[str, str],
) -> tuple[list[ScheduleEntry], set[str]]:
    """Match existing POs to SOs and return entries + set of matched SO ids."""
    so_ids_with_po: set[str] = set()
    entries: list[ScheduleEntry] = []

    for po in existing_pos:
        matched_so: SalesOrder | None = None

        so_id = next(
            (sid for sid, pid in so_po_map.items() if pid == po.id),
            None,
        )
        if so_id:
            matched_so = next((so for so in sales_orders if so.id == so_id), None)

        if not matched_so:
            for so in sales_orders:
                if so.id in so_ids_with_po:
                    continue
                pid_match = (
                    so.line.product_internal_id == po.product_internal_id
                    or so.line.product_internal_id == po.product_name
                    or so.line.product_name == po.product_name
                )
                if pid_match and so.line.quantity == po.quantity:
                    matched_so = so
                    so_po_map[so.id] = po.id
                    logger.info(
                        "Matched PO %s to SO %s by product+qty (%s x%d)",
                        po.id[:8], so.internal_id,
                        po.product_internal_id or po.product_name, po.quantity,
                    )
                    break

        if matched_so:
            so_ids_with_po.add(matched_so.id)
            on_time = po.ends_at <= matched_so.deadline
            slack_h = (matched_so.deadline - po.ends_at).total_seconds() / 3600
            entries.append(ScheduleEntry(
                production_order=po,
                sales_order=matched_so,
                planned_start=po.starts_at,
                planned_end=po.ends_at,
                deadline=matched_so.deadline,
                on_time=on_time,
                slack_hours=slack_h,
                is_existing=True,
            ))
        else:
            placeholder_so = SalesOrder(
                id="", internal_id=po.internal_id,
                customer=Customer(id="", name="\u2014"),
                line=SalesOrderLine("", po.product_name, po.product_name, po.quantity),
                deadline=po.ends_at, priority=99, status="unknown",
            )
            entries.append(ScheduleEntry(
                production_order=po,
                sales_order=placeholder_so,
                planned_start=po.starts_at,
                planned_end=po.ends_at,
                deadline=po.ends_at,
                on_time=True,
                is_existing=True,
            ))

    return entries, so_ids_with_po


def _filter_active_entries(
    entries: list[ScheduleEntry], now: datetime,
) -> list[ScheduleEntry]:
    """Keep only entries whose deadline hasn't passed and whose production
    hasn't finished yet."""
    active = []
    for e in entries:
        if e.deadline > now or e.planned_end > now:
            active.append(e)
        else:
            logger.debug(
                "Filtering out completed entry %s (deadline %s, end %s)",
                e.sales_order.internal_id, e.deadline, e.planned_end,
            )
    return active


async def build_existing_schedule(
    client: ArkeAPIClient,
) -> ScheduleResult | None:
    """Build a read-only schedule from already-existing production orders.

    Only includes entries whose deadline or production end is still in the
    future.  Returns ``None`` if there are no active entries.
    """
    existing_pos = await client.get_production_orders()
    if not existing_pos:
        return None

    sales_orders = await client.get_sales_orders()
    so_po_map: dict[str, str] = getattr(client, "_so_po_map", {})

    entries, _ = _match_existing_pos(existing_pos, sales_orders, so_po_map)

    if not hasattr(client, "_so_po_map"):
        client._so_po_map = {}
    client._so_po_map.update(so_po_map)

    sim_now = client.get_sim_now()
    entries = _filter_active_entries(entries, sim_now)
    entries.sort(key=lambda e: e.planned_start)

    if not entries:
        return None

    schedule = Schedule(
        id=str(uuid.uuid4()),
        entries=entries,
        generated_at=sim_now,
        status="accepted",
    )

    gantt_bytes = generate_gantt_image(entries, now=sim_now)
    text = _build_text_summary(entries)

    return ScheduleResult(schedule=schedule, gantt_image=gantt_bytes, text_summary=text)


async def compute_schedule(
    client: ArkeAPIClient,
    comment: str = "",
    *,
    ai_reorder: list[str] | None = None,
    ai_comment: str = "",
    ai_conflicts: list[str] | None = None,
) -> ScheduleResult:
    """Read API state, run EDF, create POs, return schedule + Gantt image.

    When *ai_reorder* is provided the pending orders are sequenced in
    that order first (any IDs not mentioned fall back to EDF at the end).
    """

    sales_orders = await client.get_sales_orders()
    existing_pos = await client.get_production_orders()
    product_map = await build_product_map(client)

    # --- Match existing POs to SOs ---
    so_po_map: dict[str, str] = getattr(client, "_so_po_map", {})
    existing_entries, so_ids_with_po = _match_existing_pos(
        existing_pos, sales_orders, so_po_map,
    )

    if not hasattr(client, "_so_po_map"):
        client._so_po_map = {}
    client._so_po_map.update(so_po_map)

    # --- Determine pending SOs (skip past-deadline orders) ---
    sim_now = client.get_sim_now()
    pending = [
        so for so in sales_orders
        if so.id not in so_ids_with_po and so.deadline > sim_now
    ]
    skipped = [
        so for so in sales_orders
        if so.id not in so_ids_with_po and so.deadline <= sim_now
    ]
    if skipped:
        logger.info(
            "Skipping %d SOs with past deadline: %s",
            len(skipped),
            ", ".join(so.internal_id for so in skipped),
        )

    if ai_reorder:
        order_map = {so.id: so for so in pending}
        reordered = [order_map[sid] for sid in ai_reorder if sid in order_map]
        remaining = sort_orders_edf(
            [so for so in pending if so.id not in set(ai_reorder)],
        )
        pending = reordered + remaining
        logger.info("Using AI-suggested order for %d/%d pending SOs",
                     len(reordered), len(pending))
    else:
        pending = sort_orders_edf(pending)

    # Line availability uses ALL existing POs (even completed ones block the line)
    if existing_pos:
        latest_end = max(po.ends_at for po in existing_pos)
        current_time = max(latest_end, snap_to_working_hours(sim_now))
    else:
        current_time = snap_to_working_hours(sim_now)

    # --- Schedule each pending SO ---
    new_entries: list[ScheduleEntry] = []
    for so in pending:
        try:
            current_time, entry = await schedule_single_order(
                client, so, product_map, current_time,
            )
            if entry:
                new_entries.append(entry)
                if not hasattr(client, "_so_po_map"):
                    client._so_po_map = {}
                client._so_po_map[so.id] = entry.production_order.id
        except Exception:
            logger.exception("Failed to schedule %s", so.internal_id)

    # Only show active entries (future deadline or still in production)
    active_existing = _filter_active_entries(existing_entries, sim_now)
    all_entries = active_existing + new_entries
    all_entries.sort(key=lambda e: e.planned_start)

    notes = ai_comment or comment
    conflicts = ai_conflicts or []

    schedule = Schedule(
        id=str(uuid.uuid4()),
        entries=all_entries,
        generated_at=sim_now,
        status="proposed",
        notes=notes,
        conflicts=conflicts,
    )

    gantt_bytes = generate_gantt_image(all_entries, now=sim_now)
    text = _build_text_summary(all_entries)

    return ScheduleResult(
        schedule=schedule,
        gantt_image=gantt_bytes,
        text_summary=text,
    )
