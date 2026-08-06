"""End-to-end smoke check for a running Gaia deployment."""

from __future__ import annotations

import json
import os
import urllib.request
from uuid import uuid4

BASE_URL = os.getenv("GAIA_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
API_KEY = os.getenv("GAIA_API_KEY", "gaia-dev-key")
HEADERS = {"X-Gaia-Api-Key": API_KEY, "Content-Type": "application/json"}


def call(path: str, *, method: str = "GET", body: dict[str, object] | None = None) -> object:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE_URL + path, data=data, method=method, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


health = call("/health/ready")
assert isinstance(health, dict) and health["status"] == "ok"

create_headers = {**HEADERS, "Idempotency-Key": str(uuid4())}
request = urllib.request.Request(
    BASE_URL + "/v1/runs",
    data=json.dumps(
        {
            "scenario_id": "controlled-task",
            "mode": "mock",
            "user": {"id": "smoke-reader", "organization": "org-alpha", "roles": ["reader"]},
            "request": {"text": "inspect res-001"},
        }
    ).encode(),
    method="POST",
    headers=create_headers,
)
with urllib.request.urlopen(request, timeout=30) as response:
    run = json.load(response)
assert run["status"] == "succeeded"
events = call(f"/v1/runs/{run['run_id']}/events")
assert isinstance(events, list) and events[-1]["step"] == "finalize"
bundle = call(f"/v1/diagnostics/runs/{run['run_id']}/bundle")
assert isinstance(bundle, dict) and bundle["redaction"]["request_text"] == "omitted"

replay = call("/v1/evals/replays", method="POST", body={"all": True})
assert isinstance(replay, dict) and replay["passed"] == 10 and replay["failed"] == 0
print(f"Gaia smoke passed: run={run['run_id']} replay={replay['replay_id']} 10/10")
