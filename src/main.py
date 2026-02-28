#!/usr/bin/env python3

"""
NovaBoard production scheduling entrypoint.

This script wires together the step modules:
  - step1_api_call.py          → auth + fetching + display helpers
  - step2_plan_policy.py → EDF planning policy + SO‑005 conflict detection
  - step3+4_create_order_schedule.py → create POs and schedule phases
  - step5a_gant_chart.py → Gantt chart + Telegram + approval loop
"""
import json
from real_time.advance_pipleine import move_pipeline, STATUS_BROKEN, STATUS_DONE, STATUS_IN_PROGRESS
from real_time.reschedule import (
    ask_user_skip_or_restart,
    reschedule_after_failure,
    save_failed_order,
)
from real_time.robot import RobotAvalokiteshvara
from step1_api_call import (
    fetch_sales_orders,
    login,
    display_orders
)
from step2_plan_policy import (
    detect_so005_conflict,
    sort_orders_edf,
)
from step3_4_create_order_schedule import (
    schedule_all_orders,
)

from step5a_gant_chart import (
    generate_gantt
)

from api import confirm_order

# ══════════════════════════════════════════════════════════════════════
# CREDENTIALS & CONFIG
# ══════════════════════════════════════════════════════════════════════
ARKE_BASE_URL = "https://hackathon46.arke.so"
ARKE_USERNAME = "arke"
ARKE_PASSWORD = "arke"
TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"  # from @BotFather
TELEGRAM_CHAT_ID = "YOUR_CHAT_ID"  # your personal chat ID
GEMINI_API_KEY = "YOUR_GEMINI_API_KEY"  # from aistudio.google.com


def main() -> None:
    # 1) Auth
    
    token = login()

    # 2) Read and display raw orders
    orders = fetch_sales_orders(token)
    display_orders(orders, " Raw Orders (unsorted)")

    # TODO: remove later
    # orders = orders[:1]

    # 3) Apply EDF planning policy
    sorted_orders = sort_orders_edf(orders)
    display_orders(sorted_orders, " EDF Sorted Schedule")
    detect_so005_conflict(sorted_orders)

    # 4) Create production orders and schedule phases
    schedule_log = schedule_all_orders(token, sorted_orders)

    # 5) Visual + messaging loop
    generate_gantt(schedule_log)

    # send_telegram(schedule_log)

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
        confirmed_order = confirm_order(token, order_id)

    # 7) Real-Time
    robot = RobotAvalokiteshvara()
    print("Starting real time...")
    errors = 0
    correct = 0
    
    i = 0
    while i < len(schedule_log):
        entry = schedule_log[i]
        order_id = entry["po_id"]
        print(f"Order id: {order_id}")
        print(f"Processing Order ID: {order_id}")

        status = STATUS_IN_PROGRESS
        while status == STATUS_IN_PROGRESS:
            status, failed_order = move_pipeline(token, order_id, robot)
            
            if status == STATUS_BROKEN:
                errors += 1
                # extract failed phase info if possible from failed_order
                failed_phase_name = "Unknown Phase"
                failed_phase_id = "unknown"
                
                # Try to parse failed_order to find the failing phase?
                # move_pipeline returns the full order object.
                # Usually the one with status='inprogress' or 'failed'?
                if isinstance(failed_order, dict):
                    phases = failed_order.get("phases", [])
                    # Maybe the last one or the one that is not done?
                    # For now, just use placeholder.
                    pass

                print(json.dumps(obj= failed_order, indent=4))
                
                save_failed_order(entry, i, failed_phase_id, failed_phase_name)
                
                choice = ask_user_skip_or_restart(entry, failed_phase_name)
                
                failed_info = {
                    "schedule_index": i,
                    "log_entry": entry
                }
                
                schedule_log = reschedule_after_failure(token, schedule_log, failed_info, choice)
                
                # Break inner loop to restart/skip
                break 
                
            if status == STATUS_DONE:
                correct += 1
        
        # If completed successfully, move to next.
        # If broken, we updated schedule_log and `i` now points to the correct next/retry item.
        if status == STATUS_DONE:
            i += 1
        
    print(f"Correct: {correct}")
    print(f"Errors: {errors}")


if __name__ == "__main__":
    main()