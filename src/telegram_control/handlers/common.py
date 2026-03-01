"""Shared handler utilities: client access, error helpers, guard clauses."""

from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING

from telegram import Update
from telegram.ext import ContextTypes

if TYPE_CHECKING:
    from ..api_client import ArkeAPIClient

logger = logging.getLogger(__name__)

NOT_IMPLEMENTED_MSG = (
    "\U0001f6a7 <b>Not Connected</b>\n\n"
    "This action requires an API endpoint that hasn't been "
    "implemented yet.\n"
    "Fill in the corresponding stub in <code>api_client.py</code>."
)


def get_client(context: ContextTypes.DEFAULT_TYPE) -> ArkeAPIClient | None:
    return context.user_data.get("api_client")  # type: ignore[return-value]


async def ensure_configured(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> ArkeAPIClient | None:
    """Return the API client or send a setup prompt and return ``None``."""
    client = get_client(context)
    if client is not None:
        return client

    text = "\u26a0\ufe0f <b>Not connected</b>\n\nPlease run /start to set your API URL first."
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, parse_mode="HTML")
        except Exception:
            try:
                await update.callback_query.answer(
                    "Not connected. Run /start first.", show_alert=True,
                )
            except Exception:
                pass
    elif update.message:
        await update.message.reply_text(text, parse_mode="HTML")
    return None


async def handle_api_error(update: Update, error: Exception) -> None:
    """Send a user-friendly error message for API failures."""
    if isinstance(error, NotImplementedError):
        text = NOT_IMPLEMENTED_MSG
    else:
        logger.exception("API error: %s", error)
        text = f"\u274c <b>Error</b>\n<code>{html.escape(str(error))}</code>"

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(text, parse_mode="HTML")
        except Exception:
            await update.callback_query.answer(str(error)[:200], show_alert=True)
    elif update.message:
        await update.message.reply_text(text, parse_mode="HTML")


async def answer_callback(update: Update) -> None:
    """Acknowledge a callback query (removes loading spinner)."""
    if update.callback_query:
        await update.callback_query.answer()


def clear_awaiting(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset any pending text-input state."""
    context.user_data.pop("awaiting_input", None)
    context.user_data.pop("awaiting_context", None)
