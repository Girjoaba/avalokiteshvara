"""Gemini-powered schedule replanner with structured JSON I/O.

``build_ai_input``  — converts domain objects into ``AIScheduleInput``
``propose_schedule_revision`` — calls Gemini, returns ``AIScheduleOutput``
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import asdict
from datetime import datetime
from typing import Sequence

from src.shared.models import (
    AIScheduleInput,
    AIScheduleOrderInput,
    AIScheduleOutput,
    AIPriorityUpdate,
    SalesOrder,
    ScheduleEntry,
)

logger = logging.getLogger(__name__)

_DT_FMT = "%Y-%m-%dT%H:%M:%SZ"

_PRODUCT_MINS: dict[str, int] = {
    "PCB-IND-100": 147,
    "MED-300": 279,
    "IOT-200": 63,
    "AGR-400": 144,
    "PCB-PWR-500": 75,
}

SYSTEM_PROMPT = """\
You are a production scheduling advisor for NovaBoard Electronics, a PCB contract manufacturer.
Your #1 JOB is to OBEY THE USER'S REORDERING / PRIORITISATION REQUEST.

FACTORY CONSTRAINTS:
- Single production line — orders run sequentially, never in parallel.
- 480 working minutes per day (08:00–16:00 shift), 7 days/week, no breaks.
- Each order's total production time = minutes_per_unit × quantity (provided in input).

PRODUCTS (total minutes per unit — already summed across all BOM phases):
  PCB-IND-100  147 min/unit
  MED-300      279 min/unit
  IOT-200       63 min/unit
  AGR-400      144 min/unit
  PCB-PWR-500   75 min/unit

CRITICAL RULES FOR REORDERING:
1. The input includes an EDF BASELINE with estimated finish times and on-time status.
   Some orders may ALREADY be late in the baseline — you cannot magically fix all of them.
2. THE USER'S REQUEST TAKES ABSOLUTE PRIORITY over EDF ordering.
   - If the user says "prioritize customer X", move ALL of customer X's orders as EARLY
     as possible so they meet their deadlines.
   - If this causes OTHER orders to become late or MORE late, THAT IS ACCEPTABLE.
   - The user is explicitly choosing which customers/orders matter most.
3. Only try to preserve deadlines for orders the user did NOT deprioritize.
4. After reordering, VERIFY your sequence by walking the clock:
   - Start at sim_now. For each order, finish = clock + production_minutes (within 480 min/day).
   - Report which orders are on time and which are late in "conflicts".

STEP-BY-STEP STRATEGY:
a) Read the user's request. Identify which customer(s)/order(s) to PROTECT.
b) Place all PROTECTED orders as early as possible in the sequence.
c) Fill remaining slots with non-protected orders in EDF order (deadline, then priority).
d) Walk the full sequence with the clock to compute finish times.
e) List any deadline violations in "conflicts" — this is informational, NOT a reason to
   undo the user's requested reorder.

YOUR TASK:
Return a JSON object with:
1. reordered_so_ids  — ALL pending order IDs in your recommended production sequence
2. priority_updates  — any priority changes you recommend (can be empty)
3. ai_comment        — 2-4 sentences: what you moved, which orders improved, which got worse
4. conflicts         — human-readable list of orders that will miss their deadline in this sequence

OUTPUT FORMAT (strict JSON, no markdown fences):
{
  "reordered_so_ids": ["id1", "id2", ...],
  "priority_updates": [
    {"sales_order_id": "...", "new_priority": 1, "reason": "..."}
  ],
  "ai_comment": "...",
  "conflicts": ["SO-XXX late by ~Xh", "..."]
}

