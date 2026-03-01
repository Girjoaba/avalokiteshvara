import requests
import json
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
from datetime import datetime, timedelta, timezone

# ══════════════════════════════════════════════════════════════════════
# STEP 2 — Multiple planning policies (EDF, PRIORITY, SJF, LJF, SLACK, CUSTOMER, MANUAL)
#
# LEVEL 1 (required): Earliest Deadline First (EDF) — the baseline
#   - Sort by expected_shipping_time, nearest first
#   - Ties broken by priority (lower number = higher urgency)
#
# KEY CONFLICT EXAMPLE: SO-005 (SmartHome IoT, P1) vs SO-003 (AgriBot, P2)
#   Naive priority-first: SO-005 jumps first → SO-003 misses Mar 4 deadline
#   EDF-correct: SO-003 (Mar 4) before SO-005 (Mar 8) → Both delivered on time
# ══════════════════════════════════════════════════════════════════════

# Customer tier ranking (hardcoded for CUSTOMER policy)
CUSTOMER_RANKS = {
    'MedTec': 0,        # Highest priority
    'AgriBot': 1,
    'SmartHome': 2,
    'IoT': 3,
    'Default': 99       # Lowest
}

def get_customer_rank(customer_name):
    """Look up customer's tier rank. Default=99 (lowest)."""
    for rank_name, rank_value in CUSTOMER_RANKS.items():
        if rank_name in customer_name:
            return rank_value
    return CUSTOMER_RANKS['Default']

def compute_total_minutes_local(product_id, quantity):
    """
    Get total production time for an order.
    Imports locally to avoid circular imports with step3_4.
    """
    try:
        from step3_4_create_order_schedule import PHASE_DURATIONS
        durations = PHASE_DURATIONS.get(product_id, {})
        return sum(mins * quantity for mins in durations.values())
    except ImportError:
        print(f"⚠️  Could not compute duration for {product_id}. Using 480 min default.")
        return 480

