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
from api import (
    fetch_production_order_by_id,
    update_production_order_start,
    update_production_order_end,
)

# ══════════════════════════════════════════════════════════════════════
# WORKING HOURS HELPER
#
# The factory runs exactly 480 min/day (08:00–16:00), 7 days/week.
# Raw timedelta arithmetic ignores the end-of-day boundary — this
# function correctly carries remaining minutes to the next morning.
#
# Example:
#   add_working_minutes(Feb 28 15:00, 120 min)
#   → only 60 min left today (15:00→16:00)
#   → 60 min remaining carry to Mar 1 08:00→09:00
#   → returns Mar 1 09:00
#
# ══════════════════════════════════════════════════════════════════════
DAY_START_HOUR = 8   # 08:00
DAY_END_HOUR   = 16  # 16:00  (08:00 + 480 min)

def add_working_minutes(start_dt, minutes):
    """
    Advance a datetime by `minutes` of working time, respecting the
    08:00–16:00 shift. Rolls over to the next day's 08:00 when the
    shift ends, consuming any leftover capacity first.

    Args:
        start_dt : timezone-aware datetime within a working shift
        minutes  : total working minutes to add (>= 0)

    Returns:
        timezone-aware datetime after `minutes` of production time
    """
    current   = start_dt
    remaining = minutes

    while remaining > 0:
        # How many minutes have already been used today since 08:00
        elapsed_today    = (current.hour * 60 + current.minute) - (DAY_START_HOUR * 60)
        # How many minutes remain in today's shift
        left_in_shift    = MINUTES_PER_DAY - elapsed_today

        if remaining <= left_in_shift:
            # Fits entirely within today's remaining shift — done
            current   = current + timedelta(minutes=remaining)
            remaining = 0
        else:
            # Spills past 16:00 — consume today's remainder, jump to
            # next day 08:00, and continue with what's left
            remaining -= left_in_shift
            current    = (current + timedelta(days=1)).replace(
                hour=DAY_START_HOUR, minute=0, second=0, microsecond=0
            )

    return current


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

def _parse_dt(value):
    """Coerce Arke timestamp string into a timezone-aware datetime.
    The API sometimes uses Z suffix; Python's fromisoformat requires
    explicit offset. Return `None` if value is falsy.
    """
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def set_phase_dates(token, phase_id, start_dt, end_dt, old_start_dt=None):
    """
    Update a single phase in Arke with the supplied start/end datetimes.

    Historically we always updated the **end** date first, then the
    start.  That avoids the validation error "starting date cannot be
    after ending date" when moving an existing phase **later** in the
    calendar (the old end is compared to the new start).  However, when
    rescheduling orders _earlier_ (e.g. skipping a failed product order
    and pushing later orders forward) the new end timestamp can end up
    before the *existing* start stored on the server.  In that case the
    first POST would be rejected with 400/invalid-date.  The fix is to
    adjust the update order based on whether the new range moves
    backwards.

    Args:
        token: API JWT
        phase_id: Arke phase UUID
        start_dt: desired new start (tz-aware)
        end_dt: desired new end (tz-aware)
        old_start_dt: if known, the server's current start time for this
            phase; used to decide whether to post start or end first.
    """
    fmt = "%Y-%m-%dT%H:%M:%SZ"

    # decide update order.  default is end→start (safe for moving
    # later).  if our new end would be before the *old* start, then flip
    # the order so that the server validates against the updated start.
    update_end_first = True
    if old_start_dt is not None and end_dt < old_start_dt:
        update_end_first = False

    r_start = None
    r_end = None

    if update_end_first:
        r_end = requests.post(
            f"{ARKE_BASE_URL}/api/product/production-order-phase/{phase_id}/_update_ending_date",
            json={"ends_at": end_dt.strftime(fmt)},
            headers=get_headers(token),
        )
        r_start = requests.post(
            f"{ARKE_BASE_URL}/api/product/production-order-phase/{phase_id}/_update_starting_date",
            json={"starts_at": start_dt.strftime(fmt)},
            headers=get_headers(token),
        )
    else:
        # moving this phase earlier than its previous start – update the
        # start timestamp **before** the end so the API validates against
        # the new start.
        print(f"   🔄 phase {phase_id}: start<old, updating start first")
        r_start = requests.post(
            f"{ARKE_BASE_URL}/api/product/production-order-phase/{phase_id}/_update_starting_date",
            json={"starts_at": start_dt.strftime(fmt)},
            headers=get_headers(token),
        )
        r_end = requests.post(
            f"{ARKE_BASE_URL}/api/product/production-order-phase/{phase_id}/_update_ending_date",
            json={"ends_at": end_dt.strftime(fmt)},
            headers=get_headers(token),
        )

    if not r_start.ok:
        print(f"   ⚠️  start date failed: {r_start.status_code} {r_start.text}")
    if not r_end.ok:
        print(f"   ⚠️  end date failed:   {r_end.status_code} {r_end.text}")


