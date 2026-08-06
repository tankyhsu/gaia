from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from gaia.integrations.prompt_files import FilePromptProvider, PromptNotFoundError
from gaia.spi.prompt import PromptArtifact, PromptRef


def prompt_data() -> dict[str, object]:
    return {
        "prompt_id": "hello",
        "version": "1.0.0",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        "messages": [
            {"role": "system", "content": "Return a concise greeting."},
            {"role": "user", "content": "Hello, {name}"},
        ],
        "model_requirements": {"structured_output": False},
        "metadata": {"owner": "application"},
    }


def test_prompt_artifact_hash_is_stable_and_checked() -> None:
    artifact = PromptArtifact.model_validate(prompt_data())
    rebuilt = PromptArtifact.model_validate(
        {**prompt_data(), "content_hash": artifact.content_hash}
    )

    assert rebuilt.content_hash == artifact.content_hash
    assert artifact.version_id == f"hello:1.0.0@{artifact.content_hash}"

    with pytest.raises(ValidationError, match="content_hash"):
        PromptArtifact.model_validate({**prompt_data(), "content_hash": "tampered"})


async def test_file_provider_resolves_exact_version_without_configure_io(
    tmp_path: Path,
) -> None:
    provider = FilePromptProvider(tmp_path / "prompts")
    prompt_dir = tmp_path / "prompts" / "hello"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "1.0.0.yaml").write_text(
        yaml.safe_dump(prompt_data(), sort_keys=False),
        encoding="utf-8",
    )

    artifact = await provider.resolve(PromptRef(prompt_id="hello", version="1.0.0"))
    artifacts = await provider.list_artifacts()

    assert artifact.prompt_id == "hello"
    assert len(artifact.content_hash) == 64
    assert [item.version_id for item in artifacts] == [artifact.version_id]
    with pytest.raises(PromptNotFoundError, match="PROMPT_NOT_FOUND"):
        await provider.resolve(PromptRef(prompt_id="hello", version="2.0.0"))


def test_prompt_ref_rejects_path_traversal() -> None:
    with pytest.raises(ValidationError, match="unsupported characters"):
        PromptRef(prompt_id="../secret", version="1.0.0")


async def test_file_provider_rejects_symlink_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "prompts"
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir()
    (outside / "1.0.0.yaml").write_text(
        yaml.safe_dump(prompt_data(), sort_keys=False),
        encoding="utf-8",
    )
    (root / "hello").symlink_to(outside, target_is_directory=True)
    provider = FilePromptProvider(root)

    with pytest.raises(PromptNotFoundError, match="PROMPT_OUTSIDE_ROOT"):
        await provider.resolve(PromptRef(prompt_id="hello", version="1.0.0"))


def test_prompt_ref_requires_one_selector() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        PromptRef(prompt_id="hello")
    with pytest.raises(ValidationError, match="exactly one"):
        PromptRef(prompt_id="hello", version="1.0.0", environment="mock")