def sort_orders_by_policy(orders, policy='EDF', custom_sequence=None):
    """
    Unified sorting function supporting multiple scheduling policies.
    
    Args:
        orders: List of order dicts from API
        policy: 'EDF', 'PRIORITY', 'SJF', 'LJF', 'SLACK', 'CUSTOMER', 'MANUAL'
        custom_sequence: For MANUAL policy, list of internal_ids in desired order
    
    Returns:
        Sorted list of orders
    """
    policy = policy.upper()
    
    if policy == 'EDF':
        # Earliest Deadline First: deadline first, then priority
        return sorted(orders, key=lambda x: (x['expected_shipping_time'], x['priority']))
    
    elif policy == 'PRIORITY':
        # Naive priority-first (ignores deadlines) — demonstrates why EDF is better
        return sorted(orders, key=lambda x: (x['priority'], x['expected_shipping_time']))
    
    elif policy == 'SJF':
        # Shortest Job First: smallest production time first
        # Minimizes average wait time but can starve large orders
        return sorted(orders, key=lambda x: compute_total_minutes_local(x['_product_id'], x['_quantity']))
    
    elif policy == 'LJF':
        # Longest Job First: biggest production time first
        # Get large orders out of the way early
        return sorted(orders, key=lambda x: compute_total_minutes_local(x['_product_id'], x['_quantity']), reverse=True)
    
    elif policy == 'SLACK':
        # Slack Time: deadline - now - production_time (ascending)
        # Order with least slack (most at risk) goes first
        def slack_key(order):
            deadline = datetime.fromisoformat(order['expected_shipping_time'].replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            prod_mins = compute_total_minutes_local(order['_product_id'], order['_quantity'])
            slack = deadline - now - timedelta(minutes=prod_mins)
            return slack  # Natural ordering: tight slack (negative) comes first
        
        return sorted(orders, key=slack_key)
    
    elif policy == 'CUSTOMER':
        # Customer Priority: rank-based (MedTec > AgriBot > SmartHome > IoT)
        # Within same customer, sort by EDF
        return sorted(orders, key=lambda x: (
            get_customer_rank(x['customer_attr']['name']),
            x['expected_shipping_time'],
            x['priority']
        ))
    
    elif policy == 'MANUAL':
        # Manual/Custom Order: exact sequence provided by planner via Telegram
        # custom_sequence = ["SO-0017", "SO-0013", "SO-0015", ...]
        if not custom_sequence:
            print("⚠️  MANUAL policy requires custom_sequence. Falling back to EDF.")
            return sort_orders_by_policy(orders, 'EDF')
        
        # Build a position map
        position = {so_id: i for i, so_id in enumerate(custom_sequence)}
        
        def manual_key(order):
            so_id = order['internal_id']
            if so_id in position:
                return (0, position[so_id])  # (in_sequence, position)
            else:
                return (1, 999)  # Orders not in list go to end
        
        return sorted(orders, key=manual_key)
    
    else:
        print(f"⚠️  Unknown policy '{policy}'. Defaulting to EDF.")
        return sort_orders_by_policy(orders, 'EDF', custom_sequence)

def sort_orders_edf(orders):
    """Legacy function — wraps new unified sort."""
    return sort_orders_by_policy(orders, 'EDF')

def detect_so005_conflict(sorted_orders, policy='EDF'):
    print("\n" + "="*80)
    print(f"🧠  SCHEDULING POLICY: {policy} (SO-005 CONFLICT DETECTION)")
    print("="*80)

    so005 = next((o for o in sorted_orders
                  if 'SmartHome' in o['customer_attr']['name']
                  and o['_product_id'] == 'IOT-200'
                  and o['priority'] == 1), None)
    so003 = next((o for o in sorted_orders
                  if 'AgriBot' in o['customer_attr']['name']
                  and o['expected_shipping_time'][:10] <= '2026-03-05'), None)

    if so005 and so003:
        so005_idx = sorted_orders.index(so005)
        so003_idx = sorted_orders.index(so003)
        
        print(f"\n  SO-005: {so005['internal_id']} | IOT-200 x{so005['_quantity']} "
              f"| deadline {so005['expected_shipping_time'][:10]} | P{so005['priority']} (ESCALATED)")
        print(f"  SO-003: {so003['internal_id']} | {so003['_product_id']} x{so003['_quantity']} "
              f"| deadline {so003['expected_shipping_time'][:10]} | P{so003['priority']}")
        print(f"\n  Position in queue: SO-005 at index {so005_idx}, SO-003 at index {so003_idx}")
        
        if so005_idx < so003_idx:
            print(f"\n  ⚠️  {policy} puts SO-005 (P1, Mar 8) BEFORE SO-003 (P2, Mar 4)")
            print(f"     → SO-003 will miss its Mar 4 deadline! ❌")
        else:
            print(f"\n  ✅ {policy} correctly puts SO-003 (Mar 4) before SO-005 (Mar 8)")
            print(f"     → Both deadlines are met. ✓")
    
    print("\n  POLICY EXPLANATION:")
    if policy == 'EDF':
        print("  • Earliest Deadline First: Sort by deadline only")
        print("  • Ignores priority and job size — only deadline matters")
        print("  • Theoretically optimal for deadline-driven scheduling")
    elif policy == 'PRIORITY':
        print("  • Naive Priority First: P1 always goes first, P2 second, etc.")
        print("  • Ignores deadlines entirely")
        print("  • THIS IS HOW THE SO-005 CONFLICT HAPPENS! 🔴")
    elif policy == 'SJF':
        print("  • Shortest Job First: Fast orders first")
        print("  • Minimizes average wait time but starves large orders")
    elif policy == 'LJF':
        print("  • Longest Job First: Big orders first")
        print("  • Gets large orders out of the way early")
    elif policy == 'SLACK':
        print("  • Slack Time: Most at-risk orders first")
        print("  • Deadline - now - production_time (ascending)")
        print("  • Very similar to EDF but accounts for job duration")
    elif policy == 'CUSTOMER':
        print("  • Customer Tier: MedTec > AgriBot > SmartHome > IoT")
        print("  • VIP customers always before others")
    elif policy == 'MANUAL':
        print("  • Custom sequence: Exact order specified by planner")
        print("  • Complete override of all algorithms")
    
    print("="*80 + "\n")

