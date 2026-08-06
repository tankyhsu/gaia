"""Runnable attack-and-defence demonstration for Gaia's controlled-execution claims.

`README.md` claims Gaia enforces a set of controls that cannot be bypassed from inside
an application: identity authority, cross-organization isolation, token verification,
monotonic policy overrides, the tool allow-list, and import-time purity checks.
A claim like that is worth exactly as much as the evidence behind it.

This script does not audit anything and is not a penetration test. It packages seven
attacks that were already reproduced during development (see the reproduction scripts
this file was built from, and the permanent regression tests listed next to each
attack below) into one runnable, no-external-services demonstration. Each attack
prints what was attempted, what happened, and which code enforces the outcome
(file:line or symbol) so the result can be checked against the source rather than
taken on faith.

Requires no Docker, no network, and no PostgreSQL: SQLite (mostly in-memory or a
throwaway tmp file), the mock model/environment, and locally generated RSA keys only.
The one real network-shaped call (JWKS fetch) is intercepted with `respx`.

Exit code is 0 only if every defence held. A defence that does not hold is reported
here plainly -- as an unexpected result, not smoothed over -- and makes the script
exit non-zero, exactly like any other regression check.

Permanent regression tests covering the same ground (more exhaustively, with pytest's
usual fixtures and parametrization) live at:
  tests/integration/test_f1_resource_ownership.py   (attacks 1, 2)
  tests/unit/integrations/test_oidc.py              (attacks 3, 4)
  tests/unit/test_policy_override.py                (attacks 5, 6)
  tests/architecture/test_import_purity.py          (attack 7, import purity)
  tests/integration/test_runtime_recovery_batching.py (attack 7, recovery batching)
  tests/unit/test_import_purity.py                  (attack 8)
This script is a narrated, standalone tour through the same claims -- not a
replacement for those tests, and not itself part of the pytest suite.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import sys
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SEPARATOR = "=" * 78


def _banner(number: int, title: str) -> None:
    print()
    print(_SEPARATOR)
    print(f"Attack {number}: {title}")
    print(_SEPARATOR)


def _step(text: str) -> None:
    print(f"  {text}")


def _verdict(*, held: bool, expected: str, observed: str, enforced_by: str) -> bool:
    print(f"  Expected:    {expected}")
    print(f"  Observed:    {observed}")
    print(f"  Enforced by: {enforced_by}")
    print(f"  Result:      {'DEFENSE HELD' if held else '*** DEFENSE FAILED ***'}")
    return held


# ---------------------------------------------------------------------------
# Attacks 1 & 2: forged approver role, cross-organization access
# ---------------------------------------------------------------------------


def _build_attack12_app() -> Any:
    from datetime import UTC, datetime, timedelta

    from gaia.api.app import ApiDependencies, create_app
    from gaia.application import GaiaApplication
    from gaia.config import GaiaApplicationConfig
    from gaia.contracts.models import (
        GateStatus,
        HumanGate,
        HumanGateDecisionRequest,
        RiskLevel,
        RunSnapshot,
        RunStatus,
        UserIdentity,
        VersionBundle,
    )
    from gaia.runtime.temporal_runtime import TemporalRuntimeEngine
    from gaia.spi.auth import AuthenticationError

    identities = {
        "alice": UserIdentity(id="alice", organization="org-a", roles=["user"]),
        "mallory": UserIdentity(id="mallory", organization="org-a", roles=["user"]),
        "approver-1": UserIdentity(
            id="approver-1", organization="org-a", roles=["approver"]
        ),
        "bob": UserIdentity(id="bob", organization="org-b", roles=["approver"]),
    }
    now = datetime.now(UTC)
    run_id = "temporal-attack-demo-org-a"
    gate_id = f"{run_id}:gate:publish"
    run = RunSnapshot(
        run_id=run_id,
        scenario_id="attack_demo.request_publish",
        mode="mock",
        status=RunStatus.WAITING_HUMAN,
        user=identities["alice"],
        version_bundle=VersionBundle(
            policy="policy:1",
            workflow="workflow:1",
            rules="rules:1",
            prompt="prompt:1",
            model_profile="model:1",
            toolset="tools:1",
            context_profile="context:1",
        ),
        pending_gate_id=gate_id,
        created_at=now,
        updated_at=now,
    )
    gate = HumanGate(
        gate_id=gate_id,
        run_id=run_id,
        command_id=f"{run_id}:command:publish",
        reason="Publishing changes a durable business record.",
        risk_level=RiskLevel.HIGH,
        requested_action={"tool_name": "attack_demo.publish", "resource_id": "widget-1"},
        status=GateStatus.PENDING,
        requested_by="alice",
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )

    class _Runtime(TemporalRuntimeEngine):
        def __init__(self) -> None:
            super().__init__()
            self.decisions: list[HumanGateDecisionRequest] = []
            self.cancellations: list[str] = []

        async def inspect(self, requested_run_id: str) -> RunSnapshot:
            if requested_run_id != run.run_id:
                raise KeyError(requested_run_id)
            return run

        async def get_gate(self, requested_gate_id: str) -> HumanGate:
            if requested_gate_id != gate.gate_id:
                raise KeyError(requested_gate_id)
            return gate

        async def decide(
            self,
            requested_gate_id: str,
            body: HumanGateDecisionRequest,
        ) -> RunSnapshot:
            if requested_gate_id != gate.gate_id:
                raise KeyError(requested_gate_id)
            self.decisions.append(body)
            return run.model_copy(update={"status": RunStatus.SUCCEEDED, "pending_gate_id": None})

        async def cancel(self, requested_run_id: str, reason: str) -> RunSnapshot:
            if requested_run_id != run.run_id:
                raise KeyError(requested_run_id)
            self.cancellations.append(reason)
            return run.model_copy(update={"status": RunStatus.CANCELLED})

    class _TokenAuthn:
        async def authenticate(self, headers: Mapping[str, str]) -> UserIdentity | None:
            value = headers.get("authorization", "")
            scheme, _, token = value.partition(" ")
            if scheme.lower() != "bearer" or token not in identities:
                raise AuthenticationError("unknown or missing bearer token")
            return identities[token]

    runtime = _Runtime()
    config = GaiaApplicationConfig(runtime={"execution": {"provider": "temporal"}})

    def runtime_factory(factory: object, database_url: str) -> _Runtime:
        del factory, database_url
        return runtime

    tmp_dir = tempfile.mkdtemp(prefix="gaia-attack-demo-identity-")
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_dir}/attack-demo.db",
        gaia_application=GaiaApplication(config),
        dependencies=ApiDependencies(runtime_factory=runtime_factory),
        authn=_TokenAuthn(),
    )
    return app, identities, runtime, run, gate


def attack_1_and_2_forged_role_and_cross_org() -> tuple[bool, bool]:
    from fastapi.testclient import TestClient

    app, _, runtime, run, gate = _build_attack12_app()

    def auth(name: str) -> dict[str, str]:
        return {"authorization": f"Bearer {name}"}

    with TestClient(app) as client:
        _banner(1, "Forged approver role")
        forged = client.post(
            f"/v1/human-gates/{gate.gate_id}/decision",
            headers=auth("mallory"),
            json={
                "decision": "approved",
                "decided_by": "mallory",
                "roles": ["approver"],
                "comment": "forged by mallory",
            },
        )
        attack_1_held = _verdict(
            held=(
                forged.status_code == 409
                and forged.json().get("code") == "IDENTITY_MISMATCH"
                and runtime.decisions == []
            ),
            expected="409 IDENTITY_MISMATCH before the Temporal Update boundary",
            observed=f"{forged.status_code} {forged.json().get('code')}",
            enforced_by="src/gaia/api/app.py authenticated identity checks before Runtime.decide",
        )
        legit = client.post(
            f"/v1/human-gates/{gate.gate_id}/decision",
            headers=auth("approver-1"),
            json={
                "decision": "approved",
                "decided_by": "approver-1",
                "roles": ["approver"],
                "comment": "reviewed",
            },
        )
        _step(
            f"Legitimate approver contrast: {legit.status_code}; "
            f"Temporal Updates captured={len(runtime.decisions)}"
        )

        _banner(2, "Cross-organization access")
        bob_gate = client.get(f"/v1/human-gates/{gate.gate_id}", headers=auth("bob"))
        bob_run = client.get(f"/v1/runs/{run.run_id}", headers=auth("bob"))
        bob_cancel = client.post(
            f"/v1/runs/{run.run_id}/cancel",
            headers=auth("bob"),
            json={"reason": "not mine"},
        )
        bob_decide = client.post(
            f"/v1/human-gates/{gate.gate_id}/decision",
            headers=auth("bob"),
            json={
                "decision": "approved",
                "decided_by": "bob",
                "roles": ["approver"],
                "comment": "cross-org attempt",
            },
        )
        alice_run = client.get(f"/v1/runs/{run.run_id}", headers=auth("alice"))
        attack_2_held = _verdict(
            held=(
                all(
                    response.status_code == 404
                    for response in (bob_gate, bob_run, bob_cancel, bob_decide)
                )
                and alice_run.status_code == 200
                and runtime.cancellations == []
                and len(runtime.decisions) == 1
            ),
            expected="cross-org reads and writes return 404 before Temporal Query/Signal/Update",
            observed=(
                f"gate={bob_gate.status_code}, run={bob_run.status_code}, "
                f"cancel={bob_cancel.status_code}, decide={bob_decide.status_code}"
            ),
            enforced_by="src/gaia/api/app.py organization ownership checks",
        )
    return attack_1_held, attack_2_held


# Attacks 3 & 4: alg=none forgery, RS256/HS256 key-confusion
# ---------------------------------------------------------------------------
# Adapted from scratchpad/jwt_attack.py (verified during development) and
# tests/unit/integrations/test_oidc.py.


async def attack_3_and_4_jwt_forgery() -> tuple[bool, bool, bool]:
    import httpx
    import jwt
    import respx
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    from gaia.integrations.oidc import ClaimMapping, JwtAuthnProvider
    from gaia.spi.auth import AuthenticationError

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = key.public_key()
    numbers = public_key.public_numbers()

    def b64url_uint(value: int) -> str:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    jwk = {
        "kty": "RSA",
        "kid": "k1",
        "use": "sig",
        "alg": "RS256",
        "n": b64url_uint(numbers.n),
        "e": b64url_uint(numbers.e),
    }
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    issuer, audience, jwks_url = "https://idp.test/realms/gaia", "gaia-api", "https://idp.test/jwks"
    claims = {
        "sub": "alice",
        "org_id": "org-a",
        "realm_access": {"roles": ["user"]},
        "iss": issuer,
        "aud": audience,
        "exp": int(time.time()) + 300,
        "nbf": int(time.time()) - 10,
    }

    def legit_token() -> str:
        return jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": "k1"})

    def alg_none_token() -> str:
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "none", "typ": "JWT", "kid": "k1"}).encode()
        ).rstrip(b"=")
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
        return f"{header.decode()}.{payload.decode()}."

    def hs256_key_confusion_token() -> str:
        """Hand-forge HS256 using the IdP's *public* key bytes as the HMAC secret.

        PyJWT's own `jwt.encode(..., algorithm="HS256")` refuses a key that looks
        like an RSA/EC PEM object -- that guardrail is exactly what protects a
        careless caller of the *signing* API, but it does not exist on the
        verification side, and a real attacker forging a token from outside has
        no reason to go through PyJWT's signing call at all. So this hand-rolls
        HMAC-SHA256 directly, exactly as an attacker would: the public key is
        public by definition (that is the whole point of asymmetric crypto), so
        anyone can fetch it from the JWKS endpoint and use it as an HMAC secret
        if the verifier is naive enough to trust the token's own `alg` header.
        """
        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "HS256", "typ": "JWT", "kid": "k1"}).encode()
        ).rstrip(b"=")
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=")
        signing_input = header + b"." + payload
        signature = hmac.new(public_pem, signing_input, hashlib.sha256).digest()
        return (signing_input + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")).decode()

    async def try_authenticate(token: str) -> tuple[bool, str]:
        provider = JwtAuthnProvider(
            issuer=issuer,
            audience=audience,
            jwks_url=jwks_url,
            claims=ClaimMapping(subject="sub", organization="org_id", roles="realm_access.roles"),
        )
        try:
            identity = await provider.authenticate({"authorization": f"Bearer {token}"})
            return True, f"accepted: {identity}"
        except AuthenticationError as error:
            return False, f"AuthenticationError: {error}"

    with respx.mock() as router:
        router.get(jwks_url).mock(return_value=httpx.Response(200, json={"keys": [jwk]}))

        accepted_legit, detail_legit = await try_authenticate(legit_token())
        sanity_ok = accepted_legit
        print(
            "  Sanity check: a genuinely signed RS256 token from this JWKS is "
            f"accepted -> {detail_legit}"
        )
        if not sanity_ok:
            print(
                "  *** UNEXPECTED: the legitimate token was rejected -- something "
                "other than the two attacks below is broken; see detail above."
            )

        _banner(3, "alg=none token")
        _step(
            "Attempting: a hand-forged JWT with header {\"alg\": \"none\"} and no "
            "signature segment at all -- the classic bypass for verifiers that "
            "trust the token's own algorithm claim."
        )
        accepted_none, detail_none = await try_authenticate(alg_none_token())
        attack_3_held = _verdict(
            held=not accepted_none,
            expected="rejected (AuthenticationError)",
            observed=detail_none,
            enforced_by=(
                "src/gaia/integrations/oidc.py:311-318 (JwtAuthnProvider.authenticate) -- "
                "the token header's alg is checked against a fixed allowlist "
                "*before* any JWKS lookup or cryptography, and "
                "src/gaia/integrations/oidc.py:58-68 (_reject_unsafe_algorithms) refuses "
                "'none' and any symmetric algorithm at provider-construction time, so it "
                "could never be in that allowlist to begin with."
            ),
        )

        _banner(4, "RS256/HS256 key-confusion")
        _step(
            "Attempting: fetch the RS256 public key from the JWKS (public by "
            "definition) and use its PEM bytes as an HMAC-SHA256 secret to "
            "hand-forge an HS256-signed token -- the classic key-confusion attack "
            "against a verifier that picks its algorithm from the token itself."
        )
        accepted_confused, detail_confused = await try_authenticate(hs256_key_confusion_token())
        attack_4_held = _verdict(
            held=not accepted_confused,
            expected="rejected (AuthenticationError)",
            observed=detail_confused,
            enforced_by=(
                "src/gaia/integrations/oidc.py:322-333 -- jwt.decode(..., "
                "algorithms=list(self._algorithms)) always verifies against the "
                "server's own fixed, asymmetric-only allowlist, never "
                "`algorithms=[header['alg']]` from the token; HS256 is never in "
                "that allowlist (src/gaia/config/models.py OIDC_ASYMMETRIC_ALGORITHMS), "
                "so the forged signature is never even attempted against the public key."
            ),
        )

    return attack_3_held, attack_4_held, sanity_ok


# ---------------------------------------------------------------------------
# Attack 5: loosening a policy from config
# ---------------------------------------------------------------------------


async def attack_5_policy_override_loosening() -> bool:
    from gaia import ScenarioContext, get_scenario_spec, scenario
    from gaia.config.models import PolicyOverrideSettings
    from gaia.contracts.models import WriteMode
    from gaia.runtime.assembly import _scenario_spec_with_override

    _banner(5, "Loosening a policy from config")

    @scenario("attack_demo.policy_loosen", write_mode=WriteMode.DISABLED)
    async def locked(context: ScenarioContext) -> dict[str, str]:
        del context
        return {"status": "unused"}

    error_message = ""
    try:
        _scenario_spec_with_override(
            get_scenario_spec(locked),
            PolicyOverrideSettings(write_mode=WriteMode.ENABLED),
        )
    except ValueError as error:
        error_message = str(error)

    @scenario("attack_demo.policy_tighten", write_mode=WriteMode.ENABLED)
    async def enabled(context: ScenarioContext) -> dict[str, str]:
        del context
        return {"status": "unused"}

    tightened = _scenario_spec_with_override(
        get_scenario_spec(enabled),
        PolicyOverrideSettings(write_mode=WriteMode.APPROVAL_REQUIRED),
    )
    return _verdict(
        held=(
            error_message.startswith("POLICY_OVERRIDE_INVALID")
            and tightened.write_mode == WriteMode.APPROVAL_REQUIRED
            and "+ovr." in tightened.policy_version
        ),
        expected="loosening rejected before Workflow start; tightening accepted and fingerprinted",
        observed=(
            f"loosening={error_message!r}; tightening={tightened.write_mode.value}/"
            f"{tightened.policy_version}"
        ),
        enforced_by="src/gaia/runtime/assembly.py _scenario_spec_with_override",
    )


# Attack 6: denied tool called directly via ctx.tools.call(...)
# ---------------------------------------------------------------------------


async def attack_6_denied_tool_called_directly() -> bool:
    from gaia import ScenarioContext, get_scenario_spec, read_tool, scenario
    from gaia.config.models import PolicyOverrideSettings
    from gaia.contracts.models import ErrorCode, RunMode, RunRequest, RunStatus, UserIdentity
    from gaia.runtime.assembly import _scenario_spec_with_override
    from gaia.runtime.dependencies import ToolRegistry
    from gaia.runtime.function_runner import FunctionScenarioRunner
    from gaia.runtime.function_tools import function_tool

    _banner(6, "Denied tool called directly (not via a write proposal)")
    tool_name = "attack_demo.denied_read_tool"
    scenario_id = "attack_demo.deny_tool_direct_call"

    @read_tool(tool_name)
    async def read(*, resource_id: str) -> dict[str, str]:
        return {"resource_id": resource_id, "status": "ok"}

    @scenario(scenario_id, allowed_tools=(tool_name,), max_model_calls=0)
    async def handler(context: ScenarioContext) -> dict[str, Any]:
        assert context.tools is not None
        result = await context.tools.call(tool_name, resource_id=context.text)
        return dict(result.data)

    request = RunRequest(
        scenario_id=scenario_id,
        mode=RunMode.MOCK,
        user=UserIdentity(id="user-1", organization="gaia", roles=["user"]),
        request={"text": "widget-1"},
    )
    registry = ToolRegistry((function_tool(read),))
    baseline = FunctionScenarioRunner(handler, tools=registry)
    effective = _scenario_spec_with_override(
        get_scenario_spec(handler),
        PolicyOverrideSettings(deny_tools=(tool_name,)),
    )
    tightened = FunctionScenarioRunner(handler, effective, tools=registry)
    baseline_result = await baseline.run(run_id="attack6-baseline", request=request)
    tightened_result = await tightened.run(run_id="attack6-tightened", request=request)

    return _verdict(
        held=(
            baseline_result.status == RunStatus.SUCCEEDED
            and tightened_result.status == RunStatus.BLOCKED
            and tightened_result.error_code == ErrorCode.TOOL_NOT_ALLOWED
        ),
        expected="baseline succeeds; tightened Runner blocks TOOL_NOT_ALLOWED",
        observed=(
            f"baseline={baseline_result.status.value}; tightened="
            f"{tightened_result.status.value}/{tightened_result.error_code}"
        ),
        enforced_by="FunctionScenarioRunner ScopedToolExecutor using the rewritten ScenarioSpec",
    )


# Attack 7: import-time side effect flagged by `gaia check`
# ---------------------------------------------------------------------------


def attack_7_import_time_side_effect() -> bool:
    from gaia.cli.main import main as gaia_cli_main

    _banner(7, "Import-time side effect")
    _step(
        "Attempting: a scenario module that resolves a secret at import time "
        "(`from gaia.config.secrets import resolve_secret` then a top-level "
        "`resolve_secret(...)` call) is declared in gaia.yaml's `scenarios.modules` "
        "and checked with `gaia check`."
    )

    with tempfile.TemporaryDirectory(prefix="gaia-attack-demo-purity-") as tmp:
        tmp_path = Path(tmp)
        module_name = "gaia_attack_demo_impure_scenario"
        (tmp_path / f"{module_name}.py").write_text(
            "from gaia.config.secrets import resolve_secret\n"
            "\n"
            "# Resolved the moment anything imports this module -- before any Run,\n"
            "# before any Starter-managed lifespan exists to own the resulting client\n"
            "# or connection.\n"
            'API_KEY = resolve_secret("attack-demo-secret-should-never-resolve")\n'
        )
        gaia_yaml = tmp_path / "gaia.yaml"
        gaia_yaml.write_text(
            "gaia:\n"
            "  application: {name: attack-demo-purity, version: 1.0.0}\n"
            "  profile: mock\n"
            "  starters: [core-runtime, model-mock, scenario-runtime]\n"
            "  runtime:\n"
            "    environment: mock\n"
            f'    database_url: "sqlite+aiosqlite:///{tmp_path}/purity.db"\n'
            "  scenarios:\n"
            f"    modules: [{module_name}]\n"
        )

        sys.path.insert(0, str(tmp_path))
        output_lines: list[str] = []
        try:
            exit_code = gaia_cli_main(
                ["check", "--config", str(gaia_yaml)], output=output_lines.append
            )
        finally:
            sys.path.remove(str(tmp_path))

    payload: dict[str, Any] = {}
    if output_lines:
        try:
            payload = json.loads(output_lines[0])
        except json.JSONDecodeError:
            payload = {}
    issues = payload.get("issues", [])

    held = exit_code == 2 and any("resolve_secret" in issue for issue in issues)
    verdict = _verdict(
        held=held,
        expected="`gaia check` exits 2 and names gaia.config.secrets.resolve_secret",
        observed=f"exit code={exit_code}, issues={issues}",
        enforced_by=(
            "src/gaia/cli/main.py:262-284 (_check) calling "
            "src/gaia/diagnostics/import_purity.py (scan_module_purity / IMPURE_CALLS) "
            "for every module in scenarios.modules, before configure() ever imports "
            "them for real."
        ),
    )
    print(
        "  Caveat, stated plainly: this is a best-effort static lint, not "
        "isolation or a security boundary. It matches only a fixed allowlist of "
        "well-known impure calls resolved by import source (never by bare name), "
        "and it deliberately does not flag what it cannot resolve -- dynamic "
        "importlib.import_module, indirection through a locally-defined wrapper, "
        "or third-party code that does I/O internally under a name outside the "
        "allowlist all sail through unflagged. See "
        "src/gaia/diagnostics/import_purity.py's module docstring for the full "
        "list of deliberate gaps."
    )
    return verdict


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def main() -> int:
    # Every attack below deliberately triggers a rejection (401/403/404/409/...),
    # each already logged at WARNING by the runtime itself (e.g.
    # src/gaia/api/app.py's error_response, src/gaia/runtime/persistent_engine.py's
    # lost-lease-race warning). That is expected noise, not a fault this script
    # needs to surface a second time -- the printed narrative below is the record
    # of what happened. Quiet it so stdout stays readable; ERROR+ still surfaces.
    logging.getLogger("gaia").setLevel(logging.ERROR)

    results: list[tuple[str, bool]] = []

    print(_SEPARATOR)
    print("Gaia attack-and-defence demonstration")
    print(
        "Not a security audit or penetration test: seven previously-reproduced "
        "attacks, packaged so each defence can be checked against the source "
        "that enforces it rather than taken on faith."
    )
    print(_SEPARATOR)

    attack_1_held, attack_2_held = attack_1_and_2_forged_role_and_cross_org()
    results.append(("1. Forged approver role", attack_1_held))
    results.append(("2. Cross-organization access", attack_2_held))

    attack_3_held, attack_4_held, jwt_sanity_ok = asyncio.run(attack_3_and_4_jwt_forgery())
    results.append(("3. alg=none token", attack_3_held))
    results.append(("4. RS256/HS256 key confusion", attack_4_held))
    if not jwt_sanity_ok:
        results.append(("  (sanity) legitimate RS256 token accepted", False))

    attack_5_held = asyncio.run(attack_5_policy_override_loosening())
    results.append(("5. Loosening a policy from config", attack_5_held))

    attack_6_held = asyncio.run(attack_6_denied_tool_called_directly())
    results.append(("6. Denied tool called directly", attack_6_held))

    attack_7_held = attack_7_import_time_side_effect()
    results.append(("7. Import-time side effect", attack_7_held))

    print()
    print(_SEPARATOR)
    print("Summary")
    print(_SEPARATOR)
    for name, held in results:
        print(f"  [{'PASS' if held else 'FAIL'}] {name}")

    print()
    print(_SEPARATOR)
    print("What this demonstration does NOT prove")
    print(_SEPARATOR)
    print(
        "  - Authorization is organization-scoped only. Attack 2 shows Bob (a\n"
        "    different organization) cannot reach Alice's resources; it says\n"
        "    nothing about finer-grained authorization *within* one organization,\n"
        "    which is the calling application's own responsibility, not Gaia's.\n"
        "  - Durable Workflow replay, cross-replica execution coordination, and\n"
        "    recovery are Temporal responsibilities. This Gaia-only demonstration\n"
        "    does not attempt to reproduce Temporal's server/Worker guarantees.\n"
        "  - The `gaia check` import-purity scan (attack 7) is a best-effort\n"
        "    static lint, not an isolation guarantee. It is defeated by ordinary\n"
        "    indirection (dynamic imports, wrapper functions, third-party I/O\n"
        "    under an unlisted name) and says so in its own module docstring.\n"
        "  - None of this constitutes a compliance certification or audit. It is\n"
        "    an engineering demonstration that specific, named mechanisms behave\n"
        "    as documented against specific, named attacks -- not a claim that\n"
        "    every possible attack has been considered."
    )

    all_held = all(held for _, held in results)
    print()
    print(_SEPARATOR)
    print("ALL DEFENSES HELD" if all_held else "*** AT LEAST ONE DEFENSE FAILED ***")
    print(_SEPARATOR)
    return 0 if all_held else 1


if __name__ == "__main__":
    raise SystemExit(main())
