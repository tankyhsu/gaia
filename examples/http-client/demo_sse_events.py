#!/usr/bin/env python3
"""Minimal public-HTTP integration: create a run then consume its SSE event stream."""

import json
import os
import sys
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE_URL = os.getenv("GAIA_BASE_URL", "http://127.0.0.1:8000")
API_KEY = os.getenv("GAIA_API_KEY", "gaia-dev-key")


def main():
    body = {
        "scenario_id": "controlled-task",
        "mode": "mock",
        "user": {"id": "demo-sse", "organization": "org-alpha", "roles": ["reader"]},
        "request": {"text": "inspect res-001"},
    }
    create = Request(
        f"{BASE_URL}/v1/runs",
        data=json.dumps(body).encode(),
        headers={
            "X-Gaia-Api-Key": API_KEY,
            "Content-Type": "application/json",
            "Idempotency-Key": str(uuid.uuid4()),
        },
        method="POST",
    )
    try:
        with urlopen(create, timeout=15) as response:
            run = json.load(response)
        stream = Request(
            f"{BASE_URL}/v1/runs/{run['run_id']}/events/stream",
            headers={"X-Gaia-Api-Key": API_KEY, "Accept": "text/event-stream"},
        )
        with urlopen(stream, timeout=15) as response:
            lines = [line.decode().strip() for line in response]
            event_ids = [line[4:].strip() for line in lines if line.startswith("id:")]
            event_names = [line[6:].strip() for line in lines if line.startswith("event:")]
    except HTTPError as error:
        print(error.read().decode(), file=sys.stderr)
        raise SystemExit(1) from None
    output = {
        "run_id": run["run_id"],
        "event_ids": event_ids,
        "event_names": event_names,
        "event_count": len(event_ids),
    }
    print(json.dumps(output, indent=2))
    if not event_ids:
        raise SystemExit("SSE response did not include any event IDs")
    if len(event_names) != len(event_ids) or set(event_names) != {"run.event"}:
        raise SystemExit("SSE response did not use the public run.event event name")


if __name__ == "__main__":
    main()