RULES:
- reordered_so_ids MUST contain exactly the same IDs from pending_orders, just reordered.
- Do NOT reorder items in current_schedule (already in production).
- DO what the user asks even if it creates deadline violations for OTHER orders.
- Never refuse the user's request. Execute it and report the consequences.
"""


# ------------------------------------------------------------------
# Build structured input from domain objects
# ------------------------------------------------------------------

def build_ai_input(
    existing_entries: Sequence[ScheduleEntry],
    pending_orders: Sequence[SalesOrder],
    user_feedback: str,
    sim_now: datetime,
) -> AIScheduleInput:
    """Convert domain objects into the structured payload for Gemini."""
    current = [
        AIScheduleOrderInput(
            sales_order_id=e.sales_order.id,
            sales_order_internal_id=e.sales_order.internal_id,
            product_internal_id=e.sales_order.line.product_internal_id,
            qty=e.sales_order.line.quantity,
            priority=e.sales_order.priority,
            deadline=e.deadline.strftime(_DT_FMT),
            customer=e.sales_order.customer.name,
            planned_start=e.planned_start.strftime(_DT_FMT),
            planned_end=e.planned_end.strftime(_DT_FMT),
            is_existing=True,
        )
        for e in existing_entries
    ]
    pending = [
        AIScheduleOrderInput(
            sales_order_id=so.id,
            sales_order_internal_id=so.internal_id,
            product_internal_id=so.line.product_internal_id,
            qty=so.line.quantity,
            priority=so.priority,
            deadline=so.deadline.strftime(_DT_FMT),
            customer=so.customer.name,
        )
        for so in pending_orders
    ]
    return AIScheduleInput(
        sim_now=sim_now.strftime(_DT_FMT),
        user_feedback=user_feedback,
        current_schedule=current,
        pending_orders=pending,
    )


# ------------------------------------------------------------------
# Gemini call (sync, wrapped for async callers)
# ------------------------------------------------------------------

def _compute_edf_baseline(
    pending: list[AIScheduleOrderInput],
    sim_now_str: str,
) -> str:
    """Walk pending orders in EDF order and produce a human-readable baseline timeline."""
    from datetime import datetime, timedelta

    try:
        sim_now = datetime.strptime(sim_now_str, _DT_FMT)
    except ValueError:
        return "(could not compute baseline)"

    sorted_orders = sorted(pending, key=lambda o: (o.deadline, o.priority))

    lines: list[str] = []
    cursor = sim_now
    if cursor.hour < 8:
        cursor = cursor.replace(hour=8, minute=0, second=0)
    elif cursor.hour >= 16:
        cursor = (cursor + timedelta(days=1)).replace(hour=8, minute=0, second=0)

    total_mins = 0
    for o in sorted_orders:
        mins_per_unit = _PRODUCT_MINS.get(o.product_internal_id, 0)
        prod_mins = mins_per_unit * o.qty
        total_mins += prod_mins

        remaining = prod_mins
        end = cursor
        while remaining > 0:
            elapsed_today = (end.hour * 60 + end.minute) - 8 * 60
            left_in_shift = 480 - elapsed_today
            if remaining <= left_in_shift:
                end = end + timedelta(minutes=remaining)
                remaining = 0
            else:
                remaining -= left_in_shift
                end = (end + timedelta(days=1)).replace(hour=8, minute=0, second=0)

        dl = datetime.strptime(o.deadline, _DT_FMT)
        on_time = end <= dl
        slack_h = (dl - end).total_seconds() / 3600
        status = f"ON TIME (+{slack_h:.1f}h)" if on_time else f"LATE by {abs(slack_h):.1f}h"

        lines.append(
            f"  {o.sales_order_internal_id} | {o.customer} | "
            f"{o.product_internal_id} x{o.qty} | {prod_mins}min ({prod_mins/480:.1f}d) | "
            f"start {cursor.strftime('%b %d %H:%M')} -> end {end.strftime('%b %d %H:%M')} | "
            f"deadline {dl.strftime('%b %d %H:%M')} | {status}"
        )
        cursor = end

    header = (
        f"Total work: {total_mins} min = {total_mins/480:.1f} working days. "
        f"Available from {sim_now_str} to last finish: {cursor.strftime(_DT_FMT)}"
    )
    return header + "\n" + "\n".join(lines)


def _call_gemini_sync(ai_input: AIScheduleInput) -> AIScheduleOutput:
    """Synchronous Gemini call — run via ``asyncio.to_thread``."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.warning("GEMINI_API_KEY not set — returning empty AI output")
        return AIScheduleOutput(ai_comment="AI unavailable (no API key).")

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    enriched_pending = []
    for o in ai_input.pending_orders:
        d = asdict(o)
        mins_per_unit = _PRODUCT_MINS.get(o.product_internal_id, 0)
        prod_mins = mins_per_unit * o.qty
        d["production_minutes"] = prod_mins
        d["production_days"] = round(prod_mins / 480, 2)
        enriched_pending.append(d)

    edf_baseline = _compute_edf_baseline(ai_input.pending_orders, ai_input.sim_now)

    user_prompt = (
        f"Current time (sim_now): {ai_input.sim_now}\n\n"
        f"CURRENTLY IN PRODUCTION (cannot be reordered):\n"
        f"{json.dumps([asdict(e) for e in ai_input.current_schedule], indent=2)}\n\n"
        f"PENDING ORDERS TO SCHEDULE (these need ordering):\n"
        f"{json.dumps(enriched_pending, indent=2)}\n\n"
        f"EDF BASELINE (current default order — deadlines and violations):\n"
        f"{edf_baseline}\n\n"
        f"USER REQUEST: {ai_input.user_feedback}\n\n"
        f"Reorder the pending orders to satisfy the user's request. "
        f"Return the JSON response."
    )

    logger.info("Calling Gemini model=%s with %d existing + %d pending orders",
                model, len(ai_input.current_schedule), len(ai_input.pending_orders))

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=0.1,
        ),
    )

    raw_text = response.text or ""
    logger.info("Gemini response length: %d chars", len(raw_text))
    logger.debug("Gemini raw: %s", raw_text[:500])

    pending_ids = {o.sales_order_id for o in ai_input.pending_orders}
    return _parse_ai_response(raw_text, pending_ids)


