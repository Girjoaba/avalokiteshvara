from typing import Dict, List

import requests
import json

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


def main():
    print("Authenticating with Arke API...")
    token = get_auth_token()
    print(token)

    print("Fetching active sales orders...")
    orders = fetch_active_orders(token)
    print(json.dumps(orders, indent=4))


if __name__ == "__main__":
    main()
