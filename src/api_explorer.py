"""
Exhaustive Arke API exploration script.

Probes every known endpoint (and guesses at undocumented ones), prints full
request/response details including headers, status codes, body schemas, and
field types so we know exactly what to implement in the Telegram bot API client.

Run:  uv run python src/api_explorer.py
"""

import json
import os
import sys
import textwrap
from datetime import datetime, timedelta, timezone

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests

BASE_URL = "https://hackathon3.arke.so/api"
USERNAME = "arke"
PASSWORD = "arke"
TODAY = datetime(2026, 2, 28, 8, 0, 0, tzinfo=timezone.utc)

TOKEN: str = ""
CALL_COUNT = 0

# ──────────────────────────────────────────────────────────────
# Utility
# ──────────────────────────────────────────────────────────────

def hdr():
    return {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def banner(title: str):
    width = 78
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print(f"{'=' * width}")


def section(title: str):
    print(f"\n--- {title} {'─' * max(0, 60 - len(title))}")


def dump_schema(obj, prefix="", depth=0):
    """Recursively print field names, types, and sample values."""
    indent = "  " * depth
    if isinstance(obj, dict):
        for k, v in obj.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                print(f"{indent}{k}: dict  (keys: {list(v.keys())})")
                dump_schema(v, full_key, depth + 1)
            elif isinstance(v, list):
                print(f"{indent}{k}: list[{len(v)}]")
                if v:
                    first = v[0]
                    if isinstance(first, dict):
                        print(f"{indent}  [0] keys: {list(first.keys())}")
                        dump_schema(first, f"{full_key}[0]", depth + 2)
                    else:
                        print(f"{indent}  [0] = {first!r}  ({type(first).__name__})")
            else:
                sample = repr(v)
                if len(sample) > 80:
                    sample = sample[:77] + "..."
                print(f"{indent}{k}: {type(v).__name__} = {sample}")
    elif isinstance(obj, list):
        print(f"{indent}list[{len(obj)}]")
        if obj:
            dump_schema(obj[0], f"{prefix}[0]", depth + 1)


def probe(method: str, path: str, body=None, label: str = "", expect_fail=False):
    """Fire a request, print everything, return (status, json_or_None)."""
    global CALL_COUNT
    CALL_COUNT += 1
    url = f"{BASE_URL}{path}"
    tag = label or f"{method} {path}"
    section(tag)

    print(f"  → {method} {url}")
    if body is not None:
        print(f"  → Body: {json.dumps(body, indent=4, default=str)}")

    try:
        resp = requests.request(method, url, json=body, headers=hdr(), timeout=15)
    except Exception as exc:
        print(f"  ✗ Request exception: {exc}")
        return 0, None

    print(f"  ← Status: {resp.status_code}  ({resp.reason})")
    print(f"  ← Content-Type: {resp.headers.get('Content-Type', 'N/A')}")
    print(f"  ← Content-Length: {resp.headers.get('Content-Length', len(resp.content))}")

    data = None
    try:
        data = resp.json()
    except Exception:
        text = resp.text[:500] if resp.text else "(empty)"
        print(f"  ← Raw text: {text}")
        return resp.status_code, None

    if isinstance(data, list):
        print(f"  ← JSON array, length={len(data)}")
        if data:
            print(f"  ← First element keys: {list(data[0].keys()) if isinstance(data[0], dict) else type(data[0]).__name__}")
            print(f"\n  Schema of [0]:")
            dump_schema(data[0], depth=2)
            if len(data) > 1:
                print(f"\n  (... {len(data)-1} more items)")
    elif isinstance(data, dict):
        print(f"  ← JSON object, keys: {list(data.keys())}")
        print(f"\n  Schema:")
        dump_schema(data, depth=2)
    else:
        print(f"  ← JSON value: {data!r}")

    if not expect_fail and not resp.ok:
        print(f"  ⚠ UNEXPECTED FAILURE")
    if expect_fail and resp.ok:
        print(f"  ✓ UNEXPECTED SUCCESS (expected failure)")

    print(f"\n  Full JSON (first 2000 chars):")
    pretty = json.dumps(data, indent=2, default=str)
    print(textwrap.indent(pretty[:2000], "    "))
    if len(pretty) > 2000:
        print(f"    ... ({len(pretty) - 2000} chars truncated)")

    return resp.status_code, data


# ──────────────────────────────────────────────────────────────
# 0. Auth
# ──────────────────────────────────────────────────────────────

def explore_auth():
    global TOKEN
    banner("0. AUTHENTICATION")

    section("POST /login")
    resp = requests.post(f"{BASE_URL}/login", json={"username": USERNAME, "password": PASSWORD})
    print(f"  ← Status: {resp.status_code}")
    data = resp.json()
    print(f"  ← Keys: {list(data.keys())}")
    dump_schema(data, depth=2)
    TOKEN = data["accessToken"]
    print(f"  ← Token (first 60): {TOKEN[:60]}...")


# ──────────────────────────────────────────────────────────────
# 1. Sales Orders – read
# ──────────────────────────────────────────────────────────────

def explore_sales_orders_read():
    banner("1. SALES ORDERS — READ")

    _, orders_accepted = probe("GET", "/sales/order?status=accepted",
                                label="GET /sales/order?status=accepted")

    _, orders_active = probe("GET", "/sales/order/_active",
                              label="GET /sales/order/_active")

    # Compare schemas between the two endpoints
    if orders_accepted and orders_active:
        section("Schema comparison: accepted vs _active")
        keys_a = set(orders_accepted[0].keys()) if orders_accepted else set()
        keys_b = set(orders_active[0].keys()) if orders_active else set()
        print(f"  ?status=accepted keys:  {sorted(keys_a)}")
        print(f"  _active keys:           {sorted(keys_b)}")
        print(f"  Only in accepted:       {sorted(keys_a - keys_b)}")
        print(f"  Only in _active:        {sorted(keys_b - keys_a)}")

    # Grab one order ID for detail probing
    first_id = None
    if orders_active:
        first_id = orders_active[0]["id"]
    elif orders_accepted:
        first_id = orders_accepted[0]["id"]

    if first_id:
        _, detail = probe("GET", f"/sales/order/{first_id}",
                           label=f"GET /sales/order/{{id}}  (id={first_id[:8]}...)")

    # Try other statuses
    for st in ["draft", "in_progress", "completed", "cancelled", "all"]:
        probe("GET", f"/sales/order?status={st}",
              label=f"GET /sales/order?status={st}",
              expect_fail=True)

    return orders_active or orders_accepted


# ──────────────────────────────────────────────────────────────
# 2. Sales Orders – mutations (discover what's possible)
# ──────────────────────────────────────────────────────────────

def explore_sales_orders_mutate(orders):
    banner("2. SALES ORDERS — MUTATIONS (discovery)")

    if not orders:
        print("  (no orders to test on)")
        return

    test_id = orders[0]["id"]
    tag = f"(id={test_id[:8]}...)"

    # Try PATCH
    probe("PATCH", f"/sales/order/{test_id}",
          body={"priority": orders[0].get("priority", 2)},
          label=f"PATCH /sales/order/{{id}} {tag}",
          expect_fail=True)

    # Try PUT (full replace)
    probe("PUT", f"/sales/order/{test_id}",
          body={"priority": orders[0].get("priority", 2)},
          label=f"PUT /sales/order/{{id}} {tag}",
          expect_fail=True)

    # Try POST with update-style body
    probe("POST", f"/sales/order/{test_id}",
          body={"priority": orders[0].get("priority", 2)},
          label=f"POST /sales/order/{{id}} {tag}",
          expect_fail=True)

    # Try common action patterns
    for action in ["_update", "_cancel", "_archive", "_update_priority",
                    "_set_priority", "_edit", "_update_notes"]:
        probe("POST", f"/sales/order/{test_id}/{action}",
              body={"priority": 2, "notes": "test"},
              label=f"POST /sales/order/{{id}}/{action}",
              expect_fail=True)

    # Try DELETE
    probe("DELETE", f"/sales/order/{test_id}",
          label=f"DELETE /sales/order/{{id}} {tag}",
          expect_fail=True)


# ──────────────────────────────────────────────────────────────
# 3. Products
# ──────────────────────────────────────────────────────────────

def explore_products():
    banner("3. PRODUCTS & BOM")

    _, products = probe("GET", "/product/product", label="GET /product/product")

    if products:
        first_pid = products[0].get("id")
        if first_pid:
            probe("GET", f"/product/product/{first_pid}",
                  label=f"GET /product/product/{{id}} (id={first_pid[:8]}...)")

    _, phases = probe("GET", "/product/production-phase",
                       label="GET /product/production-phase")

    return products


# ──────────────────────────────────────────────────────────────
# 4. Warehouse
# ──────────────────────────────────────────────────────────────

def explore_warehouse():
    banner("4. WAREHOUSE")
    probe("GET", "/iam/warehouse", label="GET /iam/warehouse")


# ──────────────────────────────────────────────────────────────
# 5. Production Orders – read existing
# ──────────────────────────────────────────────────────────────

def explore_production_read():
    banner("5. PRODUCTION ORDERS — LIST / READ")

    # Try list endpoints (undocumented, but common patterns)
    _, po_list = probe("GET", "/product/production",
                        label="GET /product/production (list all)")

    for st in ["planned", "in_progress", "completed", "confirmed"]:
        probe("GET", f"/product/production?status={st}",
              label=f"GET /product/production?status={st}",
              expect_fail=True)

    return po_list


# ──────────────────────────────────────────────────────────────
# 6. Production Order lifecycle — create, schedule, start, phase ops
# ──────────────────────────────────────────────────────────────

def explore_production_lifecycle(products):
    banner("6. PRODUCTION ORDER LIFECYCLE")

    if not products:
        print("  (no products available)")
        return None

    # Pick first product for test
    product = products[0]
    product_id = product["id"]
    product_name = product.get("internal_id") or product.get("name", "?")
    print(f"  Using product: {product_name} (id={product_id[:8]}...)")

    # ── 6a. Create ──
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    create_body = {
        "product_id": product_id,
        "quantity": 1,
        "starts_at": TODAY.strftime(fmt),
        "ends_at": (TODAY + timedelta(days=3)).strftime(fmt),
    }
    status, po = probe("PUT", "/product/production", body=create_body,
                        label="PUT /product/production (CREATE)")
    if not po or status >= 400:
        print("  ✗ Cannot continue lifecycle without a PO")
        return None

    po_id = po.get("id")
    print(f"\n  ★ Created PO id={po_id}")

    # ── 6b. Get detail (before scheduling) ──
    _, detail_pre = probe("GET", f"/product/production/{po_id}",
                           label=f"GET /product/production/{{id}} (BEFORE _schedule)")

    # ── 6c. Schedule (generate phases from BOM) ──
    _, sched_resp = probe("POST", f"/product/production/{po_id}/_schedule",
                           label=f"POST /product/production/{{id}}/_schedule")

    # ── 6d. Get detail (after scheduling) ──
    _, detail_post = probe("GET", f"/product/production/{po_id}",
                            label=f"GET /product/production/{{id}} (AFTER _schedule)")

    # Compare keys before/after
    if detail_pre and detail_post:
        section("Keys diff: before vs after _schedule")
        keys_pre = set(detail_pre.keys())
        keys_post = set(detail_post.keys())
        print(f"  Before: {sorted(keys_pre)}")
        print(f"  After:  {sorted(keys_post)}")
        print(f"  New keys after _schedule: {sorted(keys_post - keys_pre)}")

    # ── 6e. Explore phases ──
    phases = []
    if detail_post:
        for key in ["phases", "production_phases", "plan", "production_order_phases"]:
            if key in detail_post and detail_post[key]:
                phases = detail_post[key]
                print(f"\n  Phases found under key '{key}', count={len(phases)}")
                break

    if phases:
        section("Phase objects detail")
        for i, ph in enumerate(phases):
            print(f"\n  Phase [{i}]:")
            dump_schema(ph, depth=3)

    # ── 6f. Try _confirm vs _start on PO ──
    section("PO action: _confirm")
    probe("POST", f"/product/production/{po_id}/_confirm",
          label="POST /product/production/{id}/_confirm",
          expect_fail=True)

    section("PO action: _start")
    probe("POST", f"/product/production/{po_id}/_start",
          label="POST /product/production/{id}/_start",
          expect_fail=True)

    # ── 6g. Try other PO actions ──
    for action in ["_complete", "_cancel", "_pause", "_resume", "_reset"]:
        probe("POST", f"/product/production/{po_id}/{action}",
              label=f"POST /product/production/{{id}}/{action}",
              expect_fail=True)

    # ── 6h. Update PO dates ──
    new_start = TODAY + timedelta(hours=1)
    new_end = TODAY + timedelta(days=4)
    probe("POST", f"/product/production/{po_id}/_update_starting_date",
          body={"starts_at": new_start.strftime(fmt)},
          label="POST /production/{id}/_update_starting_date (starts_at)")

    probe("POST", f"/product/production/{po_id}/_update_ending_date",
          body={"ends_at": new_end.strftime(fmt)},
          label="POST /production/{id}/_update_ending_date (ends_at)")

    # Try alternate field names
    probe("POST", f"/product/production/{po_id}/_update_starting_date",
          body={"starting_date": new_start.strftime(fmt)},
          label="POST _update_starting_date (starting_date variant)",
          expect_fail=True)

    # ── 6i. Phase lifecycle ops ──
    if phases:
        ph = phases[0]
        ph_id = ph.get("id") or ph.get("phase_id")
        ph_name_obj = ph.get("phase", {})
        ph_name = ph_name_obj.get("name") if isinstance(ph_name_obj, dict) else str(ph_name_obj)
        print(f"\n  Testing phase ops on phase_id={ph_id}, name={ph_name}")

        # Update phase dates
        ph_start = TODAY
        ph_end = TODAY + timedelta(hours=1)
        probe("POST", f"/product/production-order-phase/{ph_id}/_update_starting_date",
              body={"starts_at": ph_start.strftime(fmt)},
              label=f"POST /production-order-phase/{{id}}/_update_starting_date")

        probe("POST", f"/product/production-order-phase/{ph_id}/_update_ending_date",
              body={"ends_at": ph_end.strftime(fmt)},
              label=f"POST /production-order-phase/{{id}}/_update_ending_date")

        # Try to start phase
        probe("POST", f"/product/production-order-phase/{ph_id}/_start",
              label=f"POST /production-order-phase/{{id}}/_start",
              expect_fail=True)

        # Try to make it ready first
        probe("POST", f"/product/production-order-phase/{ph_id}/_ready",
              label=f"POST /production-order-phase/{{id}}/_ready",
              expect_fail=True)

        # Complete phase
        probe("POST", f"/product/production-order-phase/{ph_id}/_complete",
              label=f"POST /production-order-phase/{{id}}/_complete",
              expect_fail=True)

        # Re-read PO to see phase status changes
        _, detail_after_ops = probe("GET", f"/product/production/{po_id}",
                                     label="GET production/{id} (AFTER phase ops)")

    # ── 6j. PATCH / PUT on production order ──
    probe("PATCH", f"/product/production/{po_id}",
          body={"quantity": 2},
          label="PATCH /product/production/{id}",
          expect_fail=True)

    probe("PUT", f"/product/production/{po_id}",
          body={"quantity": 2, "product_id": product_id,
                "starts_at": TODAY.strftime(fmt),
                "ends_at": (TODAY + timedelta(days=3)).strftime(fmt)},
          label="PUT /product/production/{id}",
          expect_fail=True)

    # ── 6k. DELETE production order ──
    probe("DELETE", f"/product/production/{po_id}",
          label="DELETE /product/production/{id}",
          expect_fail=True)

    return po_id


# ──────────────────────────────────────────────────────────────
# 7. Discover undocumented endpoints
# ──────────────────────────────────────────────────────────────

def explore_undocumented():
    banner("7. ENDPOINT DISCOVERY (guessing)")

    guesses = [
        ("GET",  "/sales/customer"),
        ("GET",  "/sales/order/_count"),
        ("GET",  "/product/production/_active"),
        ("GET",  "/product/production/_count"),
        ("GET",  "/product/production-order-phase"),
        ("GET",  "/product/bom"),
        ("GET",  "/iam/user"),
        ("GET",  "/iam/tenant"),
        ("GET",  "/notifications"),
        ("GET",  "/dashboard"),
        ("GET",  "/health"),
        ("GET",  "/status"),
    ]
    for method, path in guesses:
        probe(method, path, label=f"DISCOVER: {method} {path}", expect_fail=True)


# ──────────────────────────────────────────────────────────────
# 8. Full dump of one sales order for field reference
# ──────────────────────────────────────────────────────────────

def dump_full_sales_order(orders):
    banner("8. FULL SALES ORDER DUMP (first 3 orders)")
    if not orders:
        print("  (no orders)")
        return

    for order in orders[:3]:
        oid = order["id"]
        section(f"Sales Order {order.get('internal_id', oid[:8])}")
        _, detail = probe("GET", f"/sales/order/{oid}",
                           label=f"GET /sales/order/{oid[:8]}... (full dump)")
        if detail:
            print(f"\n  COMPLETE JSON:")
            print(textwrap.indent(json.dumps(detail, indent=2, default=str), "    "))


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

def main():
    print(f"Arke API Explorer — {datetime.now()}")
    print(f"Target: {BASE_URL}\n")

    explore_auth()
    orders = explore_sales_orders_read()
    explore_sales_orders_mutate(orders)
    products = explore_products()
    explore_warehouse()
    existing_pos = explore_production_read()
    po_id = explore_production_lifecycle(products)
    explore_undocumented()
    dump_full_sales_order(orders)

    banner("DONE")
    print(f"\n  Total API calls made: {CALL_COUNT}")
    print(f"  Timestamp: {datetime.now()}\n")


if __name__ == "__main__":
    main()
