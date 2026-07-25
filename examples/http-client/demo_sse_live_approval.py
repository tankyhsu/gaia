#!/usr/bin/env python3
"""Verify that one SSE connection receives events after a HumanGate approval."""

import json
import os
import sys
import threading
import time
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


def create_waiting_run():
    inspect_body = {
        "scenario_id": "controlled-task",
        "mode": "mock",
        "user": {"id": "sse-operator", "organization": "org-alpha", "roles": ["operator"]},
        "request": {"text": "inspect res-002"},
    }
    _, inspection = request("POST", "/v1/runs", inspect_body)
    current_status = inspection.get("result", {}).get("status")
    transitions = {
        "active": "pause res-002 because maintenance window",
        "paused": "activate res-002 because service restored",
    }
    if inspection["status"] != "succeeded" or current_status not in transitions:
        raise RuntimeError(f"Could not inspect a transition for res-002: {inspection}")
    body = {
        "scenario_id": "controlled-task",
        "mode": "mock",
        "user": {"id": "sse-operator", "organization": "org-alpha", "roles": ["operator"]},
        "request": {"text": transitions[current_status]},
    }
    _, run = request("POST", "/v1/runs", body)
    if run["status"] != "waiting_human" or not run.get("pending_gate_id"):
        raise RuntimeError(f"Expected a pending HumanGate, got {run}")
    return run, body["request"]["text"]


def collect_sse(run_id, opened, closed, events, error):
    stream = Request(
        f"{BASE_URL}/v1/runs/{run_id}/events/stream",
        headers={"X-Gaia-Api-Key": API_KEY, "Accept": "text/event-stream"},
    )
    frame = {}
    try:
        with urlopen(stream, timeout=12) as response:
            opened.set()
            for raw_line in response:
                line = raw_line.decode().rstrip("\r\n")
                if not line:
                    if frame:
                        events.append(frame)
                        frame = {}
                    continue
                field, _, value = line.partition(":")
                if field in {"id", "event", "data"}:
                    frame[field] = value.lstrip()
            if frame:
                events.append(frame)
    except Exception as exc:  # noqa: BLE001 - report a network failure through the demo result.
        error.append(str(exc))
    finally:
        closed.set()


def is_terminal_event(frame):
    if frame.get("event") != "run.event" or "data" not in frame:
        return False
    try:
        data = json.loads(frame["data"])
    except json.JSONDecodeError:
        return False
    return data.get("step") == "finalize" and data.get("status") == "succeeded"


def main():
    try:
        run, request_text = create_waiting_run()
        opened = threading.Event()
        closed = threading.Event()
        events = []
        stream_error = []
        worker = threading.Thread(
            target=collect_sse,
            args=(run["run_id"], opened, closed, events, stream_error),
            daemon=True,
        )
        worker.start()
        if not opened.wait(timeout=2):
            raise RuntimeError("SSE connection did not open")
        time.sleep(0.6)
        before_approval = len(events)
        _, completed = request(
            "POST",
            f"/v1/human-gates/{run['pending_gate_id']}/decision",
            {
                "decision": "approved",
                "decided_by": "sse-approver",
                "roles": ["approver"],
                "comment": "Approve while the original SSE connection remains open.",
            },
        )
        worker.join(timeout=10)
        if worker.is_alive() or not closed.is_set():
            raise RuntimeError("SSE connection did not close after the terminal run event")
        if stream_error:
            raise RuntimeError(f"SSE stream error: {stream_error[0]}")
        later_events = events[before_approval:]
        if not any(frame.get("event") == "run.event" for frame in later_events):
            raise RuntimeError("The open SSE connection did not receive a later run.event")
        if not any(is_terminal_event(frame) for frame in later_events):
            raise RuntimeError("The open SSE connection did not receive finalize/succeeded")
    except (HTTPError, RuntimeError) as exc:
        message = exc.read().decode() if isinstance(exc, HTTPError) else str(exc)
        print(message, file=sys.stderr)
        raise SystemExit(1) from None
    output = {
        "run_id": run["run_id"],
        "request_text": request_text,
        "wait_before_approval_seconds": 0.6,
        "events_before_approval": before_approval,
        "events_after_approval": len(later_events),
        "final_status": completed["status"],
        "stream_closed": closed.is_set(),
    }
    print(json.dumps(output, indent=2))
    if completed["status"] != "succeeded":
        raise SystemExit(f"Expected succeeded after approval, got {completed['status']}")


if __name__ == "__main__":
    main()
