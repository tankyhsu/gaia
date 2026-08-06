#!/usr/bin/env python3
"""Minimal public-HTTP Gaia high-risk write and HumanGate approval."""

import json
import os
import sys
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE_URL = os.getenv("GAIA_BASE_URL", "http://127.0.0.1:8000")
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
    inspect_body = {
        "scenario_id": "controlled-task",
        "mode": "mock",
        "user": {"id": "demo-operator", "organization": "org-alpha", "roles": ["operator"]},
        "request": {"text": "inspect res-002"},
    }
    try:
        _, inspection = request("POST", "/v1/runs", inspect_body)
        if inspection["status"] != "succeeded" or not inspection.get("result"):
            raise RuntimeError(f"Could not inspect res-002: {inspection}")
        current_status = inspection["result"].get("status")
        transitions = {
            "active": "pause res-002 because maintenance window",
            "paused": "activate res-002 because service restored",
        }
        if current_status not in transitions:
            raise RuntimeError(f"Expected res-002 to be active or paused, got {current_status!r}")
        body = {
            "scenario_id": "controlled-task",
            "mode": "mock",
            "user": {
                "id": "demo-operator",
                "organization": "org-alpha",
                "roles": ["operator"],
            },
            "request": {"text": transitions[current_status]},
        }
        _, run = request("POST", "/v1/runs", body)
        if run["status"] != "waiting_human" or not run.get("pending_gate_id"):
            raise RuntimeError(f"Expected a pending HumanGate, got {run['status']}: {run}")
        gate_id = run["pending_gate_id"]
        _, gate = request("GET", f"/v1/human-gates/{gate_id}")
        _, completed = request(
            "POST",
            f"/v1/human-gates/{gate_id}/decision",
            {
                "decision": "approved",
                "decided_by": "demo-approver",
                "roles": ["approver"],
                "comment": "Demo approval.",
            },
        )
    except (HTTPError, RuntimeError) as error:
        message = error.read().decode() if isinstance(error, HTTPError) else str(error)
        print(message, file=sys.stderr)
        raise SystemExit(1) from None
    output = {
        "previous_status": current_status,
        "request_text": body["request"]["text"],
        "run_id": run["run_id"],
        "gate_id": gate["gate_id"],
        "gate_status": gate["status"],
        "final_status": completed["status"],
    }
    print(json.dumps(output, indent=2))
    if completed["status"] != "succeeded":
        raise SystemExit(f"Expected succeeded after approval, got {completed['status']}")


if __name__ == "__main__":
    main()
