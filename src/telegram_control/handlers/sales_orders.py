"""Sales order list, detail, edit (priority / quantity / notes), delete."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from ..formatters import format_sales_order_detail, format_sales_order_list
from ..keyboards import (
    confirm_delete_keyboard,
    main_menu_keyboard,
    priority_selection_keyboard,
    sales_order_detail_keyboard,
    sales_order_list_keyboard,
)
from ..api_client import ArkeAPIClient
from ..models import ProductionOrder
from .common import answer_callback, clear_awaiting, ensure_configured, handle_api_error


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

async def _build_so_status_map(client: ArkeAPIClient) -> dict[str, str]:
    """Return SO id -> production status string.

    Possible values: "completed", "in_progress", "scheduled".
    SOs not in the map have no associated PO (pending or missed).
    """
    so_po_map: dict[str, str] = getattr(client, "_so_po_map", {})
    if not so_po_map:
        return {}

    now = client.get_sim_now()
    pos = await client.get_production_orders()
    po_by_id: dict[str, ProductionOrder] = {po.id: po for po in pos}

    result: dict[str, str] = {}
    for so_id, po_id in so_po_map.items():
        po = po_by_id.get(po_id)
        if po:
            if po.ends_at and now >= po.ends_at:
                result[so_id] = "completed"
            elif po.starts_at and now >= po.starts_at:
                result[so_id] = "in_progress"
            else:
                result[so_id] = "scheduled"
        else:
            result[so_id] = "scheduled"
    return result


def _get_so_status(status_map: dict[str, str], so_id: str) -> str | None:
    return status_map.get(so_id)


def _page_from_data(data: str) -> int:
    """Extract trailing page number from callback like ``so:list:2``."""
    parts = data.split(":")
    try:
        return int(parts[-1])
    except (ValueError, IndexError):
        return 0


def _id_from_data(data: str) -> str:
    """Extract UUID from callback like ``so:d:<uuid>``."""
    return ":".join(data.split(":")[2:])


# ------------------------------------------------------------------
# /orders  +  callback list
# ------------------------------------------------------------------

async def cmd_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = await ensure_configured(update, context)
    if not client:
        return
    try:
        orders = await client.get_sales_orders()
        status_map = await _build_so_status_map(client)
    except Exception as exc:
        await handle_api_error(update, exc)
        return

    context.user_data["_sales_orders"] = orders
    context.user_data["_so_status_map"] = status_map
    await update.message.reply_text(  # type: ignore[union-attr]
        format_sales_order_list(orders, page=0, so_status=status_map, now=client.get_sim_now()),
        parse_mode="HTML",
        reply_markup=sales_order_list_keyboard(orders, page=0),
    )


async def cb_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    clear_awaiting(context)

    client = await ensure_configured(update, context)
    if not client:
        return

    try:
        orders = await client.get_sales_orders()
        status_map = await _build_so_status_map(client)
    except Exception as exc:
        await handle_api_error(update, exc)
        return

    context.user_data["_sales_orders"] = orders
    context.user_data["_so_status_map"] = status_map
    page = _page_from_data(update.callback_query.data or "")  # type: ignore[union-attr]

    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        format_sales_order_list(orders, page, so_status=status_map, now=client.get_sim_now()),
        parse_mode="HTML",
        reply_markup=sales_order_list_keyboard(orders, page),
    )


# ------------------------------------------------------------------
# Detail
# ------------------------------------------------------------------

async def cb_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    clear_awaiting(context)

    client = await ensure_configured(update, context)
    if not client:
        return

    order_id = _id_from_data(update.callback_query.data or "")  # type: ignore[union-attr]
    context.user_data["_current_so_id"] = order_id

    try:
        order = await client.get_sales_order(order_id)
    except Exception as exc:
        await handle_api_error(update, exc)
        return

    status_map: dict[str, str] = context.user_data.get("_so_status_map", {})
    prod_status = _get_so_status(status_map, order_id)

    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        format_sales_order_detail(order, production_status=prod_status, now=client.get_sim_now()),
        parse_mode="HTML",
        reply_markup=sales_order_detail_keyboard(order_id),
    )


# ------------------------------------------------------------------
# Edit priority
# ------------------------------------------------------------------

async def cb_edit_priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    clear_awaiting(context)

    order_id = _id_from_data(update.callback_query.data or "")  # type: ignore[union-attr]

    cached_orders = context.user_data.get("_sales_orders", [])
    current_pri = next((o.priority for o in cached_orders if o.id == order_id), 0)

    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        f"\u270f\ufe0f Select new priority for this order:",
        parse_mode="HTML",
        reply_markup=priority_selection_keyboard(order_id, current_pri),
    )


async def cb_set_priority(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback pattern: ``so:sp:<uuid>:<priority>``."""
    await answer_callback(update)

    client = await ensure_configured(update, context)
    if not client:
        return

    data = update.callback_query.data or ""  # type: ignore[union-attr]
    parts = data.split(":")
    order_id = parts[2]
    new_priority = int(parts[3])

    try:
        order = await client.update_sales_order_priority(order_id, new_priority)
    except Exception as exc:
        await handle_api_error(update, exc)
        return

    status_map: dict[str, str] = context.user_data.get("_so_status_map", {})
    prod_status = _get_so_status(status_map, order_id)

    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        f"\u2705 Priority updated to P{new_priority}.\n\n"
        + format_sales_order_detail(order, production_status=prod_status, now=client.get_sim_now()),
        parse_mode="HTML",
        reply_markup=sales_order_detail_keyboard(order_id),
    )


