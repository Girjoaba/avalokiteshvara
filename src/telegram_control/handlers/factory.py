"""Handlers for factory failure actions (cancel / restart production order)."""

from __future__ import annotations

import logging
from io import BytesIO

from telegram import Update
from telegram.ext import ContextTypes

from ..formatters import format_schedule
from ..keyboards import main_menu_keyboard, schedule_view_keyboard
from .common import answer_callback, clear_awaiting, ensure_configured, handle_api_error

logger = logging.getLogger(__name__)


def _po_id_from_data(data: str) -> str:
    """Extract the production-order UUID from callback data like ``ff:cancel:<uuid>``."""
    parts = data.split(":")
    return ":".join(parts[2:]) if len(parts) > 2 else ""


async def _reschedule_and_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    header: str,
) -> None:
    """Request a fresh schedule, send the result and Gantt to the user."""
    client = context.user_data.get("api_client") or context.bot_data.get("api_client")
    if not client:
        return

    await update.callback_query.message.reply_text(  # type: ignore[union-attr]
        f"{header}\n\n\u23f3 Recalculating schedule and updating Arke dates...",
        parse_mode="HTML",
    )

    try:
        result = await client.request_new_schedule()
    except Exception as exc:
        await handle_api_error(update, exc)
        return

    sched = result.schedule
    context.user_data["_schedule"] = sched

    await update.callback_query.message.reply_text(  # type: ignore[union-attr]
        format_schedule(sched),
        parse_mode="HTML",
        reply_markup=schedule_view_keyboard(sched),
    )

    if result.gantt_image:
        await update.callback_query.message.reply_photo(  # type: ignore[union-attr]
            photo=BytesIO(result.gantt_image),
            caption="\U0001f4ca Updated Schedule \u2014 Gantt Chart",
        )


# ------------------------------------------------------------------
# Cancel: remove the production order and its sales order entirely
# ------------------------------------------------------------------

async def cb_factory_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    clear_awaiting(context)

    client = await ensure_configured(update, context)
    if not client:
        return

    po_id = _po_id_from_data(update.callback_query.data or "")  # type: ignore[union-attr]
    if not po_id:
        await update.callback_query.message.reply_text(  # type: ignore[union-attr]
            "\u26a0\ufe0f Could not identify the production order.",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return

    so_po_map: dict[str, str] = getattr(client, "_so_po_map", {})
    linked_so_id = next(
        (sid for sid, pid in so_po_map.items() if pid == po_id), None,
    )

    if linked_so_id:
        try:
            await client.delete_sales_order(linked_so_id)
            logger.info("Deleted linked SO %s for cancelled PO %s", linked_so_id[:8], po_id[:8])
        except Exception:
            logger.warning("Could not delete SO %s", linked_so_id[:8])

    await _reschedule_and_reply(
        update, context,
        header="\u274c <b>Order cancelled.</b>\n"
               "The production order and its sales order have been removed.",
    )


# ------------------------------------------------------------------
# Restart: delete the current PO but keep the SO, then reschedule
# ------------------------------------------------------------------

async def cb_factory_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    clear_awaiting(context)

    client = await ensure_configured(update, context)
    if not client:
        return

    po_id = _po_id_from_data(update.callback_query.data or "")  # type: ignore[union-attr]
    if not po_id:
        await update.callback_query.message.reply_text(  # type: ignore[union-attr]
            "\u26a0\ufe0f Could not identify the production order.",
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(),
        )
        return

    await _reschedule_and_reply(
        update, context,
        header="\U0001f504 <b>Order restarted.</b>\n"
               "The production order will be re-created from the beginning.",
    )
