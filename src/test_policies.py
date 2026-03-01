#!/usr/bin/env python3
"""
Quick Reference: Scheduling Policies in NovaBoard

This file demonstrates how each policy would sort the sample orders.
"""

# Example orders (simplified)
SAMPLE_ORDERS = [
    {
        'internal_id': 'SO-0003',
        'customer_attr': {'name': 'AgriBot'},
        '_product_id': 'AGR-100',
        '_quantity': 5,
        'priority': 2,
        'expected_shipping_time': '2026-03-04T16:00:00Z'  # Mar 4
    },
    {
        'internal_id': 'SO-0005',
        'customer_attr': {'name': 'SmartHome'},
        '_product_id': 'IOT-200',
        '_quantity': 10,
        'priority': 1,  # ESCALATED
        'expected_shipping_time': '2026-03-08T16:00:00Z'  # Mar 8
    },
    {
        'internal_id': 'SO-0001',
        'customer_attr': {'name': 'MedTec'},
        '_product_id': 'MED-50',
        '_quantity': 2,
        'priority': 3,
        'expected_shipping_time': '2026-03-10T16:00:00Z'  # Mar 10
    }
]

# ══════════════════════════════════════════════════════════════════════
# EXPECTED SORT ORDERS BY POLICY
# ══════════════════════════════════════════════════════════════════════

EXPECTED_RESULTS = {
    'EDF': [
        'SO-0003 (deadline Mar 4)',
        'SO-0005 (deadline Mar 8)',
        'SO-0001 (deadline Mar 10)'
    ],
    # ↑ CORRECT: Earliest deadline first. SO-003 doesn't miss Mar 4.
    
    'PRIORITY': [
        'SO-0005 (P1)',
        'SO-0003 (P2)',
        'SO-0001 (P3)'
    ],
    # ↑ WRONG: P1 jumps first. SO-003 misses Mar 4! This is the SO-005 conflict.
    
    'SJF': [
        'SO-0001 (MED-50 x2: ~120 min)',
        'SO-0003 (AGR-100 x5: ~600 min)',
        'SO-0005 (IOT-200 x10: ~1200 min)'
    ],
    # ↑ Depends on actual PHASE_DURATIONS, but generally: smallest job first
    # ↑ Good for minimizing avg wait, but big orders starve
    
    'LJF': [
        'SO-0005 (IOT-200 x10: largest)',
        'SO-0003 (AGR-100 x5: medium)',
        'SO-0001 (MED-50 x2: smallest)'
    ],
    # ↑ Opposite of SJF: biggest jobs first
    # ↑ Prevents big orders from blocking everything late in day
    
    'SLACK': [
        'SO-0003 (least slack - tight deadline + long job)',
        'SO-0005 (more slack despite P1)',
        'SO-0001 (most slack)'
    ],
    # ↑ Very similar to EDF but accounts for job duration
    # ↑ Correctly identifies SO-003 as most at-risk
    
    'CUSTOMER': [
        'SO-0001 (MedTec - rank 0, highest VIP)',
        'SO-0003 (AgriBot - rank 1)',
        'SO-0005 (SmartHome - rank 2)'
    ],
    # ↑ Purely by customer tier, ignoring deadlines/priority
    # ↑ Useful for SLA contracts (e.g., MedTec always first 48h)
}

# ══════════════════════════════════════════════════════════════════════
# USAGE EXAMPLES
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    from step2_plan_policy import sort_orders_by_policy, detect_so005_conflict
    
    # TEST 1: EDF (default)
    print("=" * 70)
    print("TEST 1: EDF (Earliest Deadline First)")
    print("=" * 70)
    sorted_orders = sort_orders_by_policy(SAMPLE_ORDERS, policy='EDF')
    for i, order in enumerate(sorted_orders, 1):
        print(f"{i}. {order['internal_id']} | {order['customer_attr']['name']} "
              f"| deadline {order['expected_shipping_time'][:10]}")
    detect_so005_conflict(sorted_orders, 'EDF')
    
    # TEST 2: PRIORITY (demonstrating the problem)
    print("\n" + "=" * 70)
    print("TEST 2: PRIORITY (Naive - demonstrates SO-005 conflict)")
    print("=" * 70)
    sorted_orders = sort_orders_by_policy(SAMPLE_ORDERS, policy='PRIORITY')
    for i, order in enumerate(sorted_orders, 1):
        print(f"{i}. {order['internal_id']} | P{order['priority']} "
              f"| deadline {order['expected_shipping_time'][:10]}")
    detect_so005_conflict(sorted_orders, 'PRIORITY')
    
    # TEST 3: SJF
    print("\n" + "=" * 70)
    print("TEST 3: SJF (Shortest Job First)")
    print("=" * 70)
    sorted_orders = sort_orders_by_policy(SAMPLE_ORDERS, policy='SJF')
    for i, order in enumerate(sorted_orders, 1):
        print(f"{i}. {order['internal_id']} | {order['_product_id']} "
              f"x{order['_quantity']}")
    detect_so005_conflict(sorted_orders, 'SJF')
    
    # TEST 4: CUSTOMER
    print("\n" + "=" * 70)
    print("TEST 4: CUSTOMER (VIP Tier)")
    print("=" * 70)
    sorted_orders = sort_orders_by_policy(SAMPLE_ORDERS, policy='CUSTOMER')
    for i, order in enumerate(sorted_orders, 1):
        print(f"{i}. {order['internal_id']} | {order['customer_attr']['name']}")
    detect_so005_conflict(sorted_orders, 'CUSTOMER')
    
    print("\n✅ All policy tests complete!")
    print("\nTo integrate into main.py:")
    print("  1. Call wait_for_approval() to get (approved, policy_override)")
    print("  2. If policy_override: sort_orders_by_policy(orders, policy_override)")
    print("  3. Re-schedule and send updated Gantt via Telegram")
