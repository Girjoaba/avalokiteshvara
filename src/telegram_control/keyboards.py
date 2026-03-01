"""Inline keyboard builders for every screen in the bot."""

from __future__ import annotations

import math
from typing import Sequence

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .formatters import ORDERS_PER_PAGE
from .models import (
    PRIORITY_EMOJI,
    PRIORITY_LABEL,
    ProductionOrder,
    SalesOrder,
    Schedule,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


BACK_MENU_BTN = _btn("\u2b05\ufe0f Menu", "back:menu")


def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[BACK_MENU_BTN]])


# ------------------------------------------------------------------
# Main menu
# ------------------------------------------------------------------

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("\U0001f4ca Dashboard", "dash"),   _btn("\U0001f4cb Sales Orders", "so:list:0")],
        [_btn("\U0001f3ed Production", "po:list:0"), _btn("\U0001f4c5 Schedule", "sc:view")],
        [_btn("\U0001f504 New Schedule", "sc:req"),  _btn("\u2699\ufe0f Settings", "settings")],
    ])


# ------------------------------------------------------------------
# Sales Orders
# ------------------------------------------------------------------

def sales_order_list_keyboard(
    orders: Sequence[SalesOrder], page: int
) -> InlineKeyboardMarkup:
    total = len(orders)
    total_pages = max(1, math.ceil(total / ORDERS_PER_PAGE))
    start = page * ORDERS_PER_PAGE
    page_orders = orders[start : start + ORDERS_PER_PAGE]

    rows: list[list[InlineKeyboardButton]] = []
    for so in page_orders:
        label = (
            f"{PRIORITY_EMOJI.get(so.priority, '')} {so.internal_id} "
            f"\u00b7 {so.line.product_internal_id} \u00d7{so.line.quantity}"
        )
        rows.append([_btn(label, f"so:d:{so.id}")])

    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(_btn("\u25c0\ufe0f Prev", f"so:list:{page - 1}"))
    nav_row.append(_btn(f"{page + 1}/{total_pages}", "noop"))
    if page < total_pages - 1:
        nav_row.append(_btn("Next \u25b6\ufe0f", f"so:list:{page + 1}"))
    rows.append(nav_row)

    rows.append([BACK_MENU_BTN])
    return InlineKeyboardMarkup(rows)


def sales_order_detail_keyboard(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            _btn("\u270f\ufe0f Priority", f"so:ep:{order_id}"),
            _btn("\u270f\ufe0f Quantity", f"so:eq:{order_id}"),
            _btn("\U0001f4dd Notes", f"so:en:{order_id}"),
        ],
        [_btn("\U0001f5d1\ufe0f Delete Order", f"so:del:{order_id}")],
        [_btn("\u2b05\ufe0f Back to Orders", "so:list:0")],
    ])


def priority_selection_keyboard(
    order_id: str, current_priority: int
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in (1, 2, 3, 4):
        check = " \u2713" if p == current_priority else ""
        label = f"{PRIORITY_EMOJI.get(p, '')} P{p} \u2014 {PRIORITY_LABEL[p]}{check}"
        rows.append([_btn(label, f"so:sp:{order_id}:{p}")])
    rows.append([_btn("\u2b05\ufe0f Cancel", f"so:d:{order_id}")])
    return InlineKeyboardMarkup(rows)


def confirm_delete_keyboard(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            _btn("\u2705 Yes, delete", f"so:cd:{order_id}"),
            _btn("\u274c Cancel", f"so:d:{order_id}"),
        ],
    ])


# ------------------------------------------------------------------
# Production Orders
# ------------------------------------------------------------------

def production_order_list_keyboard(
    orders: Sequence[ProductionOrder], page: int
) -> InlineKeyboardMarkup:
    total = len(orders)
    total_pages = max(1, math.ceil(total / ORDERS_PER_PAGE))
    start = page * ORDERS_PER_PAGE
    page_orders = orders[start : start + ORDERS_PER_PAGE]

    rows: list[list[InlineKeyboardButton]] = []
    for po in page_orders:
        label = f"{po.internal_id} \u00b7 {po.product_name} \u00d7{po.quantity}"
        rows.append([_btn(label, f"po:d:{po.id}")])

    nav_row: list[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(_btn("\u25c0\ufe0f Prev", f"po:list:{page - 1}"))
    nav_row.append(_btn(f"{page + 1}/{total_pages}", "noop"))
    if page < total_pages - 1:
        nav_row.append(_btn("Next \u25b6\ufe0f", f"po:list:{page + 1}"))
    rows.append(nav_row)

    rows.append([BACK_MENU_BTN])
    return InlineKeyboardMarkup(rows)


def production_order_detail_keyboard(order_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("\U0001f504 Refresh", f"po:d:{order_id}")],
        [_btn("\U0001f5d1\ufe0f Remove from Queue", f"po:del:{order_id}")],
        [_btn("\u2b05\ufe0f Back to Production", "po:list:0")],
    ])


# ------------------------------------------------------------------
# Schedule
# ------------------------------------------------------------------

def schedule_view_keyboard(schedule: Schedule | None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if schedule and schedule.status == "proposed":
        rows.append([
            _btn("\u2705 Accept", "sc:acc"),
            _btn("\u274c Reject", "sc:rej"),
        ])
        rows.append([_btn("\U0001f4ac Comment & Revise", "sc:com")])
    rows.append([_btn("\U0001f504 Request New Schedule", "sc:req")])
    rows.append([BACK_MENU_BTN])
    return InlineKeyboardMarkup(rows)


def schedule_entry_keyboard(
    entry_count: int, current_index: int
) -> InlineKeyboardMarkup:
    nav: list[InlineKeyboardButton] = []
    if current_index > 0:
        nav.append(_btn("\u25c0\ufe0f Prev", f"sc:e:{current_index - 1}"))
    nav.append(_btn(f"{current_index + 1}/{entry_count}", "noop"))
    if current_index < entry_count - 1:
        nav.append(_btn("Next \u25b6\ufe0f", f"sc:e:{current_index + 1}"))
    return InlineKeyboardMarkup([
        nav,
        [_btn("\u2b05\ufe0f Back to Schedule", "sc:view")],
    ])


def schedule_comment_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[_btn("\u2b05\ufe0f Cancel", "sc:view")]])


# ------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------

def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [_btn("\U0001f517 Change API URL", "change_url")],
        [_btn("\U0001f552 Set Time", "set_time"), _btn("\u23e9 Set Time Rate", "set_rate")],
        [_btn("\U0001f504 Reset Clock", "reset_clock")],
        [BACK_MENU_BTN],
    ])


# ------------------------------------------------------------------
# Notification action buttons
# ------------------------------------------------------------------

def notification_action_keyboard(
    production_order_id: str = "",
    sales_order_id: str = "",
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    action_row: list[InlineKeyboardButton] = []
    if production_order_id:
        action_row.append(_btn("\U0001f3ed View PO", f"po:d:{production_order_id}"))
    if sales_order_id:
        action_row.append(_btn("\U0001f4cb View SO", f"so:d:{sales_order_id}"))
    if action_row:
        rows.append(action_row)
    rows.append([_btn("\U0001f4c5 View Schedule", "sc:view")])
    return InlineKeyboardMarkup(rows)
