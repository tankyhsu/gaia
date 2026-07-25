from fastapi.testclient import TestClient

from gaia.api.app import create_app
from gaia.application import GaiaApplication
from gaia.components import ComponentDescriptor, ComponentKind, ComponentRegistry
from gaia.config import GaiaApplicationConfig
from gaia.integrations.prompt_postgres import PostgresPromptRegistry
from gaia.persistence.database import initialize_database


async def test_opt_in_prompt_workspace_imports_and_inspects_drafts(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path}/gaia.db"
    factory = await initialize_database(database_url)
    prompt_registry = PostgresPromptRegistry(factory)
    components = ComponentRegistry()
    components.register(
        ComponentDescriptor(
            component_id="prompt-postgres",
            kind=ComponentKind.PROMPT,
            implementation="tests.PostgresPromptRegistry",
            starter_id="tests",
            profile="mock",
            reason="integration-test",
        ),
        lambda _components: prompt_registry,
    )
    config = GaiaApplicationConfig.model_validate(
        {
            "prompt": {"provider": "postgres"},
            "stores": {"operational": {"provider": "postgres"}},
        }
    )
    app = create_app(
        database_url=database_url,
        gaia_application=GaiaApplication(config, components),
        enable_devtools=True,
    )

    with TestClient(app) as client:
        status = client.get(
            "/devtools/prompts",
            headers={"X-Gaia-Api-Key": "gaia-dev-key"},
        )
        imported = client.post(
            "/devtools/prompts/import",
            headers={
                "X-Gaia-Api-Key": "gaia-dev-key",
                "X-Gaia-Actor": "developer",
            },
            json={
                "prompt_id": "summary",
                "version": "1.0.0",
                "messages": [{"role": "system", "content": "Summarize."}],
            },
        )
        inspected = client.get(
            "/devtools/prompts/summary",
            headers={"X-Gaia-Api-Key": "gaia-dev-key"},
        )

    assert status.status_code == 200
    assert status.json()["provider"] == "postgres"
    assert status.json()["access"] == "read_write"
    assert imported.status_code == 201
    assert imported.json()["status"] == "draft"
    assert inspected.status_code == 200
    assert inspected.json()["versions"][0]["artifact"]["prompt_id"] == "summary"


async def test_file_prompt_workspace_lists_artifacts_without_content(tmp_path) -> None:
    prompt_dir = tmp_path / "prompts" / "summary"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "1.0.0.yaml").write_text(
        """
prompt_id: summary
version: 1.0.0
messages:
  - role: system
    content: Do not expose this prompt body.
""".strip(),
        encoding="utf-8",
    )
    config = GaiaApplicationConfig.model_validate(
        {
            "prompt": {"provider": "file", "root": str(tmp_path / "prompts")},
        }
    )
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/file.db",
        gaia_application=GaiaApplication(config),
        enable_devtools=True,
    )

    with TestClient(app) as client:
        status = client.get(
            "/devtools/prompts",
            headers={"X-Gaia-Api-Key": "gaia-dev-key"},
        )

    assert status.status_code == 200
    assert status.json()["provider"] == "file"
    assert status.json()["access"] == "read_only"
    assert status.json()["artifacts"][0]["prompt_id"] == "summary"
    assert status.json()["artifacts"][0]["relative_path"] == "summary/1.0.0.yaml"
    assert "Do not expose" not in status.text
