# Gaia public HTTP client demos

These standalone Python 3 demos use only Gaia's public HTTP API and the standard library. They assume a Gaia service at `http://127.0.0.1:8000` and use `gaia-dev-key` by default. Override either with `GAIA_BASE_URL` and `GAIA_API_KEY`.

Run from the Gaia repository root:

```bash
python3 examples/http-client/demo_readonly_run.py
python3 examples/http-client/demo_write_with_approval.py
python3 examples/http-client/demo_sse_events.py
python3 examples/http-client/demo_sse_live_approval.py
```

- `demo_readonly_run.py` creates the documented mock `controlled-task` inspection and reads its event history.
- `demo_write_with_approval.py` first inspects `res-002`, selects the opposite documented `pause` or `activate` request with a reason, then reads and approves its pending HumanGate with an `approver` role. It is repeatable against the stateful mock fixture.
- `demo_sse_events.py` creates a run and consumes its public SSE event stream.
- `demo_sse_live_approval.py` holds one SSE connection open for at least 0.6 seconds before a separate approval request, then verifies that the same stream receives later `run.event` frames through terminal completion and closes.

For a black-box validation pass, run the write demo twice consecutively, then run the live SSE demo. The write demo toggles `res-002` between its documented states, so each run creates a new HumanGate without a fixture reset.

```bash
python3 examples/http-client/demo_write_with_approval.py
python3 examples/http-client/demo_write_with_approval.py
python3 examples/http-client/demo_sse_live_approval.py
uv run ruff check examples/http-client
python3 -m py_compile examples/http-client/*.py
```
