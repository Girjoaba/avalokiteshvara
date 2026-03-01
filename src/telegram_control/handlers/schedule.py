"""Schedule viewing, requesting, accepting, rejecting, and commenting."""

from __future__ import annotations

from io import BytesIO

from telegram import Update
from telegram.ext import ContextTypes

from ..formatters import format_schedule, format_schedule_entry_detail
from ..keyboards import (
    main_menu_keyboard,
    schedule_comment_cancel_keyboard,
    schedule_entry_keyboard,
    schedule_view_keyboard,
)
from .common import answer_callback, clear_awaiting, ensure_configured, handle_api_error


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