# ------------------------------------------------------------------
# Response parser with robust validation
# ------------------------------------------------------------------

def _parse_ai_response(raw_text: str, pending_ids: set[str]) -> AIScheduleOutput:
    """Parse and validate the Gemini JSON response."""
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.error("Gemini returned invalid JSON: %s", raw_text[:200])
        return AIScheduleOutput(
            ai_comment="AI response was not valid JSON. Using default EDF order.",
        )

    reordered = data.get("reordered_so_ids", [])
    if not isinstance(reordered, list):
        reordered = []
    reordered = [sid for sid in reordered if isinstance(sid, str) and sid in pending_ids]

    raw_updates = data.get("priority_updates", [])
    updates: list[AIPriorityUpdate] = []
    if isinstance(raw_updates, list):
        for u in raw_updates:
            if not isinstance(u, dict):
                continue
            sid = u.get("sales_order_id", "")
            pri = u.get("new_priority", 0)
            if isinstance(sid, str) and isinstance(pri, int) and 1 <= pri <= 4:
                updates.append(AIPriorityUpdate(
                    sales_order_id=sid,
                    new_priority=pri,
                    reason=str(u.get("reason", "")),
                ))

    ai_comment = str(data.get("ai_comment", ""))

    conflicts = data.get("conflicts", [])
    if not isinstance(conflicts, list):
        conflicts = []
    conflicts = [str(c) for c in conflicts]

    return AIScheduleOutput(
        reordered_so_ids=reordered,
        priority_updates=updates,
        ai_comment=ai_comment,
        conflicts=conflicts,
    )


# ------------------------------------------------------------------
# Async public API
# ------------------------------------------------------------------

async def propose_schedule_revision(ai_input: AIScheduleInput) -> AIScheduleOutput:
    """Call Gemini in a background thread and return structured output."""
    try:
        return await asyncio.to_thread(_call_gemini_sync, ai_input)
    except Exception:
        logger.exception("Gemini API call failed")
        return AIScheduleOutput(
            ai_comment="AI analysis failed. Falling back to default EDF scheduling.",
        )
