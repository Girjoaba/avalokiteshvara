"""Async API client for the Arke manufacturing platform.

Uses ``httpx.AsyncClient`` for non-blocking HTTP.  All responses are
parsed into domain dataclasses from ``models.py``.

Scheduling-core methods (``request_new_schedule``, etc.) are left as
stubs — wire them to your custom optimiser.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .models import (
    Customer,
    DashboardSummary,
    Product,
    ProductionOrder,
    ProductionPhase,
    SalesOrder,
    SalesOrderLine,
    Schedule,
    ScheduleResult,
)

logger = logging.getLogger(__name__)

PHASE_ORDER = ["SMT", "Reflow", "THT", "AOI", "Test", "Coating", "Pack"]
_DT_MIN = datetime.min.replace(tzinfo=timezone.utc)


class ArkeAPIClient:
    """Async facade over the Arke REST API + scheduling core."""

    def __init__(self, base_url: str, username: str = "arke", password: str = "arke") -> None:
        self.base_url: str = base_url.rstrip("/")
        self._username: str = username
        self._password: str = password
        self._token: str | None = None
        self._http: httpx.AsyncClient | None = None
        self._known_po_ids: set[str] = set()
        self._so_po_map: dict[str, str] = {}
        self._current_schedule: Schedule | None = None
        now = datetime.now(timezone.utc)
        self._sim_ref_real: datetime = now
        self._sim_ref_time: datetime = now
        self._sim_rate: float = 1.0

    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        state.pop("_http", None)
        return state

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)
        self._http = None
        self._known_po_ids = state.get("_known_po_ids", set())
        if not hasattr(self, "_username"):
            self._username = "arke"
        if not hasattr(self, "_password"):
            self._password = "arke"
        if not hasattr(self, "_so_po_map"):
            self._so_po_map = {}
        self._current_schedule = None
        now = datetime.now(timezone.utc)
        if not hasattr(self, "_sim_ref_real"):
            self._sim_ref_real = now
        if not hasattr(self, "_sim_ref_time"):
            self._sim_ref_time = now
        if not hasattr(self, "_sim_rate"):
            self._sim_rate = 1.0

    # ==================================================================
    # Simulation clock
    # ==================================================================

    def get_sim_now(self) -> datetime:
        """Return the current simulated UTC time."""
        elapsed_real = (datetime.now(timezone.utc) - self._sim_ref_real).total_seconds()
        elapsed_sim = elapsed_real * self._sim_rate
        return self._sim_ref_time + timedelta(seconds=elapsed_sim)

    def set_sim_time(self, dt: datetime) -> None:
        """Set the simulated clock to *dt*, re-anchoring to real time."""
        self._sim_ref_real = datetime.now(timezone.utc)
        self._sim_ref_time = dt

    def set_sim_rate(self, rate: float) -> None:
        """Change the sim speed multiplier, re-anchoring first."""
        self._sim_ref_time = self.get_sim_now()
        self._sim_ref_real = datetime.now(timezone.utc)
        self._sim_rate = rate

    def reset_sim_clock(self) -> None:
        """Reset simulation clock to real time at 1x speed."""
        now = datetime.now(timezone.utc)
        self._sim_ref_real = now
        self._sim_ref_time = now
        self._sim_rate = 1.0

    async def close(self) -> None:
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    # ==================================================================
    # HTTP plumbing
    # ==================================================================

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=30.0)
        return self._http

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api{path}"

    async def _reauth(self) -> None:
        """Re-authenticate silently using stored credentials."""
        logger.info("Token expired or missing — re-authenticating…")
        await self.authenticate(self._username, self._password)

    async def _get(self, path: str, **params: Any) -> Any:
        c = await self._client()
        r = await c.get(self._url(path), headers=self._headers(),
                        params=params or None)
        if r.status_code == 401:
            await self._reauth()
            r = await c.get(self._url(path), headers=self._headers(),
                            params=params or None)
        r.raise_for_status()
        return r.json()

    async def _post(self, path: str, body: dict | None = None) -> Any:
        c = await self._client()
        r = await c.post(self._url(path), headers=self._headers(), json=body)
        if r.status_code == 401:
            await self._reauth()
            r = await c.post(self._url(path), headers=self._headers(), json=body)
        r.raise_for_status()
        if r.status_code == 204 or not r.content:
            return None
        return r.json()

    async def _put(self, path: str, body: dict) -> Any:
        c = await self._client()
        r = await c.put(self._url(path), headers=self._headers(), json=body)
        if r.status_code == 401:
            await self._reauth()
            r = await c.put(self._url(path), headers=self._headers(), json=body)
        r.raise_for_status()
        return r.json()

    async def _delete(self, path: str) -> None:
        c = await self._client()
        r = await c.delete(self._url(path), headers=self._headers())
        if r.status_code == 401:
            await self._reauth()
            r = await c.delete(self._url(path), headers=self._headers())
        r.raise_for_status()

    # ==================================================================
    # Parsers  (raw JSON dict  →  dataclass)
    # ==================================================================

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_customer(d: dict) -> Customer:
        return Customer(
            id=d.get("id", ""),
            name=d.get("name", "Unknown"),
            address=d.get("address", ""),
            country=d.get("country", ""),
        )

    @staticmethod
    def _parse_so_line(products: list[dict] | None) -> SalesOrderLine:
        if not products:
            return SalesOrderLine("", "", "Unknown", 0)
        p = products[0]
        pid = p.get("extra_id", "")
        return SalesOrderLine(
            product_id=pid,
            product_internal_id=pid,
            product_name=p.get("name", pid),
            quantity=p.get("quantity", 0),
            uom=p.get("uom", "pcs"),
        )

    def _parse_sales_order(self, d: dict) -> SalesOrder:
        return SalesOrder(
            id=d["id"],
            internal_id=d.get("internal_id", ""),
            customer=self._parse_customer(d.get("customer_attr", {})),
            line=self._parse_so_line(d.get("products")),
            deadline=self._parse_dt(d.get("expected_shipping_time")) or _DT_MIN,
            priority=d.get("priority", 99),
            status=d.get("status", "unknown"),
            notes=d.get("notes", ""),
            created_at=self._parse_dt(d.get("time")),
        )

    @staticmethod
    def _parse_product(d: dict) -> Product:
        return Product(
            id=d["id"],
            internal_id=d.get("internal_id", ""),
            name=d.get("name") or d.get("internal_id", ""),
        )

    @staticmethod
    def _extract_phase_name(p: dict) -> str:
        """Phase name lives under several possible nesting patterns."""
        return (
            (p.get("phase") or {}).get("name", "")
            or p.get("name", "")
            or p.get("phase_name", "")
            or (p.get("production_phase") or {}).get("name", "")
            or ""
        )

    def _parse_phase(self, d: dict) -> ProductionPhase:
        return ProductionPhase(
            id=d.get("id") or d.get("phase_id", ""),
            name=self._extract_phase_name(d),
            status=d.get("status", "not_ready"),
            starts_at=self._parse_dt(d.get("starts_at")),
            ends_at=self._parse_dt(d.get("ends_at")),
            duration_minutes=d.get("duration", 0),
        )

    def _parse_production_order(self, d: dict) -> ProductionOrder:
        raw_phases = d.get("phases") or d.get("production_phases") or []
        phases = [self._parse_phase(p) for p in raw_phases if self._extract_phase_name(p)]
        phases.sort(
            key=lambda p: PHASE_ORDER.index(p.name) if p.name in PHASE_ORDER else 99
        )
        starts_at = self._parse_dt(d.get("starts_at")) or _DT_MIN
        ends_at = self._parse_dt(d.get("ends_at")) or _DT_MIN

        dated_phases = [p for p in phases if p.starts_at and p.ends_at]
        if dated_phases:
            starts_at = min(p.starts_at for p in dated_phases)  # type: ignore[assignment]
            ends_at = max(p.ends_at for p in dated_phases)  # type: ignore[assignment]

        po = ProductionOrder(
            id=d["id"],
            internal_id=d.get("lot", d["id"][:12]),
            product_id=d.get("product_id", ""),
            product_name=d.get("product_name") or d.get("product_internal_id", ""),
            quantity=d.get("quantity", 0),
            starts_at=starts_at,
            ends_at=ends_at,
            status=d.get("status", "unknown"),
            product_internal_id=d.get("product_internal_id", ""),
            phases=phases,
        )
        self._known_po_ids.add(po.id)
        return po

    # ==================================================================
    # Auth
    # ==================================================================

    @property
    def is_authenticated(self) -> bool:
        return self._token is not None

    def set_token(self, token: str) -> None:
        self._token = token

    async def authenticate(self, username: str = "arke", password: str = "arke") -> str:
        """POST /api/login  →  stores and returns the JWT."""
        c = await self._client()
        r = await c.post(
            self._url("/login"),
            json={"username": username, "password": password},
        )
        r.raise_for_status()
        self._token = r.json()["accessToken"]
        return self._token

    # ==================================================================
    # Sales Orders
    # ==================================================================

    async def get_sales_orders(self, status: str = "accepted") -> list[SalesOrder]:
        """GET /api/sales/order/_active  (returns all orders with products)."""
        raw = await self._get("/sales/order/_active")
        orders = [self._parse_sales_order(d) for d in raw]
        orders.sort(key=lambda o: (o.deadline, o.priority))
        return orders

    async def get_sales_order(self, order_id: str) -> SalesOrder:
        """GET /api/sales/order/{id}  (full detail including notes & version)."""
        raw = await self._get(f"/sales/order/{order_id}")
        return self._parse_sales_order(raw)

    async def _so_read_modify_write(self, order_id: str, **fields: Any) -> SalesOrder:
        """GET full SO → mutate *fields* → PUT back with version."""
        raw = await self._get(f"/sales/order/{order_id}")
        for key, value in fields.items():
            raw[key] = value
        updated = await self._put(f"/sales/order/{order_id}", raw)
        return self._parse_sales_order(updated)

    async def update_sales_order_priority(self, order_id: str, priority: int) -> SalesOrder:
        return await self._so_read_modify_write(order_id, priority=priority)

    async def update_sales_order_quantity(self, order_id: str, quantity: int) -> SalesOrder:
        raw = await self._get(f"/sales/order/{order_id}")
        products = raw.get("products", [])
        if products:
            products[0]["quantity"] = quantity
        raw["products"] = products
        updated = await self._put(f"/sales/order/{order_id}", raw)
        return self._parse_sales_order(updated)

    async def update_sales_order_notes(self, order_id: str, notes: str) -> SalesOrder:
        return await self._so_read_modify_write(order_id, notes=notes)

    async def delete_sales_order(self, order_id: str) -> bool:
        await self._delete(f"/sales/order/{order_id}")
        return True

    # ==================================================================
    # Products
    # ==================================================================

    async def get_products(self) -> list[Product]:
        raw = await self._get("/product/product")
        return [self._parse_product(d) for d in raw if d.get("name")]

    # ==================================================================
    # Production Orders
    # ==================================================================

    async def get_production_orders(self) -> list[ProductionOrder]:
        """Fetch all tracked POs individually (no list endpoint exists)."""
        orders: list[ProductionOrder] = []
        gone: set[str] = set()
        for po_id in list(self._known_po_ids):
            try:
                orders.append(await self.get_production_order(po_id))
            except httpx.HTTPStatusError:
                gone.add(po_id)
        self._known_po_ids -= gone
        orders.sort(key=lambda o: o.starts_at)
        return orders

    async def get_production_order(self, order_id: str) -> ProductionOrder:
        raw = await self._get(f"/product/production/{order_id}")
        return self._parse_production_order(raw)

    async def create_production_order(
        self,
        product_id: str,
        quantity: int,
        starts_at: datetime,
        ends_at: datetime,
    ) -> ProductionOrder:
        """PUT /api/product/production  →  new PO in *planned* status."""
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        raw = await self._put("/product/production", {
            "product_id": product_id,
            "quantity": quantity,
            "starts_at": starts_at.strftime(fmt),
            "ends_at": ends_at.strftime(fmt),
        })
        return self._parse_production_order(raw)

    async def schedule_production_order(self, order_id: str) -> ProductionOrder:
        """POST /{id}/_schedule  →  generates phases from BOM."""
        await self._post(f"/product/production/{order_id}/_schedule")
        return await self.get_production_order(order_id)

    async def confirm_production_order(self, order_id: str) -> ProductionOrder:
        """POST /{id}/_start  →  moves PO from *planned* to *in_progress*."""
        await self._post(f"/product/production/{order_id}/_start")
        return await self.get_production_order(order_id)

    async def complete_production_order(self, order_id: str) -> ProductionOrder:
        """POST /{id}/_complete  →  marks PO as *completed*."""
        await self._post(f"/product/production/{order_id}/_complete")
        return await self.get_production_order(order_id)

    async def delete_production_order(self, order_id: str) -> bool:
        await self._delete(f"/product/production/{order_id}")
        self._known_po_ids.discard(order_id)
        return True

    async def update_production_order_dates(
        self,
        order_id: str,
        starts_at: datetime | None = None,
        ends_at: datetime | None = None,
    ) -> ProductionOrder:
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        if starts_at:
            await self._post(
                f"/product/production/{order_id}/_update_starting_date",
                {"starts_at": starts_at.strftime(fmt)},
            )
        if ends_at:
            await self._post(
                f"/product/production/{order_id}/_update_ending_date",
                {"ends_at": ends_at.strftime(fmt)},
            )
        return await self.get_production_order(order_id)

    # ------------------------------------------------------------------
    # Phase operations
    # ------------------------------------------------------------------

    async def update_phase_dates(
        self,
        phase_id: str,
        starts_at: datetime | None = None,
        ends_at: datetime | None = None,
    ) -> None:
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        if ends_at:
            await self._post(
                f"/product/production-order-phase/{phase_id}/_update_ending_date",
                {"ends_at": ends_at.strftime(fmt)},
            )
        if starts_at:
            await self._post(
                f"/product/production-order-phase/{phase_id}/_update_starting_date",
                {"starts_at": starts_at.strftime(fmt)},
            )

    async def start_phase(self, phase_id: str) -> None:
        await self._post(f"/product/production-order-phase/{phase_id}/_start")

    async def complete_phase(self, phase_id: str) -> None:
        await self._post(f"/product/production-order-phase/{phase_id}/_complete")

    # ==================================================================
    # Scheduling  (stubs — wire to your custom optimiser core)
    # ==================================================================

    async def get_current_schedule(self) -> Schedule | None:
        if self._current_schedule is not None:
            return self._current_schedule
        if not self._known_po_ids:
            return None
        from src.scheduler_logic.orchestrator import build_existing_schedule

        result = await build_existing_schedule(self)
        if result:
            self._current_schedule = result.schedule
        return self._current_schedule

    async def request_new_schedule(self, comment: str = "") -> ScheduleResult:
        from src.scheduler_logic.orchestrator import compute_schedule

        # ----------------------------------------------------------
        # Wipe ALL tracked POs (best-effort delete from Arke) and
        # clear tracking so compute_schedule starts from scratch.
        # ----------------------------------------------------------
        if self._known_po_ids:
            logger.info(
                "Cleaning up %d tracked POs before regenerating",
                len(self._known_po_ids),
            )
            for po_id in list(self._known_po_ids):
                try:
                    await self.delete_production_order(po_id)
                except Exception:
                    logger.warning("Could not delete PO %s", po_id[:8])
        self._known_po_ids.clear()
        self._so_po_map.clear()
        self._current_schedule = None

        # ----------------------------------------------------------
        # AI replanner (when user provided a comment)
        # ----------------------------------------------------------
        ai_reorder: list[str] | None = None
        ai_comment = ""
        ai_conflicts: list[str] | None = None

        if comment and os.environ.get("GEMINI_API_KEY"):
            try:
                from src.ai_scheduler_helper import (
                    build_ai_input,
                    propose_schedule_revision,
                )

                sales_orders = await self.get_sales_orders()
                sim_now = self.get_sim_now()
                pending = [
                    so for so in sales_orders
                    if so.deadline > sim_now
                ]

                ai_input = build_ai_input([], pending, comment, sim_now)
                ai_output = await propose_schedule_revision(ai_input)

                for pu in ai_output.priority_updates:
                    try:
                        await self.update_sales_order_priority(
                            pu.sales_order_id, pu.new_priority,
                        )
                        logger.info("AI priority update: %s -> P%d (%s)",
                                    pu.sales_order_id[:8], pu.new_priority, pu.reason)
                    except Exception:
                        logger.warning("Failed to apply AI priority update for %s",
                                       pu.sales_order_id[:8])

                ai_reorder = ai_output.reordered_so_ids or None
                ai_comment = ai_output.ai_comment
                ai_conflicts = ai_output.conflicts or None

                logger.info("AI replanner: reorder=%s, comment=%s",
                            bool(ai_reorder), ai_comment[:80] if ai_comment else "")
            except Exception:
                logger.exception("AI replanner failed, falling back to EDF")

        result = await compute_schedule(
            self, comment,
            ai_reorder=ai_reorder,
            ai_comment=ai_comment,
            ai_conflicts=ai_conflicts,
        )
        self._current_schedule = result.schedule
        return result

    async def accept_schedule(self, schedule_id: str) -> bool:
        sched = self._current_schedule
        if not sched:
            return False
        for entry in sched.entries:
            if not entry.is_existing and entry.production_order.status == "planned":
                try:
                    await self.confirm_production_order(entry.production_order.id)
                except Exception:
                    logger.exception(
                        "Failed to confirm PO %s", entry.production_order.id,
                    )
        sched.status = "accepted"
        return True

    async def reject_schedule(self, schedule_id: str, reason: str = "") -> bool:
        sched = self._current_schedule
        if not sched:
            return False
        for entry in sched.entries:
            if not entry.is_existing:
                try:
                    await self.delete_production_order(entry.production_order.id)
                    self._so_po_map.pop(entry.sales_order.id, None)
                except Exception:
                    logger.exception(
                        "Failed to delete PO %s on reject", entry.production_order.id,
                    )
        self._current_schedule = None
        return True

    # ==================================================================
    # Dashboard  (assembled from live API data)
    # ==================================================================

    async def get_dashboard_summary(self) -> DashboardSummary:
        orders = await self.get_sales_orders()

        by_priority: dict[int, int] = {}
        for o in orders:
            by_priority[o.priority] = by_priority.get(o.priority, 0) + 1

        upcoming = sorted(orders, key=lambda o: o.deadline)[:5]

        production_orders: list[ProductionOrder] = []
        by_status: dict[str, int] = {}
        if self._known_po_ids:
            production_orders = await self.get_production_orders()
            for po in production_orders:
                by_status[po.status] = by_status.get(po.status, 0) + 1

        alerts: list[str] = []
        now = self.get_sim_now()
        for o in orders:
            days_left = (o.deadline - now).days
            if days_left <= 2:
                alerts.append(
                    f"{o.internal_id} deadline in {days_left}d "
                    f"({o.line.product_internal_id})"
                )

        return DashboardSummary(
            total_sales_orders=len(orders),
            orders_by_priority=by_priority,
            total_production_orders=len(production_orders),
            production_by_status=by_status,
            upcoming_deadlines=upcoming,
            active_alerts=alerts,
        )

    # ==================================================================
    # Helpers
    # ==================================================================

    def track_production_order(self, po_id: str) -> None:
        """Register a PO id so ``get_production_orders`` can fetch it."""
        self._known_po_ids.add(po_id)
