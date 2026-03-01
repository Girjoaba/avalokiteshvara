"""Production order list, detail, and remove handlers."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from ..formatters import format_production_order_detail, format_production_order_list
from ..keyboards import (
    production_order_detail_keyboard,
    production_order_list_keyboard,
)
from .common import answer_callback, clear_awaiting, ensure_configured, handle_api_error

logger = logging.getLogger(__name__)


def _page_from_data(data: str) -> int:
    parts = data.split(":")
    try:
        return int(parts[-1])
    except (ValueError, IndexError):
        return 0


def _id_from_data(data: str) -> str:
    return ":".join(data.split(":")[2:])


# ------------------------------------------------------------------
# /production + callback list
# ------------------------------------------------------------------

async def cmd_production(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = await ensure_configured(update, context)
    if not client:
        return
    try:
        orders = await client.get_production_orders()
    except Exception as exc:
        await handle_api_error(update, exc)
        return

    context.user_data["_production_orders"] = orders
    await update.message.reply_text(  # type: ignore[union-attr]
        format_production_order_list(orders, page=0),
        parse_mode="HTML",
        reply_markup=production_order_list_keyboard(orders, page=0),
    )


async def cb_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    clear_awaiting(context)

    client = await ensure_configured(update, context)
    if not client:
        return

    try:
        orders = await client.get_production_orders()
    except Exception as exc:
        await handle_api_error(update, exc)
        return

    context.user_data["_production_orders"] = orders
    page = _page_from_data(update.callback_query.data or "")  # type: ignore[union-attr]

    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        format_production_order_list(orders, page),
        parse_mode="HTML",
        reply_markup=production_order_list_keyboard(orders, page),
    )


# ------------------------------------------------------------------
# Detail (with phases)
# ------------------------------------------------------------------

async def cb_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    clear_awaiting(context)

    client = await ensure_configured(update, context)
    if not client:
        return

    order_id = _id_from_data(update.callback_query.data or "")  # type: ignore[union-attr]

    try:
        order = await client.get_production_order(order_id)
    except Exception as exc:
        await handle_api_error(update, exc)
        return

    sim_now = client.get_sim_now()
    try:
        await update.callback_query.edit_message_text(  # type: ignore[union-attr]
            format_production_order_detail(order, now=sim_now),
            parse_mode="HTML",
            reply_markup=production_order_detail_keyboard(order_id),
        )
    except BadRequest as exc:
        if "not modified" in str(exc).lower():
            pass
        else:
            raise


# ------------------------------------------------------------------
# Remove PO from queue
# ------------------------------------------------------------------

async def cb_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    clear_awaiting(context)

    client = await ensure_configured(update, context)
    if not client:
        return

    order_id = _id_from_data(update.callback_query.data or "")  # type: ignore[union-attr]

    deleted = False
    try:
        await client.delete_production_order(order_id)
        deleted = True
    except Exception:
        logger.warning("Could not delete PO %s from API", order_id[:12])

    so_id_to_remove = None
    for sid, pid in list(getattr(client, "_so_po_map", {}).items()):
        if pid == order_id:
            so_id_to_remove = sid
            break
    if so_id_to_remove:
        client._so_po_map.pop(so_id_to_remove, None)
    client._known_po_ids.discard(order_id)
    client._current_schedule = None
    context.user_data.pop("_schedule", None)

    header = (
        "\u2705 <b>Production order removed from queue.</b>"
        if deleted
        else "\u26a0\ufe0f <b>Could not delete from API</b> "
             "(may already be in progress).\n"
             "Removed from local tracking."
    )

    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        header + "\n\nUse <b>New Schedule</b> to reschedule the freed slot.",
        parse_mode="HTML",
        reply_markup=production_order_list_keyboard(
            await client.get_production_orders(), page=0,
        ),
    )
