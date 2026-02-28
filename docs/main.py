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

from step1_api_call import (
    login,
    fetch_sales_orders,
    display_orders,
)

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



if __name__ == "__main__":
    main()

