from typing import Dict, List

import requests

# Constants
BASE_URL = "https://hackathon46.arke.so"
USERNAME = "arke"
PASSWORD = "arke"


def get_auth_token() -> str:
    """Authenticates with the Arke API and returns the JWT token."""

    url = f"{BASE_URL}/api/login"
    payload = {"username": USERNAME, "password": PASSWORD}

    response = requests.post(url, json=payload)
    response.raise_for_status()

    return response.json().get("accessToken")


def fetch_active_orders(token: str) -> List[Dict]:
    """Fetches all accepted sales orders from the factory."""

    url = f"{BASE_URL}/api/sales/order?status=accepted"
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    data = response.json()
    return data if isinstance(data, list) else data.get("items", [])


def fetch_products(token: str) -> List[Dict]:
    """Fetches product catalog and BOM details."""

    url = f"{BASE_URL}/api/product/product"
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    data = response.json()
    return data if isinstance(data, list) else data.get("items", [])


def create_production_order(token: str, product_id: str, quantity) -> Dict:
    """Creates a new production order using a PUT request."""

    url = f"{BASE_URL}/api/product/production"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Data as specified in your request
    payload = {
        "product_id": product_id,
        "quantity": quantity,
        "starts_at": "2026-02-28T08:00:00Z",
        "ends_at": "2026-03-02T17:00:00Z",
    }

    response = requests.put(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()


def fetch_production_order_by_id(token, order_id):
    """Fetches a specific production order by its resource path."""

    # Ensure the /product/ prefix is there!
    url = f"{BASE_URL}/api/product/production/{order_id}"
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def schedule_phase(token: str, prod_id: str) -> Dict:
    """Transition an order to a confirmed state after the human-in-the-loop accepts."""

    url = f"{BASE_URL}/api/product/production/{prod_id}/_schedule"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(url, headers=headers)
    response.raise_for_status()
    return response.json()


def confirm_order(token: str, prod_id: str) -> Dict:
    """Transition an order to a confirmed state after the human-in-the-loop accepts."""

    url = f"{BASE_URL}/api/product/production/{prod_id}/_start"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(url, headers=headers)
    response.raise_for_status()
    return response.json()

def complete_order(token: str, prod_id: str) -> Dict:
    """Complete an."""

    url = f"{BASE_URL}/api/product/production/{prod_id}/_complete"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(url, headers=headers)
    response.raise_for_status()
    return response.json()


def start_phase(token: str, phase_id: str) -> Dict:
    """Transitions a ready phase to started."""

    url = f"{BASE_URL}/api/product/production-order-phase/{phase_id}/_start"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(url, headers=headers)
    response.raise_for_status()
    return response.json()


def complete_phase(token: str, phase_id: str) -> Dict:
    """Transitions a started phase to completed."""

    url = f"{BASE_URL}/api/product/production-order-phase/{phase_id}/_complete"
    headers = {"Authorization": f"Bearer {token}"}

    response = requests.post(url, headers=headers)
    response.raise_for_status()
    return response.json()


def main():
    pass


if __name__ == "__main__":
    main()