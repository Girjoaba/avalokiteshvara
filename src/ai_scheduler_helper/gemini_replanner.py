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

SYSTEM_PROMPT = """\
You are a production scheduling advisor for NovaBoard Electronics, a PCB contract manufacturer.

FACTORY CONSTRAINTS:
- Single production line — orders run sequentially, never in parallel
- 480 min/day (08:00–16:00), 7 days/week
- Phase time = duration_per_unit × quantity
- Each order follows its product's BOM phase sequence

PRODUCTS (minutes per unit per phase):
  PCB-IND-100: SMT(30) Reflow(15) THT(45) AOI(12) Test(30) Coating(9) Pack(6) = 147 min/unit
  MED-300:     SMT(45) Reflow(30) THT(60) AOI(30) Test(90) Coating(15) Pack(9) = 279 min/unit
  IOT-200:     SMT(18) Reflow(12) AOI(9) Test(18) Pack(6) = 63 min/unit
  AGR-400:     SMT(30) Reflow(15) THT(30) AOI(12) Test(45) Coating(12) = 144 min/unit
  PCB-PWR-500: SMT(24) Reflow(12) AOI(9) Test(24) Pack(6) = 75 min/unit

SCHEDULING POLICY — Earliest Deadline First (EDF):
- Primary sort: deadline (earliest first)
- Tie-break: priority (1 = critical, 2 = high, 3 = normal, 4 = low)
- CRITICAL RULE: A tighter deadline ALWAYS takes precedence over higher priority.
  SO-003 (deadline Mar 4, P2) MUST come before SO-005 (deadline Mar 8, P1)
  even though SO-005 has higher priority.  EDF prevents deadline damage.

YOUR TASK:
Given the current schedule state and the user's feedback, produce a JSON object with:
1. reordered_so_ids  — ALL pending order IDs in your recommended sequence
2. priority_updates  — any priority changes you recommend (can be empty)
3. ai_comment        — 2-4 sentence explanation addressing the user's concerns
4. conflicts         — list of detected scheduling risks or conflicts

OUTPUT FORMAT (strict JSON, no markdown fences):
{
  "reordered_so_ids": ["id1", "id2", ...],
  "priority_updates": [
    {"sales_order_id": "...", "new_priority": 1, "reason": "..."}
  ],
  "ai_comment": "...",
  "conflicts": ["..."]
}

RULES:
- reordered_so_ids MUST contain exactly the IDs from pending_orders, reordered
- new_priority must be 1-4
- Do NOT reorder items listed in current_schedule (they are already in production)
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

def _call_gemini_sync(ai_input: AIScheduleInput) -> AIScheduleOutput:
    """Synchronous Gemini call — run via ``asyncio.to_thread``."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.warning("GEMINI_API_KEY not set — returning empty AI output")
        return AIScheduleOutput(ai_comment="AI unavailable (no API key).")

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    payload = json.dumps(asdict(ai_input), indent=2)
    user_prompt = (
        f"Current time: {ai_input.sim_now}\n\n"
        f"CURRENTLY IN PRODUCTION (cannot be reordered):\n"
        f"{json.dumps([asdict(e) for e in ai_input.current_schedule], indent=2)}\n\n"
        f"PENDING ORDERS TO SCHEDULE (these need ordering):\n"
        f"{json.dumps([asdict(e) for e in ai_input.pending_orders], indent=2)}\n\n"
        f"USER FEEDBACK: {ai_input.user_feedback}\n\n"
        f"Respond with the JSON schedule adjustment."
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
