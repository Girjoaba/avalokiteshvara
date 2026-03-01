"""Schedule viewing, requesting, accepting, rejecting, and commenting."""

from __future__ import annotations

import logging
import os
import smtplib
from collections import defaultdict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from io import BytesIO

from telegram import Update
from telegram.ext import ContextTypes

from src.scheduler_logic.constants import CLIENT_EMAILS

from ..formatters import (
    format_delay_email_html,
    format_delay_telegram_summary,
    format_schedule,
    format_schedule_entry_detail,
)
from ..keyboards import (
    main_menu_keyboard,
    schedule_comment_cancel_keyboard,
    schedule_entry_keyboard,
    schedule_view_keyboard,
)
from .common import answer_callback, clear_awaiting, ensure_configured, handle_api_error

logger = logging.getLogger(__name__)


def _generate_gantt_for_schedule(schedule, sim_now):
    """Regenerate Gantt bytes from a schedule's entries."""
    from src.scheduler_logic.gantt import generate_gantt_image
    if not schedule or not schedule.entries:
        return None
    return generate_gantt_image(schedule.entries, now=sim_now)


# ------------------------------------------------------------------
# /schedule + callback view
# ------------------------------------------------------------------

async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = await ensure_configured(update, context)
    if not client:
        return
    try:
        sched = await client.get_current_schedule()
    except Exception as exc:
        await handle_api_error(update, exc)
        return

    if sched is None:
        await update.message.reply_text(  # type: ignore[union-attr]
            "\U0001f4c5 <b>No schedule available.</b>\n\n"
            "Use \U0001f504 <b>New Schedule</b> to generate one.",
            parse_mode="HTML",
            reply_markup=schedule_view_keyboard(None),
        )
        return

    context.user_data["_schedule"] = sched
    await update.message.reply_text(  # type: ignore[union-attr]
        format_schedule(sched),
        parse_mode="HTML",
        reply_markup=schedule_view_keyboard(sched),
    )

    gantt = _generate_gantt_for_schedule(sched, client.get_sim_now())
    if gantt:
        await update.message.reply_photo(  # type: ignore[union-attr]
            photo=BytesIO(gantt),
            caption="\U0001f4ca Production Schedule \u2014 Gantt Chart",
        )


async def cb_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    clear_awaiting(context)

    client = await ensure_configured(update, context)
    if not client:
        return

    try:
        sched = await client.get_current_schedule()
    except Exception as exc:
        await handle_api_error(update, exc)
        return

    if sched is None:
        await update.callback_query.edit_message_text(  # type: ignore[union-attr]
            "\U0001f4c5 <b>No schedule available.</b>\n\n"
            "Use \U0001f504 <b>New Schedule</b> to generate one.",
            parse_mode="HTML",
            reply_markup=schedule_view_keyboard(None),
        )
        return

    context.user_data["_schedule"] = sched
    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        format_schedule(sched),
        parse_mode="HTML",
        reply_markup=schedule_view_keyboard(sched),
    )

    gantt = _generate_gantt_for_schedule(sched, client.get_sim_now())
    if gantt:
        await update.callback_query.message.reply_photo(  # type: ignore[union-attr]
            photo=BytesIO(gantt),
            caption="\U0001f4ca Production Schedule \u2014 Gantt Chart",
        )


# ------------------------------------------------------------------
# Request new schedule
# ------------------------------------------------------------------

async def cb_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    clear_awaiting(context)

    client = await ensure_configured(update, context)
    if not client:
        return

    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        "\u23f3 Computing new schedule (EDF)...\n"
        "Creating production orders and assigning phase dates.\n"
        "This may take a moment.",
        parse_mode="HTML",
    )

    try:
        result = await client.request_new_schedule()
    except Exception as exc:
        await handle_api_error(update, exc)
        return

    sched = result.schedule
    context.user_data["_schedule"] = sched

    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        format_schedule(sched),
        parse_mode="HTML",
        reply_markup=schedule_view_keyboard(sched),
    )

    if result.gantt_image:
        await update.callback_query.message.reply_photo(  # type: ignore[union-attr]
            photo=BytesIO(result.gantt_image),
            caption="\U0001f4ca Production Schedule — Gantt Chart",
        )


