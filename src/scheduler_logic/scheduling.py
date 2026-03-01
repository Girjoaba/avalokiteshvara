"""Working-hours math and async production-order creation / phase scheduling."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from src.shared.models import (
    ProductionOrder,
    ProductionPhase,
    SalesOrder,
    ScheduleEntry,
)

from .constants import (
    DAY_END_HOUR,
    DAY_START_HOUR,
    MINUTES_PER_DAY,
    PHASE_DURATIONS,
    PHASES_ORDER,
)

if TYPE_CHECKING:
    from src.telegram_control.api_client import ArkeAPIClient

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Working-hours arithmetic
# ------------------------------------------------------------------

def add_working_minutes(start_dt: datetime, minutes: int) -> datetime:
    """Advance *start_dt* by *minutes* of production time (08:00-16:00 shifts)."""
    current = start_dt
    remaining = minutes
    while remaining > 0:
        elapsed_today = (current.hour * 60 + current.minute) - (DAY_START_HOUR * 60)
        left_in_shift = MINUTES_PER_DAY - elapsed_today
        if remaining <= left_in_shift:
            current = current + timedelta(minutes=remaining)
            remaining = 0
        else:
            remaining -= left_in_shift
            current = (current + timedelta(days=1)).replace(
                hour=DAY_START_HOUR, minute=0, second=0, microsecond=0,
            )
    return current


def snap_to_working_hours(dt: datetime) -> datetime:
    """Round *dt* up to the next valid working-hours moment."""
    if dt.hour < DAY_START_HOUR:
        return dt.replace(hour=DAY_START_HOUR, minute=0, second=0, microsecond=0)
    if dt.hour >= DAY_END_HOUR:
        nxt = dt + timedelta(days=1)
        return nxt.replace(hour=DAY_START_HOUR, minute=0, second=0, microsecond=0)
    return dt


# ------------------------------------------------------------------
# Product UUID resolution
# ------------------------------------------------------------------

async def build_product_map(client: ArkeAPIClient) -> dict[str, str]:
    """internal_id (e.g. 'PCB-IND-100') → Arke UUID."""
    products = await client.get_products()
    return {p.internal_id: p.id for p in products}


# ------------------------------------------------------------------
# Single-order scheduling
# ------------------------------------------------------------------

async def schedule_single_order(
    client: ArkeAPIClient,
    so: SalesOrder,
    product_uuid_map: dict[str, str],
    current_time: datetime,
) -> tuple[datetime, ScheduleEntry | None]:
    """Create a PO for *so*, generate & date its phases, return the updated timeline cursor."""

    product_code = so.line.product_internal_id
    quantity = so.line.quantity
    product_uuid = product_uuid_map.get(product_code)

    if not product_uuid:
        logger.warning("No UUID for product %s — skipping %s", product_code, so.internal_id)
        return current_time, None

    bom = PHASE_DURATIONS.get(product_code, {})
    if not bom:
        logger.warning("No BOM for product %s — skipping %s", product_code, so.internal_id)
        return current_time, None

    po = await client.create_production_order(
        product_id=product_uuid,
        quantity=quantity,
        starts_at=current_time,
        ends_at=so.deadline,
    )

    po = await client.schedule_production_order(po.id)

    phase_cursor = current_time
    computed_phases: list[ProductionPhase] = []

    for phase_name in PHASES_ORDER:
        mins_per_unit = bom.get(phase_name, 0)
        if mins_per_unit == 0:
            continue

        matching = next((p for p in po.phases if p.name == phase_name), None)
        if not matching:
            continue

        total_mins = mins_per_unit * quantity
        phase_end = add_working_minutes(phase_cursor, total_mins)

        await client.update_phase_dates(
            matching.id,
            starts_at=phase_cursor,
            ends_at=phase_end,
        )

        computed_phases.append(ProductionPhase(
            id=matching.id,
            name=phase_name,
            status=matching.status,
            starts_at=phase_cursor,
            ends_at=phase_end,
            duration_minutes=total_mins,
        ))
        phase_cursor = phase_end

    po_start = computed_phases[0].starts_at if computed_phases else current_time
    po_end = computed_phases[-1].ends_at if computed_phases else current_time
    on_time = po_end <= so.deadline
    slack_h = (so.deadline - po_end).total_seconds() / 3600

    try:
        await client.update_production_order_dates(
            po.id, starts_at=po_start, ends_at=po_end,
        )
    except Exception:
        logger.warning("Could not update PO %s dates on API", po.id[:12])

    scheduled_po = ProductionOrder(
        id=po.id,
        internal_id=po.internal_id,
        product_id=po.product_id,
        product_name=po.product_name or product_code,
        quantity=quantity,
        starts_at=po_start,
        ends_at=po_end,
        status=po.status,
        sales_order_id=so.id,
        phases=computed_phases,
    )

    entry = ScheduleEntry(
        production_order=scheduled_po,
        sales_order=so,
        planned_start=po_start,
        planned_end=po_end,
        deadline=so.deadline,
        on_time=on_time,
        slack_hours=slack_h,
        is_existing=False,
    )

    return phase_cursor, entry
