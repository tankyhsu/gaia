import pytest
from pydantic import ValidationError

from gaia.config import GaiaApplicationConfig


def test_postgres_prompt_registry_requires_postgres_operational_store() -> None:
    with pytest.raises(ValidationError, match="prompt registry"):
        GaiaApplicationConfig.model_validate(
            {
                "prompt": {"provider": "postgres"},
                "stores": {"operational": {"provider": "sqlite"}},
            }
        )
