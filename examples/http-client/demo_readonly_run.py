#!/usr/bin/env python3
"""Minimal public-HTTP Gaia read-only run."""

import json
import os
import sys
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE_URL = os.getenv("GAIA_BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("GAIA_API_KEY", "gaia-dev-key")


def request(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"X-Gaia-Api-Key": API_KEY}
    if data:
        headers["Content-Type"] = "application/json"
    if method == "POST":
        headers["Idempotency-Key"] = str(uuid.uuid4())
    req = Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    with urlopen(req, timeout=15) as response:
        return response.status, json.load(response)


def main():
    body = {
        "scenario_id": "controlled-task",
        "mode": "mock",
        "user": {"id": "demo-reader", "organization": "org-alpha", "roles": ["reader"]},
        "request": {"text": "inspect res-001"},
    }
    try:
        _, run = request("POST", "/v1/runs", body)
        _, events = request("GET", f"/v1/runs/{run['run_id']}/events")
    except HTTPError as error:
        print(error.read().decode(), file=sys.stderr)
        raise SystemExit(1) from None
    output = {"run_id": run["run_id"], "status": run["status"], "events": len(events)}
    print(json.dumps(output, indent=2))
    if run["status"] != "succeeded":
        raise SystemExit(f"Expected succeeded, got {run['status']}")


if __name__ == "__main__":
    main()
