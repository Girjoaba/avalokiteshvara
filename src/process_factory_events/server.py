"""HTTP server that receives factory failure events and notifies Telegram users.

Run alongside the Telegram bot — see ``bot.py`` for integration.
The factory sends a ``POST /factory/failure`` with a multipart form containing
an ``image`` field (the failure photo) and an optional ``description`` text.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from telegram.ext import Application

logger = logging.getLogger(__name__)


def create_factory_app(telegram_app: Application) -> web.Application:
    """Create an aiohttp web application wired to the Telegram bot."""
    app = web.Application()
    app["telegram_app"] = telegram_app
    app.router.add_post("/factory/failure", _handle_failure)
    return app


async def _find_executing_order(client):
    """Return ``(ProductionOrder, SalesOrder | None)`` for the PO currently
    being executed, or ``(None, None)`` when nothing is running."""
    production_orders = await client.get_production_orders()
    if not production_orders:
        return None, None

    sim_now = client.get_sim_now()

    executing_po = None
    for po in production_orders:
        if po.status in ("in_progress", "confirmed"):
            executing_po = po
            break
    if not executing_po:
        for po in production_orders:
            if po.starts_at <= sim_now < po.ends_at:
                executing_po = po
                break
    if not executing_po:
        executing_po = production_orders[0]

    so_po_map: dict[str, str] = getattr(client, "_so_po_map", {})
    so_id = next(
        (sid for sid, pid in so_po_map.items() if pid == executing_po.id),
        None,
    )

    linked_so = None
    if so_id:
        try:
            linked_so = await client.get_sales_order(so_id)
        except Exception:
            logger.warning("Could not fetch linked SO %s", so_id[:8])

    return executing_po, linked_so


def _resolve_api_client(telegram_app: Application):
    """Find an ArkeAPIClient from bot_data or any user's persisted session."""
    client = telegram_app.bot_data.get("api_client")
    if client:
        return client
    for uid, udata in telegram_app.user_data.items():
        c = udata.get("api_client")
        if c is not None:
            telegram_app.bot_data["api_client"] = c
            return c
    return None


async def _handle_failure(request: web.Request) -> web.Response:
    """``POST /factory/failure`` — receive a failure image and alert Telegram."""
    telegram_app: Application = request.app["telegram_app"]

    client = _resolve_api_client(telegram_app)
    if not client:
        return web.json_response(
            {"error": "No API client configured. Complete bot onboarding first."},
            status=503,
        )

    dispatcher = telegram_app.bot_data.get("notification_dispatcher")
    if not dispatcher:
        return web.json_response(
            {"error": "Notification dispatcher not available."},
            status=503,
        )

    if not dispatcher.subscribers:
        for uid in telegram_app.user_data:
            if isinstance(uid, int):
                dispatcher.subscribe(uid)
        if not dispatcher.subscribers:
            return web.json_response(
                {"error": "No Telegram chats subscribed to notifications."},
                status=503,
            )

    image_data: bytes | None = None
    description = ""

    content_type = request.content_type
    if "multipart" in content_type:
        reader = await request.multipart()
        async for part in reader:
            if part.name == "image":
                image_data = await part.read()
            elif part.name == "description":
                raw = await part.read()
                description = raw.decode("utf-8", errors="replace")
    else:
        image_data = await request.read()

    if not image_data:
        return web.json_response(
            {"error": "No image provided. Send multipart form with 'image' field."},
            status=400,
        )

    executing_po, linked_so = await _find_executing_order(client)
    if not executing_po:
        return web.json_response(
            {"error": "No production order is currently executing."},
            status=404,
        )

    await dispatcher.notify_factory_failure(
        po=executing_po,
        so=linked_so,
        image_data=image_data,
        description=description,
    )

    return web.json_response({
        "status": "notification_sent",
        "production_order_id": executing_po.id,
        "production_order_name": executing_po.internal_id,
        "sales_order": linked_so.internal_id if linked_so else None,
        "subscribers_notified": len(dispatcher.subscribers),
    })
