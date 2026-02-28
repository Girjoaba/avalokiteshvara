import json

from api import (
    complete_order,
    complete_phase,
    confirm_order,
    create_production_order,
    fetch_production_order_by_id,
    get_auth_token,
    schedule_phase,
    start_phase,
)

from step3_4_create_order_schedule import schedule_all_orders
from real_time.robot import RobotAvalokiteshvara


STATUS_IN_PROGRESS = 0
STATUS_DONE = 1
STATUS_BROKEN = 2

def move_pipeline(token, order_id, robot) -> (bool, list):
    status = True
    failed_product = None

    order = fetch_production_order_by_id(token, order_id)
    print(json.dumps(obj= order, indent=4))
    phases = order.get("phases", [])
    ready_phase = next((p for p in phases if p.get("status") == "ready"), None)

    p_id = ready_phase["id"]
    is_last = p_id == phases[-1]["id"]
    start_phase(token, phase_id= p_id)

    # wait for RobotAvalokiteshvara
    if not robot.is_phase_complete():
        return STATUS_BROKEN, order

    if is_last:
        complete_order(token, order_id)
        return STATUS_DONE, None
    else:
        complete_phase(token, p_id)

    order = fetch_production_order_by_id(token, order_id)

    return STATUS_IN_PROGRESS, None


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

    confirmed_order = confirm_order(token, new_order_id)
    print(f"Confirmed order: {new_order_id}...")
    # print(json.dumps(confirmed_order, indent=4))

    robot = RobotAvalokiteshvara()

    # After confirm_phase
    order = confirmed_order

    while True:
        phases = order.get("phases", [])
        ready_phase = next((p for p in phases if p.get("status") == "ready"), None)
        if not ready_phase:
            break  # no more phases to run

        p_id = ready_phase["id"]
        is_last = p_id == phases[-1]["id"]
        start_phase(token, p_id)

        # wait for RobotAvalokiteshvara
        while not robot.is_phase_complete():
            pass

        if is_last:
            complete_order(token, new_order_id)
        else:
            complete_phase(token, p_id)

        order = fetch_production_order_by_id(token, new_order_id)

    order = fetch_production_order_by_id(token, new_order_id)
    print(json.dumps(order, indent=4))


if __name__ == "__main__":
    main()
