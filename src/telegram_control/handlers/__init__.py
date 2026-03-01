"""Handler registration and text-input routing."""

from __future__ import annotations

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import menu, onboarding, production, sales_orders, schedule


def register_handlers(app: Application) -> None:
    """Wire every command, callback, and text handler into *app*."""

    # ---- Commands ----
    app.add_handler(CommandHandler("start", onboarding.cmd_start))
    app.add_handler(CommandHandler("menu", menu.cmd_menu))
    app.add_handler(CommandHandler("dashboard", menu.cmd_dashboard))
    app.add_handler(CommandHandler("orders", sales_orders.cmd_orders))
    app.add_handler(CommandHandler("production", production.cmd_production))
    app.add_handler(CommandHandler("schedule", schedule.cmd_schedule))
    app.add_handler(CommandHandler("help", onboarding.cmd_help))
    app.add_handler(CommandHandler("cancel", onboarding.cmd_cancel))

    # ---- Menu / navigation ----
    app.add_handler(CallbackQueryHandler(menu.cb_menu, pattern=r"^menu$"))
    app.add_handler(CallbackQueryHandler(menu.cb_menu, pattern=r"^back:menu$"))
    app.add_handler(CallbackQueryHandler(menu.cb_dashboard, pattern=r"^dash$"))
    app.add_handler(CallbackQueryHandler(onboarding.cb_settings, pattern=r"^settings$"))
    app.add_handler(CallbackQueryHandler(onboarding.cb_change_url, pattern=r"^change_url$"))
    app.add_handler(CallbackQueryHandler(onboarding.cb_set_time, pattern=r"^set_time$"))
    app.add_handler(CallbackQueryHandler(onboarding.cb_set_rate, pattern=r"^set_rate$"))
    app.add_handler(CallbackQueryHandler(onboarding.cb_reset_clock, pattern=r"^reset_clock$"))
    app.add_handler(CallbackQueryHandler(onboarding.cb_cancel, pattern=r"^cancel$"))

    # ---- Sales orders ----
    app.add_handler(CallbackQueryHandler(sales_orders.cb_list, pattern=r"^so:list:"))
    app.add_handler(CallbackQueryHandler(sales_orders.cb_list, pattern=r"^back:so$"))
    app.add_handler(CallbackQueryHandler(sales_orders.cb_detail, pattern=r"^so:d:"))
    app.add_handler(CallbackQueryHandler(sales_orders.cb_edit_priority, pattern=r"^so:ep:"))
    app.add_handler(CallbackQueryHandler(sales_orders.cb_set_priority, pattern=r"^so:sp:"))
    app.add_handler(CallbackQueryHandler(sales_orders.cb_edit_quantity, pattern=r"^so:eq:"))
    app.add_handler(CallbackQueryHandler(sales_orders.cb_edit_notes, pattern=r"^so:en:"))
    app.add_handler(CallbackQueryHandler(sales_orders.cb_delete, pattern=r"^so:del:"))
    app.add_handler(CallbackQueryHandler(sales_orders.cb_confirm_delete, pattern=r"^so:cd:"))

    # ---- Production orders ----
    app.add_handler(CallbackQueryHandler(production.cb_list, pattern=r"^po:list:"))
    app.add_handler(CallbackQueryHandler(production.cb_list, pattern=r"^back:po$"))
    app.add_handler(CallbackQueryHandler(production.cb_detail, pattern=r"^po:d:"))
    app.add_handler(CallbackQueryHandler(production.cb_remove, pattern=r"^po:del:"))

    # ---- Schedule ----
    app.add_handler(CallbackQueryHandler(schedule.cb_view, pattern=r"^sc:view$"))
    app.add_handler(CallbackQueryHandler(schedule.cb_view, pattern=r"^back:sc$"))
    app.add_handler(CallbackQueryHandler(schedule.cb_request, pattern=r"^sc:req$"))
    app.add_handler(CallbackQueryHandler(schedule.cb_accept, pattern=r"^sc:acc$"))
    app.add_handler(CallbackQueryHandler(schedule.cb_reject, pattern=r"^sc:rej$"))
    app.add_handler(CallbackQueryHandler(schedule.cb_comment, pattern=r"^sc:com$"))
    app.add_handler(CallbackQueryHandler(schedule.cb_entry_detail, pattern=r"^sc:e:"))

    # ---- No-op (pagination label clicks etc.) ----
    app.add_handler(CallbackQueryHandler(_noop_callback, pattern=r"^noop$"))

    # ---- Free-text input (must be last) ----
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, _route_text_input)
    )


async def _route_text_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Dispatch text messages based on ``context.user_data['awaiting_input']``."""
    awaiting = context.user_data.get("awaiting_input")

    if awaiting == "api_url":
        await onboarding.handle_api_url_input(update, context)
    elif awaiting == "set_time":
        await onboarding.handle_set_time_input(update, context)
    elif awaiting == "set_rate":
        await onboarding.handle_set_rate_input(update, context)
    elif awaiting == "quantity":
        await sales_orders.handle_quantity_input(update, context)
    elif awaiting == "notes":
        await sales_orders.handle_notes_input(update, context)
    elif awaiting == "schedule_comment":
        await schedule.handle_comment_input(update, context)
    else:
        await update.message.reply_text(  # type: ignore[union-attr]
            "\U0001f4a1 Use the buttons to navigate, or /menu for options.",
        )


async def _noop_callback(update: Update, _context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.callback_query:
        await update.callback_query.answer()
