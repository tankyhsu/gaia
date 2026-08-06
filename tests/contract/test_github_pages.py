"""Keep the public documentation deployment safe and reproducible."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "pages.yml"


def test_pages_workflow_builds_the_locked_mkdocs_site_and_deploys_only_main() -> None:
    source = WORKFLOW.read_text()
    workflow = yaml.safe_load(source)

    assert isinstance(workflow, dict)
    assert "push:\n    branches: [main]" in source
    assert "workflow_dispatch:" in source
    assert workflow["permissions"] == {"contents": "read"}

    build = workflow["jobs"]["build"]
    build_steps = build["steps"]
    assert any(step.get("uses") == "actions/configure-pages@v5" for step in build_steps)
    assert any(
        step.get("run") == "uv sync --locked --all-extras --all-groups"
        for step in build_steps
    )
    assert any(step.get("run") == "uv run mkdocs build --strict" for step in build_steps)
    assert any(
        step.get("uses") == "actions/upload-pages-artifact@v4"
        and step.get("with") == {"path": "site"}
        for step in build_steps
    )

    deploy = workflow["jobs"]["deploy"]
    assert deploy["if"] == "github.ref == 'refs/heads/main'"
    assert deploy["needs"] == "build"
    assert deploy["permissions"] == {"pages": "write", "id-token": "write"}
    assert deploy["environment"]["name"] == "github-pages"
    assert deploy["environment"]["url"] == "${{ steps.deployment.outputs.page_url }}"
    assert deploy["steps"] == [
        {
            "name": "Deploy to GitHub Pages",
            "id": "deployment",
            "uses": "actions/deploy-pages@v4",
        }
    ]


def test_mkdocs_uses_the_public_pages_and_repository_urls() -> None:
    config = yaml.safe_load((ROOT / "mkdocs.yml").read_text())

    assert config["site_url"] == "https://tankyhsu.github.io/gaia/"
    assert config["repo_url"] == "https://github.com/tankyhsu/gaia"
    assert config["edit_uri"] == "edit/main/developer-docs/"