def reschedule_single_order(token, log_entry, start_time):
    """
    Reschedule one production order (existing PO) to start at start_time.
    Updates phase dates in Arke and PO start/end. Returns new end time and updated log entry.
    """
    po_id = log_entry["po_id"]
    product_id = log_entry["product_id"]
    quantity = log_entry["quantity"]
    fmt = "%Y-%m-%dT%H:%M:%SZ"

    detail = fetch_production_order_by_id(token, po_id)
    phases_raw = (
        detail.get("phases")
        or detail.get("production_phases")
        or detail.get("plan")
        or []
    )
    phases_sorted = sorted(
        phases_raw,
        key=lambda p: PHASES_ORDER.index(get_phase_name(p))
        if get_phase_name(p) in PHASES_ORDER
        else 99,
    )

    phase_start = start_time
    phase_log = []

    for phase in phases_sorted:
        phase_id = phase.get("id") or phase.get("phase_id")
        phase_name = get_phase_name(phase)
        mins_per_u = PHASE_DURATIONS.get(product_id, {}).get(phase_name, 0)

        if mins_per_u == 0 or not phase_id or phase_name not in PHASES_ORDER:
            continue

        # ── NEW: Skip started/completed phases ──
        # If a phase is already running or done, we cannot change its dates.
        # We accept its existing timeline and schedule subsequent phases after it.
        status = phase.get("status")
        if status in ("started", "completed"):
            existing_start = phase.get("starts_at") or phase.get("starting_date")
            existing_end = phase.get("ends_at") or phase.get("ending_date")
            
            # Parse or fallback to current cursor if missing (unlikely)
            p_start = _parse_dt(existing_start) if existing_start else phase_start
            p_end   = _parse_dt(existing_end)   if existing_end   else phase_start
            
            print(f"   🔒 {phase_name:<10} is {status}, keeping {p_start.strftime('%m-%d %H:%M')} → {p_end.strftime('%m-%d %H:%M')}")
            
            phase_log.append({"name": phase_name, "start": p_start, "end": p_end})
            # The next phase starts after this one finishes
            phase_start = p_end
            continue

        # grab the existing start timestamp from Arke (if present) so we
        # can detect when the reschedule is trying to move the phase
        # earlier than it was originally planned.
        old_start_dt = None
        existing = (
            phase.get("starts_at") or
            phase.get("starting_date") or
            phase.get("start")
        )
        if existing:
            old_start_dt = _parse_dt(existing)

        # Ensure we don't schedule a new phase in the past (before the order's allowed start)
        # even if the previous phase finished long ago.
        if phase_start < start_time:
            phase_start = start_time

        total_mins = mins_per_u * quantity
        phase_end = add_working_minutes(phase_start, total_mins)
        set_phase_dates(token, phase_id, phase_start, phase_end, old_start_dt)
        phase_log.append({"name": phase_name, "start": phase_start, "end": phase_end})
        phase_start = phase_end

    end_time = phase_start
    try:
        update_production_order_start(token, po_id, start_time.strftime(fmt))
        update_production_order_end(token, po_id, end_time.strftime(fmt))
    except Exception as e:
        # Server may reject PO-level date change (e.g. order in progress); phase dates are already updated
        print(f"   ⚠️  PO date update skipped for {po_id}: {e}")

    updated_entry = dict(log_entry)
    updated_entry["po_start"] = start_time
    updated_entry["po_end"] = end_time
    updated_entry["phases"] = phase_log
    return end_time, updated_entry


def reschedule_orders_from_time(token, schedule_entries, start_time):
    """
    Reschedule a list of production orders to run sequentially from start_time.
    Returns (end_time_after_last, list of updated log entries).
    """
    current_time = start_time
    updated_entries = []
    for entry in schedule_entries:
        current_time, updated_entry = reschedule_single_order(
            token, entry, current_time
        )
        updated_entries.append(updated_entry)
    return current_time, updated_entries


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

        # capture the phase's current start time so set_phase_dates can
        # decide whether we need to update the start before the end.
        old_start_dt = None
        existing = (
            phase.get('starts_at') or
            phase.get('starting_date') or
            phase.get('start')
        )
        if existing:
            old_start_dt = _parse_dt(existing)

        total_mins = mins_per_u * quantity
        # ── KEY FIX: use add_working_minutes instead of raw timedelta ──
        # Raw timedelta would let phases run past 16:00 and overnight,
        # violating the 480 min/day constraint. This respects the shift.
        phase_end  = add_working_minutes(phase_start, total_mins)

        set_phase_dates(token, phase_id, phase_start, phase_end, old_start_dt)

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

    # ── Summary with capacity warning ────────────────────────────────
    on_time_count = sum(1 for e in schedule_log if e['on_time'])
    late_entries  = [e for e in schedule_log if not e['on_time']]

    print("\n" + "="*65)
    print("📋 FINAL SCHEDULE SUMMARY  (480 min/day · 08:00–16:00 shifts)")
    print("="*65)
    for e in schedule_log:
        status = "✅" if e['on_time'] else "❌ LATE"
        slack  = (e['deadline'] - e['po_end']).total_seconds() / 3600
        slack_str = f"+{slack:.0f}h" if e['on_time'] else f"{slack:.0f}h"
        print(f"  {e['so_id']} | {e['product_id']:<12} x{e['quantity']:<3} | "
              f"{e['po_start'].strftime('%b %d %H:%M')} → {e['po_end'].strftime('%b %d %H:%M')} | "
              f"Deadline: {e['deadline'].strftime('%b %d')} | {slack_str:>6} | {status}")

    print(f"\n  On time: {on_time_count}/{len(schedule_log)}")

    if late_entries:
        total_work = sum(
            sum(v * e['quantity'] for v in PHASE_DURATIONS[e['product_id']].values())
            for e in schedule_log
        )
        print(f"\n  ⚠️  CAPACITY NOTE:")
        print(f"     Total work required : {total_work:,} min = {total_work/MINUTES_PER_DAY:.1f} working days")
        print(f"     {len(late_entries)} order(s) are late under the 480 min/day constraint.")
        print(f"     EDF minimises maximum lateness — no reordering can fix a capacity shortfall.")
        print(f"     Late orders:")
        for e in late_entries:
            late_by = (e['po_end'] - e['deadline']).total_seconds() / 3600
            print(f"       {e['so_id']} | {e['product_id']} x{e['quantity']} | "
                  f"late by {late_by:.1f}h")

    return schedule_log