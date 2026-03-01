"""Notification dispatcher — pushes production events to subscribed Telegram chats.

Usage from external code (webhooks, polling loops, etc.)::

    from src.telegram_control.notifications import NotificationDispatcher

    dispatcher = app.bot_data["notification_dispatcher"]
    await dispatcher.notify_phase_completed(
        chat_id=..., po_id="...", po_name="...", phase_name="SMT", next_phase="Reflow",
    )
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from telegram import Bot

from .formatters import format_notification
from .keyboards import notification_action_keyboard
from .models import Notification, NotificationType

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """Sends formatted alert messages to one or more Telegram chats."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot
        self._subscribed_chats: set[int] = set()

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def subscribe(self, chat_id: int) -> None:
        self._subscribed_chats.add(chat_id)

    def unsubscribe(self, chat_id: int) -> None:
        self._subscribed_chats.discard(chat_id)

    @property
    def subscribers(self) -> frozenset[int]:
        return frozenset(self._subscribed_chats)

    # ------------------------------------------------------------------
    # Generic send
    # ------------------------------------------------------------------

    async def send(
        self,
        notification: Notification,
        chat_id: int | None = None,
    ) -> None:
        """Send *notification* to a specific chat or all subscribers."""
        text = format_notification(notification)
        keyboard = notification_action_keyboard(
            production_order_id=notification.production_order_id,
            sales_order_id=notification.sales_order_id,
        )
        targets = {chat_id} if chat_id else self._subscribed_chats
        for cid in targets:
            try:
                await self._bot.send_message(
                    chat_id=cid,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
            except Exception:
                logger.exception("Failed to send notification to chat %s", cid)

    # ------------------------------------------------------------------
    # Convenience methods (call these from your production event hooks)
    # ------------------------------------------------------------------

    async def notify_phase_completed(
        self,
        *,
        chat_id: int | None = None,
        po_id: str,
        po_name: str,
        phase_name: str,
        next_phase: str | None = None,
    ) -> None:
        msg = (
            f"{phase_name} phase for <b>{po_name}</b> has been completed."
        )
        if next_phase:
            msg += f"\n\nNext: <b>{next_phase}</b> (starting automatically)"
        await self.send(
            Notification(
                type=NotificationType.PHASE_COMPLETED,
                title=f"Phase {phase_name} \u2014 Complete",
                message=msg,
                production_order_id=po_id,
                phase_name=phase_name,
                timestamp=datetime.utcnow(),
            ),
            chat_id=chat_id,
        )

    async def notify_order_completed(
        self,
        *,
        chat_id: int | None = None,
        po_id: str,
        po_name: str,
        so_id: str = "",
        customer: str = "",
    ) -> None:
        msg = f"Production order <b>{po_name}</b> is fully completed!"
        if customer:
            msg += f"\nCustomer: {customer}"
        await self.send(
            Notification(
                type=NotificationType.ORDER_COMPLETED,
                title=f"{po_name} \u2014 Completed",
                message=msg,
                production_order_id=po_id,
                sales_order_id=so_id,
                timestamp=datetime.utcnow(),
            ),
            chat_id=chat_id,
        )

    async def notify_product_failed(
        self,
        *,
        chat_id: int | None = None,
        po_id: str,
        po_name: str,
        phase_name: str,
        unit_index: int,
        rescheduled: bool = True,
    ) -> None:
        action = "The unit has been rescheduled for re-processing." if rescheduled else ""
        msg = (
            f"Unit #{unit_index} of <b>{po_name}</b> "
            f"failed at <b>{phase_name}</b> stage.\n{action}"
        )
        await self.send(
            Notification(
                type=NotificationType.PRODUCT_FAILED,
                title=f"Quality Failure \u2014 {po_name}",
                message=msg,
                production_order_id=po_id,
                phase_name=phase_name,
                timestamp=datetime.utcnow(),
            ),
            chat_id=chat_id,
        )

    async def notify_deadline_at_risk(
        self,
        *,
        chat_id: int | None = None,
        so_id: str,
        so_name: str,
        deadline: datetime,
        projected_completion: datetime,
        reason: str = "",
    ) -> None:
        dl = deadline.strftime("%b %d")
        proj = projected_completion.strftime("%b %d")
        msg = (
            f"<b>{so_name}</b> deadline is at risk!\n\n"
            f"Deadline: <b>{dl}</b>\n"
            f"Projected completion: <b>{proj}</b>\n"
        )
        if reason:
            msg += f"\nCause: {reason}"
        await self.send(
            Notification(
                type=NotificationType.DEADLINE_AT_RISK,
                title=f"Deadline Risk \u2014 {so_name}",
                message=msg,
                sales_order_id=so_id,
                timestamp=datetime.utcnow(),
            ),
            chat_id=chat_id,
        )
