"""Scheduling policies operating on SalesOrder dataclasses."""

from __future__ import annotations

from src.shared.models import SalesOrder


def sort_orders_edf(orders: list[SalesOrder]) -> list[SalesOrder]:
    """Earliest Deadline First — ties broken by priority (lower = more urgent)."""
    return sorted(orders, key=lambda o: (o.deadline, o.priority))
