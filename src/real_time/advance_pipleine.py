import json

from api import (
    complete_phase,
    confirm_phase,
    create_production_order,
    fetch_production_order_by_id,
    get_auth_token,
    schedule_phase,
    start_phase,
)
from real_time.robot import RobotAvalokiteshvara


def main():
    token = get_auth_token()
    product_uuid = "9e7f1969-4e7f-47b0-b938-41a8fff2a2a4"

    #####################
    # 1. Create Order
    #####################

    new_order = create_production_order(token, product_uuid, 20)
    new_order_id = new_order.get("id")

    print(f"Created order: {new_order_id}...")
    specific_order = fetch_production_order_by_id(token, new_order_id)
    # print(json.dumps(specific_order, indent=4))

    #####################
    # 2. Schedule Order
    #####################

    print(f"Scheduled order: {new_order_id}...")
    scheduled_order = schedule_phase(token, new_order_id)
    # print(json.dumps(scheduled_order, indent=4))

    #####################
    # 3. Confirm Order
    #####################

    confirmed_order = confirm_phase(token, new_order_id)
    print(f"Confirmed order: {new_order_id}...")
    # print(json.dumps(confirmed_order, indent=4))

    robot = RobotAvalokiteshvara()

    # After confirm_phase
    order = confirmed_order

    i = 1
    while True:
        print(f"========= PHASE {i}")
        phases = order.get("phases", [])
        ready_phase = next((p for p in phases if p.get("status") == "ready"), None)
        if not ready_phase:
            break  # no more phases to run

        p_id = ready_phase["id"]
        started_phase = start_phase(token, p_id)
        # wait for RobotAvalokiteshvara
        while not robot.is_phase_complete():
            pass
        order = fetch_production_order_by_id(token, new_order_id)
        print(json.dumps(order, indent=4))
        completed_phase = complete_phase(token, p_id)

        order = fetch_production_order_by_id(token, new_order_id)
        i += 1

    # for i, phase in enumerate(phases):
    #     p_id = phase.get("id")
    #     p_name = phase.get("phase", {}).get("name", "Unknown")
    #     p_status = phase.get("status")
    #     print("======== PHASE:")
    #     print(json.dumps(phase, indent=4))

    #     if p_status == "ready":
    #         started_phase = start_phase(token, p_id)
    #         print("======== STARTED PHASE:")
    #         print(json.dumps(started_phase, indent=4))

    #         completed: bool = False
    #         while not completed:
    #             completed = robot.is_phase_complete()

    #         completed_phase = complete_phase(token, p_id)
    #         print("======== COMPLETED PHASE:")
    #         print(json.dumps(completed_phase, indent=4))
    #         print(f"============== Confirmed order: {new_order_id}...")
    #         print(json.dumps(confirmed_order, indent=4))
    # print(f"Phase {i}: {p_name} (ID: {p_id}) - Status: {p_status}")


if __name__ == "__main__":
    main()
