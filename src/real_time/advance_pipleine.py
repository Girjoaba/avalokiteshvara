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

def get_phase_name_from_phase(phase):
    """Extract phase name from phase object (various possible keys)."""
    return (
        phase.get('phase', {}).get('name') or
        phase.get('name') or
        phase.get('phase_name') or
        phase.get('production_phase', {}).get('name') or
        '?'
    )

def extract_failed_phase_info(order):
    """
    Extract the failed phase information from an order object.
    Returns (phase_id, phase_name).
    """
    if not isinstance(order, dict):
        return "unknown", "Unknown Phase"
    
    phases = order.get("phases", [])
    if not phases:
        return "unknown", "Unknown Phase"
    
    # Try to find the phase that was being executed (status = in_progress or running)
    for phase in phases:
        status = phase.get("status", "").lower()
        if status in ("in_progress", "running", "failed"):
            phase_id = phase.get('id') or phase.get('phase_id') or "unknown"
            phase_name = get_phase_name_from_phase(phase)
            return phase_id, phase_name
    
    # If no in_progress phase found, return the last non-done phase
    for phase in reversed(phases):
        status = phase.get("status", "").lower()
        if status != "done":
            phase_id = phase.get('id') or phase.get('phase_id') or "unknown"
            phase_name = get_phase_name_from_phase(phase)
            return phase_id, phase_name
    
    # Fallback to first phase if all are done
    phase = phases[0]
    phase_id = phase.get('id') or phase.get('phase_id') or "unknown"
    phase_name = get_phase_name_from_phase(phase)
    return phase_id, phase_name

def move_pipeline(token, order_id, robot) -> (bool, list):
    status = True
    failed_product = None

    order = fetch_production_order_by_id(token, order_id)
    print(json.dumps(obj= order, indent=4))
    phases = order.get("phases", [])
    ready_phase = next((p for p in phases if p.get("status") == "ready"), None)

    if not ready_phase:
        # Check if maybe all phases are done?
        if all(p.get("status") == "done" for p in phases) and phases:
             return STATUS_DONE, None
        
        # If order status is not 'in_progress' (e.g. 'draft', 'planned'), it might need confirmation?
        order_status = order.get("status")
        if order_status == "planned":
             # This happens if not confirmed.
             # We can try to confirm it here, or return a special status.
             # But let's just log and fail gracefully for now.
             print(f"⚠️  Order {order_id} has no ready phases. Status: {order_status}. Is it confirmed?")
             return STATUS_BROKEN, order
        
        print(f"⚠️  Order {order_id} has no ready phases. Phases: {json.dumps([p.get('status') for p in phases])}")
        return STATUS_BROKEN, order

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