# ------------------------------------------------------------------
# Accept / Reject
# ------------------------------------------------------------------

async def cb_accept(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    clear_awaiting(context)

    client = await ensure_configured(update, context)
    if not client:
        return

    sched = context.user_data.get("_schedule")
    if not sched:
        await update.callback_query.edit_message_text(  # type: ignore[union-attr]
            "\u26a0\ufe0f No schedule to accept. Request one first.",
            parse_mode="HTML",
            reply_markup=schedule_view_keyboard(None),
        )
        return

    try:
        await client.accept_schedule(sched.id)
    except Exception as exc:
        await handle_api_error(update, exc)
        return

    sched.status = "accepted"
    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        "\u2705 <b>Schedule accepted!</b>\n\n"
        "Production orders have been confirmed and moved to <i>in progress</i>.\n"
        "You'll receive notifications as phases complete.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


async def cb_reject(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    clear_awaiting(context)

    client = await ensure_configured(update, context)
    if not client:
        return

    sched = context.user_data.get("_schedule")
    if not sched:
        await update.callback_query.edit_message_text(  # type: ignore[union-attr]
            "\u26a0\ufe0f No schedule to reject.",
            parse_mode="HTML",
            reply_markup=schedule_view_keyboard(None),
        )
        return

    try:
        await client.reject_schedule(sched.id)
    except Exception as exc:
        await handle_api_error(update, exc)
        return

    sched.status = "rejected"
    context.user_data.pop("_schedule", None)
    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        "\u274c <b>Schedule rejected.</b>\n\n"
        "You can request a new schedule or adjust orders first.",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


# ------------------------------------------------------------------
# Comment & revise
# ------------------------------------------------------------------

async def cb_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)

    context.user_data["awaiting_input"] = "schedule_comment"

    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        "\U0001f4ac <b>Enter your feedback</b>\n\n"
        "Your comments will be forwarded to the scheduling core "
        "along with the current order set. The system will compute "
        "a revised schedule taking your input into account.\n\n"
        "<i>Type your comment below:</i>",
        parse_mode="HTML",
        reply_markup=schedule_comment_cancel_keyboard(),
    )


async def handle_comment_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    comment = update.message.text.strip()  # type: ignore[union-attr]
    clear_awaiting(context)

    client = await ensure_configured(update, context)
    if not client:
        return

    await update.message.reply_text(  # type: ignore[union-attr]
        f"\U0001f4ac <b>Comment received:</b>\n<i>{comment}</i>\n\n"
        "\u23f3 Requesting revised schedule...",
        parse_mode="HTML",
    )

    try:
        result = await client.request_new_schedule(comment=comment)
    except Exception as exc:
        await handle_api_error(update, exc)
        return

    sched = result.schedule
    context.user_data["_schedule"] = sched
    await update.message.reply_text(  # type: ignore[union-attr]
        format_schedule(sched),
        parse_mode="HTML",
        reply_markup=schedule_view_keyboard(sched),
    )

    if result.gantt_image:
        await update.message.reply_photo(  # type: ignore[union-attr]
            photo=BytesIO(result.gantt_image),
            caption="\U0001f4ca Revised Schedule — Gantt Chart",
        )


# ------------------------------------------------------------------
# Send delay messages to clients
# ------------------------------------------------------------------

def _send_email(to: str, subject: str, html_body: str) -> bool:
    """Send an HTML email via SMTP. Returns True on success."""
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASSWORD", "")
    smtp_from = os.environ.get("SMTP_FROM", smtp_user)

    if not smtp_user or not smtp_pass:
        logger.warning("SMTP credentials not configured — skipping real send to %s", to)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = to
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, [to], msg.as_string())
        return True
    except Exception:
        logger.exception("SMTP send failed for %s", to)
        return False


