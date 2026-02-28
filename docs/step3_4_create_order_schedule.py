import requests
import json
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
from datetime import datetime, timedelta, timezone

# Shared config, constants, and helpers from step 1 (API + factory data)
from step1_api_call import (
    ARKE_BASE_URL,
    get_headers,
    PHASE_DURATIONS,
    PHASES_ORDER,
    MINUTES_PER_DAY,
    PRODUCT_ID_MAP,
    TODAY,
)

# EDF conflict explanation lives in the planning module
from step2_plan_policy import detect_so005_conflict

# ══════════════════════════════════════════════════════════════════════
# STEP 3+4 — Create production orders & schedule phases
# ══════════════════════════════════════════════════════════════════════
def build_product_map(token):
    r = requests.get(f"{ARKE_BASE_URL}/api/product/product", headers=get_headers(token))
    r.raise_for_status()
    for p in r.json():
        PRODUCT_ID_MAP[p['internal_id']] = p['id']
    print(f"✅ Product map: {list(PRODUCT_ID_MAP.keys())}")

def compute_total_minutes(product_id, quantity):
    durations = PHASE_DURATIONS.get(product_id, {})
    return sum(mins * quantity for mins in durations.values())

def get_phase_name(p):
    """
    Extract phase name from Arke's nested phase object.
    Arke returns: {"id": "...", "phase": {"name": "SMT"}}
    Must check p['phase']['name'] first — top-level 'name' is absent.
    """
    return (
        p.get('phase', {}).get('name') or
        p.get('name') or
        p.get('phase_name') or
        p.get('production_phase', {}).get('name') or
        ''
    )

def set_phase_dates(token, phase_id, start_dt, end_dt):
    """
    Field names confirmed working: starts_at / ends_at
    (starting_date / ending_date returned 500 errors)
    """
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    r1 = requests.post(
        f"{ARKE_BASE_URL}/api/product/production-order-phase/{phase_id}/_update_starting_date",
        json={"starts_at": start_dt.strftime(fmt)},
        headers=get_headers(token)
    )
    r2 = requests.post(
        f"{ARKE_BASE_URL}/api/product/production-order-phase/{phase_id}/_update_ending_date",
        json={"ends_at": end_dt.strftime(fmt)},
        headers=get_headers(token)
    )
    if not r1.ok: print(f"   ⚠️  start date failed: {r1.status_code} {r1.text}")
    if not r2.ok: print(f"   ⚠️  end date failed:   {r2.status_code} {r2.text}")

def create_and_schedule(token, order, current_time):
    product_id   = order['_product_id']
    quantity     = order['_quantity']
    ends_at      = order['expected_shipping_time']
    so_id        = order['internal_id']
    product_uuid = PRODUCT_ID_MAP.get(product_id)

    if not product_uuid:
        print(f"❌ Product UUID not found for {product_id}")
        return current_time, None

    payload = {
        "product_id": product_uuid,
        "quantity":   quantity,
        "starts_at":  current_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ends_at":    ends_at,
    }
    r = requests.put(
        f"{ARKE_BASE_URL}/api/product/production",
        json=payload,
        headers=get_headers(token)
    )
    if not r.ok:
        print(f"❌ Create PO failed for {so_id}: {r.status_code} {r.text}")
        return current_time, None

    po    = r.json()
    po_id = po.get('id')
    print(f"\n✅ PO created: {po_id} | {so_id} | {product_id} x{quantity}")

    r2 = requests.post(
        f"{ARKE_BASE_URL}/api/product/production/{po_id}/_schedule",
        headers=get_headers(token)
    )
    if not r2.ok:
        print(f"   ⚠️  _schedule failed: {r2.status_code} {r2.text}")

    detail     = requests.get(
        f"{ARKE_BASE_URL}/api/product/production/{po_id}",
        headers=get_headers(token)
    ).json()
    phases_raw = (
        detail.get('phases') or
        detail.get('production_phases') or
        detail.get('plan') or
        []
    )
    if not phases_raw:
        print(f"   ⚠️  No phases found. Keys: {list(detail.keys())}")

    phases_sorted = sorted(
        phases_raw,
        key=lambda p: PHASES_ORDER.index(get_phase_name(p))
        if get_phase_name(p) in PHASES_ORDER else 99
    )

    phase_start = current_time
    phase_log   = []

    for phase in phases_sorted:
        phase_id   = phase.get('id') or phase.get('phase_id')
        phase_name = get_phase_name(phase)
        mins_per_u = PHASE_DURATIONS.get(product_id, {}).get(phase_name, 0)

        if mins_per_u == 0 or not phase_id or phase_name not in PHASES_ORDER:
            continue

        total_mins = mins_per_u * quantity
        phase_end  = phase_start + timedelta(minutes=total_mins)

        set_phase_dates(token, phase_id, phase_start, phase_end)

        days = total_mins / MINUTES_PER_DAY
        print(f"   ⏱  {phase_name:<10} "
              f"{phase_start.strftime('%m-%d %H:%M')} → {phase_end.strftime('%m-%d %H:%M')}  "
              f"({total_mins} min / {days:.1f} days)")

        phase_log.append({'name': phase_name, 'start': phase_start, 'end': phase_end})
        phase_start = phase_end

    current_time = phase_start
    deadline     = datetime.fromisoformat(ends_at.replace('Z', '+00:00'))
    on_time      = current_time <= deadline
    print(f"   → PO ends: {current_time.strftime('%Y-%m-%d %H:%M')} | "
          f"Deadline: {deadline.strftime('%Y-%m-%d')} {'✅' if on_time else '❌ LATE'}")

    log_entry = {
        'so_id':       so_id,
        'po_id':       po_id,
        'product_id':  product_id,
        'quantity':    quantity,
        'customer':    order['customer_attr']['name'],
        'po_start':    datetime.fromisoformat(payload['starts_at'].replace('Z', '+00:00')),
        'po_end':      current_time,
        'deadline':    deadline,
        'priority':    order['priority'],
        'phases':      phase_log,
        'on_time':     on_time,
    }
    return current_time, log_entry

def schedule_all_orders(token, sorted_orders):
    build_product_map(token)
    detect_so005_conflict(sorted_orders)

    current_time = TODAY
    schedule_log = []

    print("\n🏭 Creating and scheduling all production orders...\n")
    for order in sorted_orders:
        current_time, log_entry = create_and_schedule(token, order, current_time)
        if log_entry:
            schedule_log.append(log_entry)

    print("\n" + "="*65)
    print("📋 FINAL SCHEDULE SUMMARY")
    print("="*65)
    for e in schedule_log:
        status = "✅" if e['on_time'] else "❌ LATE"
        print(f"  {e['so_id']} | {e['product_id']:<12} x{e['quantity']:<3} | "
              f"{e['po_start'].strftime('%b %d %H:%M')} → {e['po_end'].strftime('%b %d %H:%M')} | "
              f"Deadline: {e['deadline'].strftime('%b %d')} {status}")

    return schedule_log
