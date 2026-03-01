"""Telegram bot application builder and runner.

Run with::

    python -m src.telegram_control
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from telegram.ext import Application, PicklePersistence

from .handlers import register_handlers
from .notifications import NotificationDispatcher

logger = logging.getLogger(__name__)


def create_bot(token: str | None = None) -> Application:
    """Build and return a configured ``Application`` (not yet running).

    Args:
        token: Telegram bot token.  Falls back to the ``TELEGRAM_API_KEY``
               environment variable.
    """
    load_dotenv()
    token = token or os.environ.get("TELEGRAM_API_KEY")
    if not token:
        raise RuntimeError(
            "Telegram token not found. Set TELEGRAM_API_KEY in .env "
            "or pass it to create_bot()."
        )

    persistence = PicklePersistence(filepath="bot_data.pickle")

    app = (
        Application.builder()
        .token(token)
        .persistence(persistence)
        .build()
    )

    register_handlers(app)

    dispatcher = NotificationDispatcher(app.bot)
    app.bot_data["notification_dispatcher"] = dispatcher

    return app


def run_bot(token: str | None = None) -> None:
    """Create the bot and start polling (blocking)."""
    logging.basicConfig(
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        level=logging.INFO,
    )
    logger.info("Starting NovaBoard Operations Bot...")
    app = create_bot(token)
    app.run_polling()
