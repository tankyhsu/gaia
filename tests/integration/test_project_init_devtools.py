from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from gaia.api.app import create_app
from gaia.templates import project_files, selected_starters


def _write_initial_project(root: Path) -> None:
    for relative, contents in project_files(
        "guided-app",
        selected_starters("basic"),
    ).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")


def test_quickstart_applies_template_once_and_then_closes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_initial_project(tmp_path)
    monkeypatch.setenv("GAIA_PROJECT_ROOT", str(tmp_path))
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}",
        enable_devtools=True,
    )
    headers = {"X-Gaia-Api-Key": "gaia-dev-key"}

    with TestClient(app) as client:
        initial = client.get("/devtools/project/init", headers=headers)
        applied = client.post(
            "/devtools/project/init",
            headers=headers,
            json={"template_id": "approval", "components": ["cache"]},
        )
        after_apply = client.get("/devtools/project/init", headers=headers)
        marker = json.loads((tmp_path / ".gaia/init.json").read_text())
        completed = client.post("/devtools/project/init/complete", headers=headers)
        after_complete = client.get("/devtools/project/init", headers=headers)

    assert initial.status_code == 200
    assert {item["id"] for item in initial.json()["templates"]} == {
        "basic",
        "knowledge",
        "approval",
    }
    assert applied.status_code == 200
    assert applied.json()["restart_required"] is True
    assert "cache-redis" in applied.json()["starters"]
    assert after_apply.json()["applied"] is True
    assert marker["template_id"] == "approval"
    assert (tmp_path / "src/guided_app/scenarios/approval.py").is_file()
    assert not (tmp_path / "src/guided_app/scenarios/hello.py").exists()
    assert completed.json() == {"completed": True}
    assert after_complete.status_code == 200
    assert after_complete.json()["available"] is False
    assert not (tmp_path / ".gaia/init.json").exists()


def test_project_init_write_routes_do_not_exist_without_devtools(tmp_path: Path) -> None:
    _write_initial_project(tmp_path)
    app = create_app(database_url=f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")

    with TestClient(app) as client:
        response = client.post(
            "/devtools/project/init",
            headers={"X-Gaia-Api-Key": "gaia-dev-key"},
            json={"template_id": "approval", "components": []},
        )

    assert response.status_code == 404
