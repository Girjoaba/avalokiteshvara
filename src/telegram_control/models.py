"""Domain types (re-exported from src.shared.models) + Telegram display constants."""

from __future__ import annotations

# Re-export every domain type so existing `from .models import X` still works
from src.shared.models import (  # noqa: F401
    Customer,
    DashboardSummary,
    Notification,
    NotificationType,
    Product,
    ProductionOrder,
    ProductionPhase,
    SalesOrder,
    SalesOrderLine,
    Schedule,
    ScheduleEntry,
    ScheduleResult,
)

# ---------------------------------------------------------------------------
# Telegram-specific display constants (emoji / label maps)
# ---------------------------------------------------------------------------

PRIORITY_EMOJI: dict[int, str] = {1: "\U0001f534", 2: "\U0001f7e0", 3: "\U0001f535", 4: "\u26aa"}
PRIORITY_LABEL: dict[int, str] = {1: "Critical", 2: "High", 3: "Normal", 4: "Low"}

STATUS_EMOJI: dict[str, str] = {
    "accepted": "\U0001f4cb",
    "scheduled": "\U0001f4c5",
    "in_progress": "\u2699\ufe0f",
    "completed": "\u2705",
    "cancelled": "\u274c",
    "planned": "\U0001f4cb",
    "confirmed": "\U0001f4c5",
}

PHASE_STATUS_EMOJI: dict[str, str] = {
    "not_ready": "\u2b1c",
    "ready": "\U0001f7e1",
    "started": "\U0001f535",
    "completed": "\u2705",
}
