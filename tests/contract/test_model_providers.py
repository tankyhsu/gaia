from pydantic import BaseModel

from examples.controlled_task.model import DeterministicMockProvider
from gaia.contracts.models import ModelCapabilities, ModelEndpointProfile
from gaia.spi.model import ModelMessage


class Intent(BaseModel):
    operation: str | None
    resource_id: str | None
    target_status: str | None
    reason: str | None


async def test_deterministic_mock_parses_controlled_task_intent() -> None:
    profile = ModelEndpointProfile(
        provider_id="mock",
        protocol="mock",
        model_id="deterministic-mock",
        capabilities=ModelCapabilities(
            structured_output=True,
            tool_calling=False,
            streaming=False,
            max_context_tokens=None,
        ),
        data_residency="local",
        timeout_seconds=1,
    )
    result = await DeterministicMockProvider().generate_structured(
        profile=profile,
        messages=[ModelMessage(role="user", content="pause res-001 because maintenance")],
        output_schema=Intent,
        timeout_seconds=1,
    )
    assert result.output == {
        "operation": "set_status",
        "resource_id": "res-001",
        "target_status": "paused",
        "reason": "maintenance",
    }
