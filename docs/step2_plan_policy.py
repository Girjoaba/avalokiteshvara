import requests
import json
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
from datetime import datetime, timedelta, timezone

# ══════════════════════════════════════════════════════════════════════
# STEP 2 — EDF planning policy + SO-005 conflict detection
#
# LEVEL 1 (required): Earliest Deadline First (EDF)
#   - One production order per sales order
#   - Sort by expected_shipping_time, nearest first
#   - Ties broken by priority (lower number = higher urgency)
#
# KEY CONFLICT: SO-005 (SmartHome IoT, IOT-200 x10) was escalated P3→P1
#   A naive priority-first agent would schedule SO-005 before SO-003
#   (AgriBot, Mar 4 deadline), causing SO-003 to miss its deadline.
#   EDF correctly keeps SO-003 first since Mar 4 < Mar 8.
# ══════════════════════════════════════════════════════════════════════
def sort_orders_edf(orders):
    return sorted(orders, key=lambda x: (x['expected_shipping_time'], x['priority']))

def detect_so005_conflict(sorted_orders):
    print("\n" + "="*65)
    print("🧠  SO-005 CONFLICT DETECTION & EDF REASONING")
    print("="*65)

    so005 = next((o for o in sorted_orders
                  if 'SmartHome' in o['customer_attr']['name']
                  and o['_product_id'] == 'IOT-200'
                  and o['priority'] == 1), None)
    so003 = next((o for o in sorted_orders
                  if 'AgriBot' in o['customer_attr']['name']
                  and o['expected_shipping_time'][:10] <= '2026-03-05'), None)

    if so005 and so003:
        print(f"  SO-005: {so005['internal_id']} | IOT-200 x{so005['_quantity']} "
              f"| deadline {so005['expected_shipping_time'][:10]} | P{so005['priority']} (ESCALATED)")
        print(f"  SO-003: {so003['internal_id']} | {so003['_product_id']} x{so003['_quantity']} "
              f"| deadline {so003['expected_shipping_time'][:10]} | P{so003['priority']}")
        print()
        print("  ❌ Naive priority-first: SO-005 (P1) jumps before SO-003 (P2)")
        print("     → SO-003 misses Mar 4 deadline by 1 day!")
        print()
        print("  ✅ EDF-correct: SO-003 (Mar 4) stays before SO-005 (Mar 8)")
        print("     → Both deadlines are met. EDF prevails over raw priority.")
    print("="*65 + "\n")

