"""Black-box fault acceptance for the local production-like Docker stack."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "infra" / "production-like" / "compose.yaml"
API_URL = os.environ.get("GAIA_PROD_API_URL", "http://127.0.0.1:8088")
LANGFUSE_URL = os.environ.get("GAIA_PROD_LANGFUSE_URL", "http://127.0.0.1:3000")
API_KEY = os.environ.get("GAIA_API_KEY", "gaia-production-like-key")
LANGFUSE_PUBLIC_KEY = os.environ.get(
    "LANGFUSE_PUBLIC_KEY",
    "pk-lf-gaia-production-like",
)
LANGFUSE_SECRET_KEY = os.environ.get(
    "LANGFUSE_SECRET_KEY",
    "sk-lf-gaia-production-like",
)
HEADERS = {"X-Gaia-Api-Key": API_KEY}


class AcceptanceFailure(RuntimeError):
    pass


def compose(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("docker", "compose", "-f", str(COMPOSE_FILE), *args),
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def wait_for_http(
    client: httpx.Client,
    path: str,
    *,
    timeout_seconds: float = 60,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = client.get(path, headers=HEADERS)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
        except (httpx.HTTPError, ValueError) as error:
            last_error = error
        time.sleep(0.5)
    raise AcceptanceFailure(f"{path} did not become ready: {last_error}")


def wait_for_run(
    client: httpx.Client,
    run_id: str,
    expected: set[str],
    *,
    timeout_seconds: float = 60,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_status = "unknown"
    while time.monotonic() < deadline:
        response = client.get(f"/v1/runs/{run_id}", headers=HEADERS)
        if response.status_code == 200:
            payload = response.json()
            last_status = str(payload["status"])
            if last_status in expected:
                return payload
        time.sleep(0.4)
    raise AcceptanceFailure(
        f"run {run_id} stayed in {last_status}; expected {sorted(expected)}"
    )


def create_approval_run(client: httpx.Client) -> dict[str, Any]:
    response = client.post(
        "/v1/runs",
        headers={**HEADERS, "Idempotency-Key": f"prod-{uuid.uuid4()}"},
        json={
            "scenario_id": "controlled-task",
            "mode": "sandbox",
            "user": {
                "id": "production-like-operator",
                "organization": "org-alpha",
                "roles": ["operator"],
            },
            "request": {
                "text": "pause res-001 because production-like recovery test",
            },
        },
    )
    response.raise_for_status()
    return wait_for_run(client, response.json()["run_id"], {"waiting_human"})


def approve(client: httpx.Client, run: dict[str, Any]) -> dict[str, Any]:
    gate_id = run.get("pending_gate_id")
    if not gate_id:
        raise AcceptanceFailure("approval run did not expose pending_gate_id")
    response = client.post(
        f"/v1/human-gates/{gate_id}/decision",
        headers=HEADERS,
        json={
            "decision": "approved",
            "decided_by": "production-like-approver",
            "roles": ["approver"],
            "comment": "production-like recovery acceptance",
        },
    )
    response.raise_for_status()
    return wait_for_run(client, run["run_id"], {"succeeded"})


def wait_for_langfuse_trace(run_id: str, *, timeout_seconds: float = 90) -> None:
    token = base64.b64encode(
        f"{LANGFUSE_PUBLIC_KEY}:{LANGFUSE_SECRET_KEY}".encode()
    ).decode()
    headers = {"Authorization": f"Basic {token}"}
    deadline = time.monotonic() + timeout_seconds
    last_status = 0
    with httpx.Client(base_url=LANGFUSE_URL, timeout=10) as client:
        while time.monotonic() < deadline:
            response = client.get(
                "/api/public/traces",
                params={"sessionId": run_id, "limit": 10},
                headers=headers,
            )
            last_status = response.status_code
            if response.status_code == 200:
                data = response.json().get("data", [])
                if any(item.get("sessionId") == run_id for item in data):
                    return
            time.sleep(1)
    raise AcceptanceFailure(
        f"Langfuse did not expose a trace for {run_id}; last HTTP {last_status}"
    )


def running_services() -> set[str]:
    result = compose("ps", "--services", "--status", "running")
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def main() -> int:
    required = {
        "api-a",
        "api-b",
        "worker-a",
        "worker-b",
        "gateway",
        "temporal",
        "gaia-postgres",
        "langfuse-web",
        "langfuse-worker",
        "console",
    }
    missing = required - running_services()
    if missing:
        raise AcceptanceFailure(
            f"production-like services are not running: {sorted(missing)}; "
            "run `make prod-up` first"
        )

    report: dict[str, object] = {}
    with httpx.Client(base_url=API_URL, timeout=30) as client:
        wait_for_http(client, "/health/ready")

        run = create_approval_run(client)
        report["waiting_before_worker_restart"] = run["status"]

        compose("stop", "worker-a", "worker-b")
        compose("start", "worker-b")
        run = wait_for_run(client, run["run_id"], {"waiting_human"})
        completed = approve(client, run)
        report["worker_restart_status"] = completed["status"]
        compose("start", "worker-a")

        compose("stop", "api-a")
        wait_for_http(client, "/health/live")
        failover = wait_for_run(client, completed["run_id"], {"succeeded"})
        report["api_failover_status"] = failover["status"]
        compose("start", "api-a")

        compose("restart", "temporal")
        recovered = wait_for_run(
            client,
            completed["run_id"],
            {"succeeded"},
            timeout_seconds=90,
        )
        report["temporal_restart_status"] = recovered["status"]

        page = client.get("/v1/runs", headers=HEADERS)
        page.raise_for_status()
        run_ids = {item["run_id"] for item in page.json()["items"]}
        if completed["run_id"] not in run_ids:
            raise AcceptanceFailure("Gaia audit projection did not list the completed run")
        report["audit_projection"] = "listed"

    wait_for_langfuse_trace(completed["run_id"])
    report["langfuse_trace"] = "visible"
    report["run_id"] = completed["run_id"]
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
