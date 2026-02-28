import requests
from datetime import datetime, timedelta, timezone

# ══════════════════════════════════════════════════════════════════════
# CREDENTIALS & CONFIG
# ══════════════════════════════════════════════════════════════════════
ARKE_BASE_URL    = "https://hackathon46.arke.so"
ARKE_USERNAME    = "arke"
ARKE_PASSWORD    = "arke"
TELEGRAM_TOKEN   = "YOUR_TELEGRAM_BOT_TOKEN"   # from @BotFather
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"              # your personal chat ID
GEMINI_API_KEY   = "YOUR_GEMINI_API_KEY"        # from aistudio.google.com

# ══════════════════════════════════════════════════════════════════════
# FACTORY DATA — BOM phase durations in minutes per unit
# Source: NovaBoard hackathon factory spec
# Formula: total_minutes = duration_per_unit × quantity
# One line, 480 min/day, 7 days/week, sequential batch processing
# ══════════════════════════════════════════════════════════════════════
# Bill of Materials — it tells the scheduler exactly how many minutes each product needs per phase, per unit. 
PHASE_DURATIONS = {
    # Product ID    : {phase: minutes_per_unit}
    "PCB-IND-100": {"SMT": 30, "Reflow": 15, "THT": 45, "AOI": 12, "Test": 30, "Coating": 9,  "Pack": 6},
    "MED-300":     {"SMT": 45, "Reflow": 30, "THT": 60, "AOI": 30, "Test": 90, "Coating": 15, "Pack": 9},
    "IOT-200":     {"SMT": 18, "Reflow": 12, "THT": 0,  "AOI": 9,  "Test": 18, "Coating": 0,  "Pack": 6},  # no THT/Coating
    "AGR-400":     {"SMT": 30, "Reflow": 15, "THT": 30, "AOI": 12, "Test": 45, "Coating": 12, "Pack": 0},  # no Pack
    "PCB-PWR-500": {"SMT": 24, "Reflow": 12, "THT": 0,  "AOI": 9,  "Test": 24, "Coating": 0,  "Pack": 6},  # no THT/Coating
}

# Fixed phase order for all products (BOM sequence)
PHASES_ORDER    = ["SMT", "Reflow", "THT", "AOI", "Test", "Coating", "Pack"]
MINUTES_PER_DAY = 480

# BOM uses human-readable codes like "PCB-IND-100", but Arke's API only accepts UUIDs so we need to map them.
# Global product map: internal_id (e.g. "PCB-IND-100") → Arke UUID
# Populated by build_product_map() before any PO creation
PRODUCT_ID_MAP  = {}

# Hackathon scenario start time (Feb 28 2026, 08:00 UTC)
# This is the moment the factory line becomes available, and every subsequent timestamp is calculated relative to it.
TODAY = datetime(2026, 2, 28, 8, 0, 0, tzinfo=timezone.utc)

# Per-phase colors for Gantt (replaces per-priority coloring)
# Visual lookup tables for the Gantt chart — which color to draw for each phase or priority leve
PHASE_COLORS = {
    'SMT':     '#4fc3f7',  # light blue
    'Reflow':  '#81c784',  # green
    'THT':     '#ffb74d',  # amber
    'AOI':     '#ba68c8',  # purple
    'Test':    '#f06292',  # pink
    'Coating': '#4db6ac',  # teal
    'Pack':    '#aed581',  # lime
}

# Priority colors kept for legend / summary use
PRIORITY_COLORS = {
    1: '#e74c3c',
    2: '#e67e22',
    3: '#3498db',
    4: '#95a5a6',
    5: '#bdc3c7',
}


# ══════════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════════
# This function logs in to the Arke API and returns the access token.
def login():
    r = requests.post(f"{ARKE_BASE_URL}/api/login", json={
        "username": ARKE_USERNAME,
        "password": ARKE_PASSWORD
    })
    r.raise_for_status()
    print("✅ Logged in")
    return r.json()["accessToken"]

# This function returns the headers for the Arke API requests.
def get_headers(token):
    return {"Authorization": f"Bearer {token}"}


# ══════════════════════════════════════════════════════════════════════
# STEP 1 — Read open orders
# ══════════════════════════════════════════════════════════════════════
# This function fetches the sales orders from the Arke API.
# First pass hits /api/sales/order/_active. This returns all 12 open orders quickly, but each order object only has basic fields
# Second pass loops through every order and hits /api/sales/order/{id} individually to get the detail. 
def fetch_sales_orders(token):
    r = requests.get(f"{ARKE_BASE_URL}/api/sales/order/_active", headers=get_headers(token))
    if r.ok and len(r.json()) >= 12:
        orders = r.json()
    else:
        r = requests.get(
            f"{ARKE_BASE_URL}/api/sales/order",
            params={"status": "accepted"},
            headers=get_headers(token)
        )
        r.raise_for_status()
        orders = r.json()

    print(f"📦 Fetching details for {len(orders)} orders...")
    for o in orders:
        detail   = requests.get(
            f"{ARKE_BASE_URL}/api/sales/order/{o['id']}",
            headers=get_headers(token)
        ).json()
        products = detail.get('products', [])
        o['_product_id']   = products[0]['extra_id'] if products else 'unknown'
        o['_product_name'] = products[0]['name']     if products else 'unknown'
        o['_quantity']     = products[0]['quantity'] if products else 0

    print(f"✅ Fetched {len(orders)} orders")
    return orders

# This function displays the sales orders in a table format.
# It also highlights the SO-005 conflict and the EDF reasoning.
# The one special case is it checks for SO-2026/0017 specifically and appends an ESCALATED flag.
# That's the SmartHome IoT order whose priority was bumped from P3 to P1.
def display_orders(orders, title="📋 Sales Orders"):
    print(f"\n{title}")
    print(f"{'#':<4} {'SO ID':<15} {'Customer':<22} {'Product':<15} {'Qty':<5} {'Deadline':<12} {'Priority'}")
    print("-" * 85)
    for i, o in enumerate(orders):
        customer = o['customer_attr']['name']
        flag = " ⚠️ ESCALATED" if o['internal_id'] == 'SO-2026/0017' else ""
        print(
            f"{i+1:<4} {o['internal_id']:<15} {customer:<22} "
            f"{o['_product_id']:<15} {o['_quantity']:<5} "
            f"{o['expected_shipping_time'][:10]:<12} P{o['priority']}{flag}"
        )

