"""Version-pinned execution policy validation."""

from __future__ import annotations

from typing import Any

from gaia._authoring.versioning import fingerprint
from gaia.config.models import PolicyOverrideSettings
from gaia.contracts.models import ErrorCode, ExecutionPolicy, VersionBundle, WriteMode


class PolicyDenied(ValueError):
    pass


_WRITE_MODE_RANK: dict[WriteMode, int] = {
    WriteMode.DISABLED: 0,
    WriteMode.APPROVAL_REQUIRED: 1,
    WriteMode.ENABLED: 2,
}


def stricter_write_mode(first: WriteMode, second: WriteMode) -> WriteMode:
    """Return whichever of the two write modes is the more restrictive one.

    Rank: `DISABLED < APPROVAL_REQUIRED < ENABLED`; ties resolve to `first`.

    This is the single source of truth for "more restrictive" shared by the
    non-bypassable admission check in `runtime.safety` and the config-driven
    policy overrides in `apply_policy_override` below -- both need the exact
    same rank table, and a second copy of it would eventually drift.
    """

    return first if _WRITE_MODE_RANK[first] <= _WRITE_MODE_RANK[second] else second


def validate_tool_allowed(policy: ExecutionPolicy, tool_name: str) -> None:
    if tool_name not in policy.allowed_tools:
        raise PolicyDenied(f"tool {tool_name} is not allowed by policy")


def validate_roles(policy: ExecutionPolicy, roles: list[str]) -> None:
    unknown = set(roles).difference(policy.recognized_roles)
    if unknown:
        raise PolicyDenied(f"unrecognized roles: {sorted(unknown)}")


def apply_policy_override(
    policy: ExecutionPolicy, override: PolicyOverrideSettings
) -> ExecutionPolicy:
    """Return a strictly tighter policy whose version carries the override
    fingerprint, so audit evidence changes whenever governance changes.

    Every override field may only make `policy` *stricter*: a stricter write
    mode, a smaller budget, or a smaller `allowed_tools` set. This is not an
    incidental restriction -- an override that could loosen policy would turn
    a config file into a way to bypass the controls this framework exists to
    enforce, entirely outside of `@scenario` code review. Any attempt to
    loosen a field raises `ValueError` (prefixed
    `f"{ErrorCode.POLICY_OVERRIDE_INVALID.value}:"`) the moment this function
    runs -- for `RuntimeAssembler.create_engine`, that is application
    startup, never a request.

    The returned policy's `version` carries a fingerprint of the *effective*
    override (only the fields that actually changed something, canonically
    encoded) appended as a PEP 440 local version segment:
    `f"{policy.version}+ovr.{digest}"`, with `digest` computed via
    `fingerprint(..., qualified=False)` so it never contains a colon. If the
    override does not change anything relative to `policy` (every provided
    field already matches the baseline, or none were provided), `policy` is
    returned unchanged -- `version` included -- so a `+ovr.` suffix appearing
    in recorded evidence always reflects a *real* difference. `policy_id`
    never changes; only `version` does.
    """

    changes: dict[str, Any] = {}
    effective: dict[str, Any] = {}

    if override.write_mode is not None:
        tightened = stricter_write_mode(policy.write_mode, override.write_mode)
        if tightened != override.write_mode:
            raise ValueError(
                f"{ErrorCode.POLICY_OVERRIDE_INVALID.value}: write_mode override "
                f"{override.write_mode.value!r} is not at least as strict as the "
                f"current {policy.write_mode.value!r}"
            )
        if override.write_mode != policy.write_mode:
            changes["write_mode"] = override.write_mode
            effective["write_mode"] = override.write_mode.value

    for field_name in ("max_steps", "max_model_calls", "max_duration_seconds"):
        override_value = getattr(override, field_name)
        if override_value is None:
            continue
        current_value = getattr(policy, field_name)
        if override_value > current_value:
            raise ValueError(
                f"{ErrorCode.POLICY_OVERRIDE_INVALID.value}: {field_name} override "
                f"{override_value} is larger than the current {current_value}"
            )
        if override_value != current_value:
            changes[field_name] = override_value
            effective[field_name] = override_value

    if override.deny_tools:
        denied = set(override.deny_tools)
        removed = tuple(name for name in policy.allowed_tools if name in denied)
        if removed:
            changes["allowed_tools"] = [
                name for name in policy.allowed_tools if name not in denied
            ]
            effective["deny_tools"] = sorted(removed)

    if not changes:
        return policy

    digest = fingerprint(effective, qualified=False)
    return policy.model_copy(
        update={**changes, "version": f"{policy.version}+ovr.{digest}"}
    )


def freeze_version_bundle(
    *,
    policy: ExecutionPolicy,
    workflow: str,
    rules: str,
    prompt: str,
    model_profile: str,
    toolset: str,
    context_profile: str,
) -> VersionBundle:
    return VersionBundle(
        policy=f"{policy.policy_id}:{policy.version}",
        workflow=workflow,
        rules=rules,
        prompt=prompt,
        model_profile=model_profile,
        toolset=toolset,
        context_profile=context_profile,
    )
