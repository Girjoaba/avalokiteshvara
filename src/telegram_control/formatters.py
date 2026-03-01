"""Telegram message builders (HTML parse mode).

Every ``format_*`` function returns a ready-to-send HTML string.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Sequence

from .models import (
    PHASE_STATUS_EMOJI,
    PRIORITY_EMOJI,
    PRIORITY_LABEL,
    STATUS_EMOJI,
    DashboardSummary,
    Notification,
    NotificationType,
    ProductionOrder,
    ProductionPhase,
    SalesOrder,
    Schedule,
    ScheduleEntry,
)

ORDERS_PER_PAGE = 5
MAX_MESSAGE_LEN = 4096


_DEFAULT_PRI_EMOJI = "\u26aa"
_DEFAULT_STATUS_EMOJI = "\u2753"


def _pri(p: int) -> str:
    emoji = PRIORITY_EMOJI.get(p, _DEFAULT_PRI_EMOJI)
    return f"{emoji} P{p}"


def _date(dt: datetime) -> str:
    return dt.strftime("%b %d")


def _datetime(dt: datetime) -> str:
    return dt.strftime("%b %d %H:%M")


def _status(s: str) -> str:
    emoji = STATUS_EMOJI.get(s, _DEFAULT_STATUS_EMOJI)
    label = s.replace("_", " ").title()
    return f"{emoji} {label}"


# ------------------------------------------------------------------
# Welcome / help / settings
# ------------------------------------------------------------------

WELCOME_TEXT = (
    "\U0001f3ed <b>NovaBoard Operations Bot</b>\n\n"
    "Welcome! I'll help you manage production scheduling "
    "and monitor your manufacturing line.\n\n"
    "To get started, please enter your <b>API base URL</b>:\n"
    "<i>Example: https://hackathon3.arke.so</i>"
)

HELP_TEXT = (
    "\U0001f4d6 <b>Help — NovaBoard Operations Bot</b>\n\n"
    "<b>Commands</b>\n"
    "/start  — Set up API connection\n"
    "/menu   — Main navigation menu\n"
    "/help   — This help message\n"
    "/cancel — Cancel current input\n\n"
    "<b>What you can do</b>\n"
    "\u2022 View and manage sales orders (priority, qty, notes, delete)\n"
    "\u2022 Monitor production orders and phase progress\n"
    "\u2022 View, request, and approve production schedules\n"
    "\u2022 Receive real-time production alerts\n\n"
    "<b>Navigation</b>\n"
    "Use the inline buttons below messages to navigate. "
    "Text input is only requested when editing values or adding comments."
)


def format_connected(url: str) -> str:
    return (
        f"\u2705 Connected to <code>{url}</code>\n\n"
        "You're all set! Here's your control panel:"
    )


def format_settings(
    url: str,
    sim_now: datetime | None = None,
    sim_rate: float = 1.0,
) -> str:
    lines = [
        "\u2699\ufe0f <b>Settings</b>\n",
        f"<b>API Base URL:</b>\n<code>{url}</code>\n",
        "\U0001f552 <b>Simulation Clock</b>",
    ]
    if sim_now:
        lines.append(f"   Current time: <code>{sim_now.strftime('%Y-%m-%d %H:%M:%S')} UTC</code>")
    else:
        lines.append("   Current time: <i>real UTC</i>")
    rate_label = "real-time" if sim_rate == 1.0 else f"{sim_rate}x"
    lines.append(f"   Time rate: <code>{rate_label}</code>")
    return "\n".join(lines)


# ------------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------------

def format_dashboard(s: DashboardSummary) -> str:
    lines = [
        "\U0001f4ca <b>Operations Dashboard</b>",
        "\u2501" * 24,
        "",
        f"\U0001f4cb <b>Sales Orders:</b> {s.total_sales_orders}",
    ]

    pri_parts = []
    for p in sorted(s.orders_by_priority):
        emoji = PRIORITY_EMOJI.get(p, "")
        count = s.orders_by_priority[p]
        pri_parts.append(f"{emoji} P{p}: {count}")
    if pri_parts:
        lines.append("   " + "  ".join(pri_parts))

    lines.append("")
    lines.append(f"\U0001f3ed <b>Production Orders:</b> {s.total_production_orders}")
    status_parts = []
    for k, v in s.production_by_status.items():
        if v:
            emoji = STATUS_EMOJI.get(k, "")
            label = k.replace("_", " ").title()
            status_parts.append(f"{emoji} {label}: {v}")
    if status_parts:
        lines.append("   " + " | ".join(status_parts))

    if s.current_schedule_status:
        lines.append("")
        lines.append(f"\U0001f4c5 <b>Schedule:</b> {s.current_schedule_status}")

    if s.upcoming_deadlines:
        lines.append("")
        lines.append("\u23f0 <b>Next Deadlines:</b>")
        for so in s.upcoming_deadlines[:5]:
            lines.append(
                f"   {_date(so.deadline)} \u2014 {so.internal_id} "
                f"({so.line.product_internal_id} \u00d7{so.line.quantity}, "
                f"{so.customer.name})"
            )

    if s.active_alerts:
        lines.append("")
        lines.append(f"\u26a0\ufe0f <b>Alerts:</b> {len(s.active_alerts)}")
        for alert in s.active_alerts[:5]:
            lines.append(f"   \u26a1 {alert}")

    return "\n".join(lines)


# ------------------------------------------------------------------
# Sales Orders
# ------------------------------------------------------------------

_SO_PROD_STATUS_TAG = {
    "completed": " \u2705",
    "in_progress": " \u25b6\ufe0f",
    "scheduled": " \U0001f3ed",
}

_SO_PROD_STATUS_LABEL = {
    "completed": "\u2705 <i>Completed</i>",
    "in_progress": "\u25b6\ufe0f <i>In progress</i>",
    "scheduled": "\U0001f3ed <i>Scheduled for production</i>",
}


def _so_production_line(
    so_id: str,
    so_status: dict[str, str],
    now: datetime | None,
    deadline: datetime | None,
) -> str | None:
    """Return a status line for the SO, or None."""
    prod = so_status.get(so_id)
    if prod:
        return f"     {_SO_PROD_STATUS_LABEL[prod]}"
    if now and deadline and deadline <= now:
        return "     \u274c <i>Deadline missed</i>"
    return None


def format_sales_order_list(
    orders: Sequence[SalesOrder],
    page: int,
    so_status: dict[str, str] | None = None,
    now: datetime | None = None,
) -> str:
    total = len(orders)
    total_pages = max(1, math.ceil(total / ORDERS_PER_PAGE))
    start = page * ORDERS_PER_PAGE
    page_orders = orders[start : start + ORDERS_PER_PAGE]
    status = so_status or {}

    n_completed = sum(1 for o in orders if status.get(o.id) == "completed")
    n_progress = sum(1 for o in orders if status.get(o.id) == "in_progress")
    n_scheduled = sum(1 for o in orders if status.get(o.id) == "scheduled")
    n_missed = sum(
        1 for o in orders
        if o.id not in status and now and o.deadline and o.deadline <= now
    )

    lines = [f"\U0001f4cb <b>Sales Orders</b> \u2014 {total} total"]
    summary_parts: list[str] = []
    if n_completed:
        summary_parts.append(f"\u2705 {n_completed} completed")
    if n_progress:
        summary_parts.append(f"\u25b6\ufe0f {n_progress} in progress")
    if n_scheduled:
        summary_parts.append(f"\U0001f3ed {n_scheduled} scheduled")
    if n_missed:
        summary_parts.append(f"\u274c {n_missed} missed")
    if summary_parts:
        lines.append(" | ".join(summary_parts))
    lines.append(f"Page {page + 1}/{total_pages}\n")

    for so in page_orders:
        tag = _SO_PROD_STATUS_TAG.get(status.get(so.id, ""), "")
        lines.append(
            f"{_pri(so.priority)} <b>{so.internal_id}</b>{tag} | {so.customer.name}"
        )
        lines.append(
            f"     {so.line.product_internal_id} \u00d7 {so.line.quantity}"
            f" | \u23f0 {_date(so.deadline)}"
        )
        prod_line = _so_production_line(so.id, status, now, so.deadline)
        if prod_line:
            lines.append(prod_line)
        if so.notes:
            short = so.notes if len(so.notes) <= 60 else so.notes[:57] + "..."
            lines.append(f"     \U0001f4dd <i>{short}</i>")
        lines.append("")

    return "\n".join(lines)


def format_sales_order_detail(
    so: SalesOrder,
    production_status: str | None = None,
    now: datetime | None = None,
) -> str:
    lines = [
        "\U0001f4cb <b>Sales Order Detail</b>",
        "\u2501" * 24,
        "",
        f"\U0001f4c4 <b>{so.internal_id}</b>",
        f"\U0001f464 {so.customer.name}",
        f"\U0001f4e6 {so.line.product_internal_id} ({so.line.product_name}) "
        f"\u00d7 {so.line.quantity}",
        f"\u23f0 Deadline: <b>{_date(so.deadline)}</b>",
        f"{_pri(so.priority)} \u2014 {PRIORITY_LABEL.get(so.priority, 'Unknown')}",
        f"\U0001f4ca Status: {_status(so.status)}",
    ]
    if production_status == "completed":
        lines.append("\n\u2705 <b>Production completed</b>")
    elif production_status == "in_progress":
        lines.append("\n\u25b6\ufe0f <b>Production in progress</b>")
    elif production_status == "scheduled":
        lines.append("\n\U0001f3ed <b>Scheduled for production</b>")
    elif not production_status and now and so.deadline and so.deadline <= now:
        lines.append("\n\u274c <b>Deadline missed \u2014 not scheduled</b>")
    if so.notes:
        lines.append(f"\n\U0001f4dd <b>Notes:</b>\n<i>{so.notes}</i>")
    return "\n".join(lines)


# ------------------------------------------------------------------
# Production Orders
# ------------------------------------------------------------------

def format_production_order_list(
    orders: Sequence[ProductionOrder], page: int
) -> str:
    total = len(orders)
    total_pages = max(1, math.ceil(total / ORDERS_PER_PAGE))
    start = page * ORDERS_PER_PAGE
    page_orders = orders[start : start + ORDERS_PER_PAGE]

    lines = [
        f"\U0001f3ed <b>Production Orders</b> \u2014 {total} total",
        f"Page {page + 1}/{total_pages}\n",
    ]

    for po in page_orders:
        lines.append(
            f"{_status(po.status)} <b>{po.internal_id}</b>"
        )
        lines.append(
            f"     {po.product_name} \u00d7 {po.quantity}"
            f" | \U0001f4c5 {_date(po.starts_at)} \u2192 {_date(po.ends_at)}"
        )
        lines.append("")

    return "\n".join(lines)


def _execution_state(starts_at: datetime, ends_at: datetime, now: datetime) -> str:
    if now < starts_at:
        return "\u23f3 Pending"
    if now >= ends_at:
        return "\u2705 Completed"
    return "\u25b6\ufe0f In Progress"


def format_production_order_detail(
    po: ProductionOrder, now: datetime | None = None,
) -> str:
    lines = [
        "\U0001f3ed <b>Production Order</b>",
        "\u2501" * 24,
        "",
        f"\U0001f4c4 <b>{po.internal_id}</b>",
        f"\U0001f4e6 {po.product_name} \u00d7 {po.quantity}",
        f"\U0001f4c5 {_datetime(po.starts_at)} \u2192 {_datetime(po.ends_at)}",
        f"\U0001f4ca Status: {_status(po.status)}",
    ]
    if now:
        exec_state = _execution_state(po.starts_at, po.ends_at, now)
        lines.append(f"\U0001f680 Execution: <b>{exec_state}</b>")
        if po.starts_at <= now < po.ends_at:
            total = (po.ends_at - po.starts_at).total_seconds()
            elapsed = (now - po.starts_at).total_seconds()
            pct = min(100.0, elapsed / total * 100) if total > 0 else 0
            filled = round(pct / 5)
            bar = "\u2588" * filled + "\u2591" * (20 - filled)
            lines.append(f"   <code>[{bar}] {pct:.0f}%</code>")
    if po.phases:
        lines.append("")
        lines.append("\U0001f4d0 <b>Phases:</b>")
        for ph in po.phases:
            lines.append(_format_phase_line(ph, now=now))

    lines.append("")
    lines.append(
        '\U0001f4f9 <a href="https://olene-expository-uncrookedly.ngrok-free.dev/index.html">'
        "Live Factory Footage</a>"
    )
    return "\n".join(lines)


def _format_phase_line(ph: ProductionPhase, now: datetime | None = None) -> str:
    if now and ph.starts_at and ph.ends_at:
        state = _execution_state(ph.starts_at, ph.ends_at, now)
        icon = {
            "\u23f3 Pending": "\u23f3",
            "\u2705 Completed": "\u2705",
            "\u25b6\ufe0f In Progress": "\u25b6\ufe0f",
        }.get(state, "\u2753")
    else:
        icon = PHASE_STATUS_EMOJI.get(ph.status, "\u2753")
    time_str = ""
    if ph.starts_at and ph.ends_at:
        time_str = f" | {_datetime(ph.starts_at)} \u2192 {_datetime(ph.ends_at)}"
    dur = f" | {ph.duration_minutes} min" if ph.duration_minutes else ""
    return f"  {icon} {ph.name:<10}{dur}{time_str}"


# ------------------------------------------------------------------
# Schedule
# ------------------------------------------------------------------

def format_schedule(sched: Schedule) -> str:
    status_icon = {
        "proposed": "\U0001f7e1",
        "accepted": "\u2705",
        "rejected": "\u274c",
    }.get(sched.status, "\u2753")

    gen_str = _datetime(sched.generated_at) if sched.generated_at else "N/A"
    on_time_str = "\u2705 All on time" if sched.all_on_time else f"\u274c {sched.late_count} late"

    n_existing = sum(1 for e in sched.entries if e.is_existing)
    n_new = len(sched.entries) - n_existing
    count_parts = []
    if n_existing:
        count_parts.append(f"\U0001f3ed {n_existing} in production")
    if n_new:
        count_parts.append(f"\U0001f195 {n_new} newly scheduled")

    lines = [
        "\U0001f4c5 <b>Production Schedule</b>",
        "\u2501" * 24,
        f"{status_icon} {sched.status.title()} | Generated: {gen_str}",
        f"{len(sched.entries)} orders | {on_time_str}",
    ]
    if count_parts:
        lines.append(" | ".join(count_parts))
    lines.append("")

    for i, entry in enumerate(sched.entries):
        lines.append(_format_schedule_entry_compact(entry, i + 1))

    if sched.conflicts:
        lines.append("")
        lines.append("\u26a0\ufe0f <b>Conflicts:</b>")
        for c in sched.conflicts:
            lines.append(f"  \u2022 {c}")

    if sched.notes:
        lines.append(f"\n\U0001f4dd <i>{sched.notes}</i>")

    return "\n".join(lines)


def _format_schedule_entry_compact(entry: ScheduleEntry, index: int) -> str:
    so = entry.sales_order
    if entry.on_time:
        slack = f"+{entry.slack_hours:.1f}h"
    else:
        late_h = abs(entry.slack_hours)
        slack = f"LATE {late_h:.1f}h"
    tick = "\u2705" if entry.on_time else "\u274c"
    tag = " \U0001f3ed" if entry.is_existing else " \U0001f195"
    note = ""
    if entry.conflict_note:
        note = f"\n     \u26a0\ufe0f <i>{entry.conflict_note}</i>"

    return (
        f"<b>{index:02d}</b> {so.internal_id}{tag} | "
        f"{so.line.product_internal_id} \u00d7{so.line.quantity} | "
        f"{so.customer.name}\n"
        f"     \U0001f4c5 {_date(entry.planned_start)} \u2192 {_date(entry.planned_end)}"
        f" | \u23f0 {_date(entry.deadline)} {tick} {slack}"
        f"{note}\n"
    )


def format_delay_email_html(
    customer_name: str,
    delayed_entries: list[ScheduleEntry],
    on_time_entries: list[ScheduleEntry],
) -> str:
    """Build an HTML email body for a customer whose orders are delayed."""
    lines = [
        "<html><body style='font-family: Arial, sans-serif; color: #333;'>",
        "<h2 style='color: #1a237e;'>NovaBoard Manufacturing</h2>",
        "<hr>",
        f"<p>Dear <b>{customer_name}</b>,</p>",
        "<p>We sincerely apologize for the inconvenience, but we must inform you "
        "that the following order(s) will not meet the originally agreed delivery deadline:</p>",
        "<table style='border-collapse: collapse; width: 100%;'>",
        "<tr style='background: #e8eaf6;'>"
        "<th style='padding: 8px; border: 1px solid #ccc; text-align: left;'>Order</th>"
        "<th style='padding: 8px; border: 1px solid #ccc; text-align: left;'>Product</th>"
        "<th style='padding: 8px; border: 1px solid #ccc; text-align: right;'>Qty</th>"
        "<th style='padding: 8px; border: 1px solid #ccc; text-align: left;'>Deadline</th>"
        "<th style='padding: 8px; border: 1px solid #ccc; text-align: left;'>Est. Completion</th>"
        "<th style='padding: 8px; border: 1px solid #ccc; text-align: right;'>Delay</th>"
        "</tr>",
    ]
    for e in delayed_entries:
        delay_h = abs(e.slack_hours)
        delay_str = f"{delay_h:.0f}h" if delay_h < 24 else f"{delay_h / 24:.1f} days"
        lines.append(
            f"<tr>"
            f"<td style='padding: 8px; border: 1px solid #ccc;'>{e.sales_order.internal_id}</td>"
            f"<td style='padding: 8px; border: 1px solid #ccc;'>"
            f"{e.sales_order.line.product_internal_id} ({e.sales_order.line.product_name})</td>"
            f"<td style='padding: 8px; border: 1px solid #ccc; text-align: right;'>"
            f"{e.sales_order.line.quantity}</td>"
            f"<td style='padding: 8px; border: 1px solid #ccc;'>"
            f"{e.deadline.strftime('%b %d, %Y')}</td>"
            f"<td style='padding: 8px; border: 1px solid #ccc;'>"
            f"{e.planned_end.strftime('%b %d, %Y')}</td>"
            f"<td style='padding: 8px; border: 1px solid #ccc; text-align: right; "
            f"color: #c62828; font-weight: bold;'>{delay_str}</td>"
            f"</tr>"
        )
    lines.append("</table>")

    if on_time_entries:
        lines.append(
            "<p>We would like to reassure you that the following order(s) "
            "remain on track and will be delivered on time:</p>"
        )
        lines.append(
            "<ul style='color: #2e7d32;'>"
        )
        for e in on_time_entries:
            lines.append(
                f"<li><b>{e.sales_order.internal_id}</b> — "
                f"{e.sales_order.line.product_internal_id} x{e.sales_order.line.quantity} "
                f"(deadline: {e.deadline.strftime('%b %d, %Y')}) — on schedule</li>"
            )
        lines.append("</ul>")

    lines.extend([
        "<p>We understand this may impact your plans and we are doing everything possible "
        "to expedite production. Our scheduling team is actively working to minimize the delay.</p>",
        "<p>Please do not hesitate to reach out if you have any questions or need further assistance.</p>",
        "<p>With sincere apologies,<br>"
        "<b>NovaBoard Manufacturing — Operations Team</b></p>",
        "</body></html>",
    ])
    return "\n".join(lines)


def format_delay_telegram_summary(
    customer_name: str,
    email: str,
    delayed_entries: list[ScheduleEntry],
    on_time_entries: list[ScheduleEntry],
) -> str:
    """Build a Telegram message summarising what was sent to one customer."""
    lines = [
        f"\U0001f464 <b>{customer_name}</b>  \u2192  <code>{email}</code>",
    ]
    for e in delayed_entries:
        delay_h = abs(e.slack_hours)
        delay_str = f"{delay_h:.0f}h" if delay_h < 24 else f"{delay_h / 24:.1f} days"
        lines.append(
            f"   \u274c {e.sales_order.internal_id} — "
            f"{e.sales_order.line.product_internal_id} x{e.sales_order.line.quantity} "
            f"| late by <b>{delay_str}</b>"
        )
    for e in on_time_entries:
        lines.append(
            f"   \u2705 {e.sales_order.internal_id} — "
            f"{e.sales_order.line.product_internal_id} x{e.sales_order.line.quantity} "
            f"| on time"
        )
    return "\n".join(lines)


def format_schedule_entry_detail(entry: ScheduleEntry, index: int) -> str:
    so = entry.sales_order
    po = entry.production_order
    slack = f"+{entry.slack_hours:.1f}h" if entry.on_time else f"LATE {abs(entry.slack_hours):.1f}h"
    tick = "\u2705" if entry.on_time else "\u274c"

    lines = [
        f"\U0001f4c5 <b>Schedule Entry #{index}</b>",
        "\u2501" * 24,
        "",
        f"{so.internal_id} \u2192 {po.internal_id}",
        f"\U0001f464 {so.customer.name}",
        f"\U0001f4e6 {so.line.product_internal_id} ({so.line.product_name}) "
        f"\u00d7 {so.line.quantity}",
        f"\U0001f4c5 {_datetime(entry.planned_start)} \u2192 {_datetime(entry.planned_end)}",
        f"\u23f0 Deadline: {_date(entry.deadline)} | {tick} {slack} slack",
    ]
    if entry.conflict_note:
        lines.append(f"\n\u26a0\ufe0f <i>{entry.conflict_note}</i>")

    if po.phases:
        lines.append("")
        lines.append("\U0001f4d0 <b>Phases:</b>")
        for ph in po.phases:
            lines.append(_format_phase_line(ph))

    return "\n".join(lines)


# ------------------------------------------------------------------
# Notifications
# ------------------------------------------------------------------

_NOTIF_ICON: dict[NotificationType, str] = {
    NotificationType.PHASE_COMPLETED: "\u2705",
    NotificationType.ORDER_COMPLETED: "\U0001f389",
    NotificationType.PRODUCT_FAILED: "\u274c",
    NotificationType.DEADLINE_AT_RISK: "\u26a0\ufe0f",
    NotificationType.SCHEDULE_PROPOSED: "\U0001f4c5",
    NotificationType.PRIORITY_CHANGED: "\U0001f504",
    NotificationType.FACTORY_FAILURE: "\U0001f6a8",
}

_NOTIF_CATEGORY: dict[NotificationType, str] = {
    NotificationType.PHASE_COMPLETED: "Production Update",
    NotificationType.ORDER_COMPLETED: "Production Complete",
    NotificationType.PRODUCT_FAILED: "Quality Alert",
    NotificationType.DEADLINE_AT_RISK: "Deadline Warning",
    NotificationType.SCHEDULE_PROPOSED: "Schedule Update",
    NotificationType.PRIORITY_CHANGED: "Priority Change",
    NotificationType.FACTORY_FAILURE: "Factory Failure",
}


def format_factory_failure_caption(
    po_name: str,
    product_name: str,
    quantity: int,
    so_name: str | None = None,
    customer: str | None = None,
    description: str = "",
) -> str:
    """Build a short caption for the factory failure photo (max 1024 chars)."""
    lines = [
        "\U0001f6a8 <b>Factory Failure Detected</b>",
        "\u2501" * 24,
        "",
        f"\U0001f3ed Production Order: <b>{po_name}</b>",
        f"\U0001f4e6 {product_name} \u00d7 {quantity}",
    ]
    if so_name:
        lines.append(f"\U0001f4cb Sales Order: <b>{so_name}</b>")
    if customer:
        lines.append(f"\U0001f464 Customer: {customer}")
    if description:
        lines.append(f"\n\U0001f4dd {description}")
    lines.append(
        "\n\u26a0\ufe0f <b>Choose an action:</b>\n"
        "\u2022 <b>Cancel</b> \u2014 remove this order entirely\n"
        "\u2022 <b>Restart</b> \u2014 re-execute from the beginning"
    )
    return "\n".join(lines)


def format_notification(n: Notification) -> str:
    icon = _NOTIF_ICON.get(n.type, "\U0001f514")
    category = _NOTIF_CATEGORY.get(n.type, "Notification")
    lines = [
        f"{icon} <b>{category}</b>",
        "\u2501" * 24,
        "",
        f"<b>{n.title}</b>",
        "",
        n.message,
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------
# Utility
# ------------------------------------------------------------------

def split_message(text: str) -> list[str]:
    """Split text into chunks that respect Telegram's 4096 char limit."""
    if len(text) <= MAX_MESSAGE_LEN:
        return [text]
    parts: list[str] = []
    while text:
        if len(text) <= MAX_MESSAGE_LEN:
            parts.append(text)
            break
        cut = text.rfind("\n", 0, MAX_MESSAGE_LEN)
        if cut == -1:
            cut = MAX_MESSAGE_LEN
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return parts
