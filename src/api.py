from typing import Dict, List

import requests

# Constants
BASE_URL = "https://hackathon3.arke.so/api"
USERNAME = "arke"
PASSWORD = "arke"


def get_auth_token() -> str:
    """Authenticates with the Arke API and returns the JWT token."""
    url = f"{BASE_URL}/login"
    payload = {"username": USERNAME, "password": PASSWORD}

    response = requests.post(url, json=payload)
    response.raise_for_status()

    return response.json().get("accessToken")


def fetch_active_orders(token: str) -> List[Dict]:
    """Fetches all accepted sales orders from the factory."""
    url = f"{BASE_URL}/sales/order?status=accepted"
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    data = response.json()
    return data if isinstance(data, list) else data.get("items", [])


def fetch_products(token: str) -> List[Dict]:
    """Fetches product catalog and BOM details."""
    url = f"{BASE_URL}/product/product"
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    data = response.json()
    return data if isinstance(data, list) else data.get("items", [])

def start_phase(token: str, phase_id: str) -> Dict:
    """Transitions a ready phase to started."""
    url = f"{BASE_URL}/product/production-order-phase/{phase_id}/_start"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(url, headers=headers)
    response.raise_for_status()
    return response.json()


def complete_phase(token: str, phase_id: str) -> Dict:
    """Transitions a started phase to completed."""
    url = f"{BASE_URL}/product/production-order-phase/{phase_id}/_complete"
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.post(url, headers=headers)
    response.raise_for_status()
    return response.json()


def fetch_production_orders(token: str) -> List[Dict]:
    """
    Fetches all production orders from the factory.
    Note: The endpoint is /product/production based on the API Cheat Sheet.
    """
    url = f"{BASE_URL}/product/production"
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    data = response.json()
    # Handle both list and paginated object responses
    return data if isinstance(data, list) else data.get("items", [])


def print_in_progress_orders(token: str):
    """Filters and displays production orders currently in progress."""
    all_productions = fetch_production_orders(token)

    # Filter for the 'in_progress' status
    in_progress = [p for p in all_productions if p.get("status") == "in_progress"]

    if not in_progress:
        print("\n--- No orders currently 'in_progress' ---")
        return

    print(f"\n--- Found {len(in_progress)} In-Progress Production Orders ---")
    print(f"{'ID':<15} | {'Product ID':<15} | {'Qty':<5} | {'Deadline'}")
    print("-" * 60)

    for order in in_progress:
        order_id = order.get("id", "N/A")
        product = order.get("product_id", "N/A")
        qty = order.get("quantity", 0)
        deadline = order.get("ends_at", "N/A")

        print(f"{order_id:<15} | {product:<15} | {qty:<5} | {deadline}")


def main():
    try:
        print("Authenticating...")
        token = get_auth_token()

        print_in_progress_orders(token)

    except requests.exceptions.HTTPError as e:
        print(f"API Error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    main()
