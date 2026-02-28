#!/usr/bin/env python3

"""
NovaBoard production scheduling entrypoint.

This script wires together the step modules:
  - step1_api_call.py          → auth + fetching + display helpers
  - step2_plan_policy.py → EDF planning policy + SO‑005 conflict detection
  - step3+4_create_order_schedule.py → create POs and schedule phases
  - step5a_gant_chart.py → Gantt chart + Telegram + approval loop
"""
import requests
import json
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
from datetime import datetime, timedelta, timezone

from real_time.advance_pipleine import move_pipeline, STATUS_BROKEN, STATUS_DONE, STATUS_IN_PROGRESS
from real_time.robot import RobotAvalokiteshvara
from real_time.reschedule import (
    save_failed_order,
    ask_user_skip_or_restart,
    reschedule_after_failure,
)
from step1_api_call import (
    login,
    fetch_sales_orders,
    display_orders,
)

# direct API helper used for order confirmation
from api import confirm_order

from step2_plan_policy import (
    sort_orders_edf,
    detect_so005_conflict,
)

from step3_4_create_order_schedule import (
    schedule_all_orders,
)

from step5a_gant_chart import (
    generate_gantt,
    send_telegram,
    wait_for_approval,
)


# ══════════════════════════════════════════════════════════════════════
# CREDENTIALS & CONFIG
# ══════════════════════════════════════════════════════════════════════
ARKE_BASE_URL    = "https://hackathon46.arke.so"
ARKE_USERNAME    = "arke"
ARKE_PASSWORD    = "arke"
TELEGRAM_TOKEN   = "YOUR_TELEGRAM_BOT_TOKEN"   # from @BotFather
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"              # your personal chat ID
GEMINI_API_KEY   = "YOUR_GEMINI_API_KEY"        # from aistudio.google.com

def main() -> None:
    # 1) Auth
    token = login()

    # 2) Read and display raw orders
    orders = fetch_sales_orders(token)
    display_orders(orders, " Raw Orders (unsorted)")

    # 3) Apply EDF planning policy
    sorted_orders = sort_orders_edf(orders)
    display_orders(sorted_orders, " EDF Sorted Schedule")
    detect_so005_conflict(sorted_orders)

    # 4) Create production orders and schedule phases
    schedule_log = schedule_all_orders(token, sorted_orders)

    # 5) Visual + messaging loop
    generate_gantt(schedule_log)
    send_telegram(schedule_log)

    # 6) Human-in-the-loop approval 
    # Uncomment to enable Telegram approval flow:
    # send_telegram(schedule_log)
    # approved = wait_for_approval()
    # if approved:
    #     print("\n Production confirmed. Ready for physical integration (Step 6).")
    # else:
    #     print("\n Schedule rejected — adjust and rerun.")

    # TODO: remove later
    # starts all orders
    for entry in schedule_log:
        order_id = entry["po_id"]
        try:
            confirmed_order = confirm_order(token, order_id)
        except requests.exceptions.HTTPError as exc:
            # Some environments forbid programmatic confirmation; this
            # loop is only for early testing and can be removed later.
            print(f"⚠️  could not confirm {order_id}: {exc}")
            confirmed_order = None

    # 7) Real-Time pipeline with reschedule on failure
    robot = RobotAvalokiteshvara()
    print("Starting real time...")
    errors = 0
    correct = 0
    idx = 0
    while idx < len(schedule_log):
        entry = schedule_log[idx]
        order_id = entry["po_id"]
        print(f"Order id: {order_id}")
        print(f"Processing Order ID: {order_id}")

        status = STATUS_IN_PROGRESS
        while status == STATUS_IN_PROGRESS:
            status, failed_info = move_pipeline(token, order_id, robot)
            if status == STATUS_BROKEN:
                errors += 1
                print(json.dumps(obj=failed_info, indent=4))
                failed_order_info = {
                    "schedule_index": idx,
                    "log_entry": entry,
                    "failed_phase_id": failed_info["failed_phase_id"],
                    "failed_phase_name": failed_info["failed_phase_name"],
                }
                save_failed_order(
                    log_entry=entry,
                    schedule_index=idx,
                    failed_phase_id=failed_info["failed_phase_id"],
                    failed_phase_name=failed_info["failed_phase_name"],
                )
                choice = ask_user_skip_or_restart(
                    entry, failed_info["failed_phase_name"]
                )
                schedule_log = reschedule_after_failure(
                    token, schedule_log, failed_order_info, choice
                )
                # Retry: same idx (restart = same order; skip = next order is now at idx)
                # We break here to reload the entry from the new schedule_log in the outer loop.
                break

            if status == STATUS_DONE:
                correct += 1
                idx += 1
                break

    print(f"Correct: {correct}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
