"""Domain dataclasses shared across telegram_control, scheduler_logic, and ai_assistant."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class NotificationType(Enum):
    PHASE_COMPLETED = "phase_completed"
    ORDER_COMPLETED = "order_completed"
    PRODUCT_FAILED = "product_failed"
    DEADLINE_AT_RISK = "deadline_at_risk"
    SCHEDULE_PROPOSED = "schedule_proposed"
    PRIORITY_CHANGED = "priority_changed"
    FACTORY_FAILURE = "factory_failure"


# ---------------------------------------------------------------------------
# Domain dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Customer:
    id: str
    name: str
    address: str = ""
    country: str = ""


@dataclass
class Product:
    id: str
    internal_id: str
    name: str
    phases: dict[str, int] = field(default_factory=dict)


@dataclass
class SalesOrderLine:
    product_id: str
    product_internal_id: str
    product_name: str
    quantity: int
    uom: str = "pcs"


@dataclass
class SalesOrder:
    id: str
    internal_id: str
    customer: Customer
    line: SalesOrderLine
    deadline: datetime
    priority: int
    status: str
    notes: str = ""
    created_at: Optional[datetime] = None


@dataclass
class ProductionPhase:
    id: str
    name: str
    status: str
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    duration_minutes: int = 0


@dataclass
class ProductionOrder:
    id: str
    internal_id: str
    product_id: str
    product_name: str
    quantity: int
    starts_at: datetime
    ends_at: datetime
    status: str
    product_internal_id: str = ""
    sales_order_id: str = ""
    phases: list[ProductionPhase] = field(default_factory=list)


@dataclass
class ScheduleEntry:
    production_order: ProductionOrder
    sales_order: SalesOrder
    planned_start: datetime
    planned_end: datetime
    deadline: datetime
    on_time: bool
    slack_hours: float = 0.0
    conflict_note: str = ""
    is_existing: bool = False


@dataclass
class Schedule:
    id: str
    entries: list[ScheduleEntry] = field(default_factory=list)
    generated_at: Optional[datetime] = None
    status: str = "proposed"
    conflicts: list[str] = field(default_factory=list)
    notes: str = ""

    @property
    def all_on_time(self) -> bool:
        return all(e.on_time for e in self.entries)

    @property
    def late_count(self) -> int:
        return sum(1 for e in self.entries if not e.on_time)


@dataclass
class DashboardSummary:
    total_sales_orders: int
    orders_by_priority: dict[int, int]
    total_production_orders: int
    production_by_status: dict[str, int]
    upcoming_deadlines: list[SalesOrder]
    active_alerts: list[str]
    current_schedule_status: Optional[str] = None


@dataclass
class Notification:
    type: NotificationType
    title: str
    message: str
    production_order_id: str = ""
    sales_order_id: str = ""
    phase_name: str = ""
    details: dict = field(default_factory=dict)
    timestamp: Optional[datetime] = None


@dataclass
class ScheduleResult:
    """Returned by the scheduler orchestrator to the Telegram layer."""
    schedule: Schedule
    gantt_image: bytes
    text_summary: str


# ---------------------------------------------------------------------------
# AI Replanner structured I/O
# ---------------------------------------------------------------------------

@dataclass
class AIScheduleOrderInput:
    """Single order serialized for the Gemini replanner."""
    sales_order_id: str
    sales_order_internal_id: str
    product_internal_id: str
    qty: int
    priority: int
    deadline: str
    customer: str = ""
    planned_start: str = ""
    planned_end: str = ""
    is_existing: bool = False


@dataclass
class AIScheduleInput:
    """Full structured payload sent to Gemini."""
    sim_now: str
    user_feedback: str
    current_schedule: list[AIScheduleOrderInput] = field(default_factory=list)
    pending_orders: list[AIScheduleOrderInput] = field(default_factory=list)


@dataclass
class AIPriorityUpdate:
    """AI-suggested priority change for a single SO."""
    sales_order_id: str
    new_priority: int
    reason: str = ""


@dataclass
class AIScheduleOutput:
    """Structured response from the Gemini replanner."""
    reordered_so_ids: list[str] = field(default_factory=list)
    priority_updates: list[AIPriorityUpdate] = field(default_factory=list)
    ai_comment: str = ""
    conflicts: list[str] = field(default_factory=list)
