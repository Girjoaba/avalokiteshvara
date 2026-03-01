"""Main menu and dashboard handlers."""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from ..formatters import format_dashboard
from ..keyboards import back_to_menu_keyboard, main_menu_keyboard
from .common import answer_callback, clear_awaiting, ensure_configured, handle_api_error


MENU_TEXT = (
    "\U0001f3ed <b>NovaBoard Operations</b>\n\n"
    "Select an option below:"
)


# ------------------------------------------------------------------
# Main menu
# ------------------------------------------------------------------

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    clear_awaiting(context)
    await update.message.reply_text(  # type: ignore[union-attr]
        MENU_TEXT,
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


async def cb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    clear_awaiting(context)
    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        MENU_TEXT,
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )


# ------------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------------

async def cmd_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = await ensure_configured(update, context)
    if not client:
        return

    try:
        summary = await client.get_dashboard_summary()
    except Exception as exc:
        await handle_api_error(update, exc)
        return

    await update.message.reply_text(  # type: ignore[union-attr]
        format_dashboard(summary),
        parse_mode="HTML",
        reply_markup=back_to_menu_keyboard(),
    )


async def cb_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await answer_callback(update)
    clear_awaiting(context)

    client = await ensure_configured(update, context)
    if not client:
        return

    try:
        summary = await client.get_dashboard_summary()
    except Exception as exc:
        await handle_api_error(update, exc)
        return

    await update.callback_query.edit_message_text(  # type: ignore[union-attr]
        format_dashboard(summary),
        parse_mode="HTML",
        reply_markup=back_to_menu_keyboard(),
    )
