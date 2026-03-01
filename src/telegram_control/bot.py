"""Telegram bot application builder and runner.

Run with::

    python -m src.telegram_control
"""

from __future__ import annotations

import asyncio
import logging
import os

from aiohttp import web
from dotenv import load_dotenv
from telegram.ext import Application, PicklePersistence

from src.process_factory_events import create_factory_app

from .handlers import register_handlers
from .notifications import NotificationDispatcher

logger = logging.getLogger(__name__)

FACTORY_SERVER_HOST = "0.0.0.0"
FACTORY_SERVER_PORT_DEFAULT = 8080


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

    return app


async def _run_all(token: str | None = None) -> None:
    """Start the Telegram bot and the factory HTTP server concurrently."""
    app = create_bot(token)

    port = int(os.environ.get("FACTORY_SERVER_PORT", FACTORY_SERVER_PORT_DEFAULT))
    factory_app = create_factory_app(app)
    runner = web.AppRunner(factory_app)
    await runner.setup()
    site = web.TCPSite(runner, FACTORY_SERVER_HOST, port)

    async with app:
        app.bot_data["notification_dispatcher"] = NotificationDispatcher(app.bot)

        await app.start()
        await app.updater.start_polling()  # type: ignore[union-attr]
        await site.start()
        logger.info(
            "Factory event server listening on http://%s:%d",
            FACTORY_SERVER_HOST, port,
        )

        stop_event = asyncio.Event()
        try:
            await stop_event.wait()
        except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
            pass
        finally:
            logger.info("Shutting down...")
            await app.updater.stop()  # type: ignore[union-attr]
            await app.stop()
            await runner.cleanup()


def run_bot(token: str | None = None) -> None:
    """Create the bot and start polling (blocking)."""
    logging.basicConfig(
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        level=logging.INFO,
    )
    logger.info("Starting NovaBoard Operations Bot + Factory Event Server...")
    asyncio.run(_run_all(token))