# ------------------------------------------------------------------
# Edit quantity
# ------------------------------------------------------------------

async def cb_edit_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)

    order_id = _id_from_data(update.callback_query.data or "")  # type: ignore[union-attr]
    context.user_data["awaiting_input"] = "quantity"
    context.user_data["awaiting_context"] = {"order_id": order_id}

    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        "\u270f\ufe0f Enter the new <b>quantity</b> (positive integer):",
        parse_mode="HTML",
    )


async def handle_quantity_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()  # type: ignore[union-attr]

    if not text.isdigit() or int(text) < 1:
        await update.message.reply_text(  # type: ignore[union-attr]
            "\u274c Please enter a valid positive integer.",
        )
        return

    quantity = int(text)
    order_id = context.user_data.get("awaiting_context", {}).get("order_id", "")
    clear_awaiting(context)

    client = await ensure_configured(update, context)
    if not client:
        return

    try:
        order = await client.update_sales_order_quantity(order_id, quantity)
    except Exception as exc:
        await handle_api_error(update, exc)
        return

    status_map: dict[str, str] = context.user_data.get("_so_status_map", {})
    prod_status = _get_so_status(status_map, order_id)

    await update.message.reply_text(  # type: ignore[union-attr]
        f"\u2705 Quantity updated to {quantity}.\n\n"
        + format_sales_order_detail(order, production_status=prod_status, now=client.get_sim_now()),
        parse_mode="HTML",
        reply_markup=sales_order_detail_keyboard(order_id),
    )


# ------------------------------------------------------------------
# Edit notes
# ------------------------------------------------------------------

async def cb_edit_notes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)

    order_id = _id_from_data(update.callback_query.data or "")  # type: ignore[union-attr]
    context.user_data["awaiting_input"] = "notes"
    context.user_data["awaiting_context"] = {"order_id": order_id}

    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        "\U0001f4dd Type the new <b>notes</b> for this order\n"
        "(or send a single <code>-</code> to clear):",
        parse_mode="HTML",
    )


async def handle_notes_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()  # type: ignore[union-attr]
    notes = "" if text == "-" else text

    order_id = context.user_data.get("awaiting_context", {}).get("order_id", "")
    clear_awaiting(context)

    client = await ensure_configured(update, context)
    if not client:
        return

    try:
        order = await client.update_sales_order_notes(order_id, notes)
    except Exception as exc:
        await handle_api_error(update, exc)
        return

    status_map: dict[str, str] = context.user_data.get("_so_status_map", {})
    prod_status = _get_so_status(status_map, order_id)

    await update.message.reply_text(  # type: ignore[union-attr]
        "\u2705 Notes updated.\n\n"
        + format_sales_order_detail(order, production_status=prod_status, now=client.get_sim_now()),
        parse_mode="HTML",
        reply_markup=sales_order_detail_keyboard(order_id),
    )


# ------------------------------------------------------------------
# Delete
# ------------------------------------------------------------------

async def cb_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    clear_awaiting(context)

    order_id = _id_from_data(update.callback_query.data or "")  # type: ignore[union-attr]

    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        "\u26a0\ufe0f <b>Confirm deletion</b>\n\n"
        "This will cancel the sales order. If it was already scheduled, "
        "the corresponding production order will also be affected.\n\n"
        "Are you sure?",
        parse_mode="HTML",
        reply_markup=confirm_delete_keyboard(order_id),
    )


async def cb_confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)

    client = await ensure_configured(update, context)
    if not client:
        return

    order_id = _id_from_data(update.callback_query.data or "")  # type: ignore[union-attr]

    try:
        await client.delete_sales_order(order_id)
    except Exception as exc:
        await handle_api_error(update, exc)
        return

    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        "\u2705 Sales order deleted.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
