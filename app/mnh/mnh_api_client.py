import json

import requests

# Keep these fixed.
BASE_URL = "https://aziro.mynexthire.com"
CLIENT_ID = "1088"
CLIENT_SECRET = "ZjY1OTgyNTMtY2ZjMC00NmM1LTkxOWItZTE5YWNkZmZkMTExMTc2MjE2MTIzODk5Ng"
METHOD = "POST"

class MnhApiClient:
    @staticmethod
    def call(endpoint, body=None, method=METHOD):
        api_url = f"{BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"
        headers = {
            "client-id": CLIENT_ID,
            "client-secret": CLIENT_SECRET,
            "Content-Type": "application/json;charset=UTF-8",
        }
        return requests.request(
            method.upper(),
            api_url,
            headers=headers,
            json=body,
            timeout=30,
        )


try:
    endpoint = input("Enter endpoint (e.g. /ats/core-apis/v1/...): ").strip()
    body_input = input("Enter JSON body (or press Enter for none): ").strip()
    body = json.loads(body_input) if body_input else None

    if not endpoint:
        raise ValueError("Endpoint is required.")

    response = MnhApiClient.call(endpoint, body)
    print(f"Status: {response.status_code}")
    try:
        print(json.dumps(response.json(), indent=2))
    except Exception:
        print(response.text)
except Exception as e:
    print(f"Error: {e}")
