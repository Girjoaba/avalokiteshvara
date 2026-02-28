import json

from api import create_production_order, fetch_production_order_by_id, get_auth_token, schedule_phase, confirm_phase, start_phase, complete_phase


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
    print(json.dumps(specific_order, indent=4))

    #####################
    # 2. Schedule Order
    #####################

    print(f"Scheduled order: {new_order_id}...")
    scheduled_order = schedule_phase(token, new_order_id)
    print(json.dumps(scheduled_order, indent=4))

    #####################
    # 3. Confirm Order
    #####################

    print(f"Confirmed order: {new_order_id}...")
    confirmed_order = confirm_phase(token, new_order_id)
    print(json.dumps(confirmed_order, indent=4))


if __name__ == "__main__":
    main()