async def cb_delay_emails(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    clear_awaiting(context)

    sched = context.user_data.get("_schedule")
    if not sched or sched.late_count == 0:
        await update.callback_query.edit_message_text(
            "\u2705 <b>All orders are on time!</b>\nNo delay notifications needed.",
            parse_mode="HTML",
            reply_markup=schedule_view_keyboard(sched),
        )
        return

    await update.callback_query.edit_message_text(
        "\u23f3 Sending delay notifications to affected clients...",
        parse_mode="HTML",
    )

    by_customer: dict[str, dict[str, list]] = defaultdict(
        lambda: {"delayed": [], "on_time": []}
    )
    for entry in sched.entries:
        name = entry.sales_order.customer.name
        if entry.on_time:
            by_customer[name]["on_time"].append(entry)
        else:
            by_customer[name]["delayed"].append(entry)

    affected = {
        name: groups
        for name, groups in by_customer.items()
        if groups["delayed"]
    }

    summary_lines = [
        "\U0001f4e7 <b>Delay Notifications Sent</b>",
        "\u2501" * 24,
        "",
    ]
    sent_count = 0
    skipped_count = 0

    for customer_name, groups in affected.items():
        email = CLIENT_EMAILS.get(customer_name)
        delayed = groups["delayed"]
        on_time = groups["on_time"]

        if not email:
            summary_lines.append(
                f"\u26a0\ufe0f <b>{customer_name}</b> — no email on file, skipped"
            )
            skipped_count += 1
            continue

        html_body = format_delay_email_html(customer_name, delayed, on_time)
        subject = (
            f"NovaBoard — Delivery Delay Notice: "
            f"{', '.join(e.sales_order.internal_id for e in delayed)}"
        )

        ok = _send_email(email, subject, html_body)
        status_tag = "\u2709\ufe0f Sent" if ok else "\U0001f4e4 Queued (SMTP not configured)"
        sent_count += 1 if ok else 0

        summary_lines.append(
            format_delay_telegram_summary(customer_name, email, delayed, on_time)
        )
        summary_lines.append(f"   {status_tag}")
        summary_lines.append("")

    not_affected = [
        name for name, groups in by_customer.items()
        if not groups["delayed"]
    ]
    if not_affected:
        summary_lines.append("\u2705 <b>Clients with all orders on time (no email needed):</b>")
        for name in not_affected:
            summary_lines.append(f"   \u2022 {name}")
        summary_lines.append("")

    total = len(affected)
    summary_lines.append(
        f"\U0001f4ca {total} client(s) notified | "
        f"{sent_count} sent | {total - sent_count - skipped_count} queued | "
        f"{skipped_count} skipped"
    )

    await update.callback_query.message.reply_text(
        "\n".join(summary_lines),
        parse_mode="HTML",
        reply_markup=schedule_view_keyboard(sched),
    )


# ------------------------------------------------------------------
# Schedule entry detail (drill-down)
# ------------------------------------------------------------------

async def cb_entry_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    clear_awaiting(context)

    data = update.callback_query.data or ""  # type: ignore[union-attr]
    try:
        index = int(data.split(":")[-1])
    except (ValueError, IndexError):
        index = 0

    sched = context.user_data.get("_schedule")
    if not sched or index >= len(sched.entries):
        await update.callback_query.edit_message_text(  # type: ignore[union-attr]
            "\u26a0\ufe0f Schedule entry not found.",
            parse_mode="HTML",
            reply_markup=schedule_view_keyboard(sched),
        )
        return

    entry = sched.entries[index]
    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        format_schedule_entry_detail(entry, index + 1),
        parse_mode="HTML",
        reply_markup=schedule_entry_keyboard(len(sched.entries), index),
    )
