"""Version-pinned execution policy validation."""

from __future__ import annotations

from gaia.contracts.models import ExecutionPolicy, VersionBundle


class PolicyDenied(ValueError):
    pass


def validate_tool_allowed(policy: ExecutionPolicy, tool_name: str) -> None:
    if tool_name not in policy.allowed_tools:
        raise PolicyDenied(f"tool {tool_name} is not allowed by policy")


def validate_roles(policy: ExecutionPolicy, roles: list[str]) -> None:
    unknown = set(roles).difference(policy.recognized_roles)
    if unknown:
        raise PolicyDenied(f"unrecognized roles: {sorted(unknown)}")


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
