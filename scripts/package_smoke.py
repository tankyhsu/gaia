"""Build Gaia and verify the installed wheel can generate a working application."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).parents[1]


def run(*command: str, cwd: Path = ROOT) -> None:
    print(f"[package-smoke] {' '.join(command)}")
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="gaia-package-smoke-") as directory:
        work = Path(directory)
        dist = work / "dist"
        environment = work / "venv"
        application = work / "generated-app"

        run("uv", "build", "--out-dir", str(dist))
        wheel = next(dist.glob("gaia_framework-*.whl"))
        run("uv", "venv", str(environment))
        python = environment / "bin" / "python"
        gaia = environment / "bin" / "gaia"
        run("uv", "pip", "install", "--python", str(python), str(wheel), "pytest")
        run(
            str(gaia),
            "init",
            str(application),
            "--name",
            "ci-smoke",
            "--starter",
            "model-mock",
            "--starter",
            "workflow-langgraph",
        )
        run(str(gaia), "check", "--config", "gaia.yaml", cwd=application)
        run(
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--no-deps",
            "-e",
            str(application),
        )
        run(str(python), "-m", "pytest", "-q", cwd=application)
        run(
            str(python),
            "-c",
            "from ci_smoke.app import app; assert app is not None",
            cwd=application,
        )
        print("Gaia wheel smoke passed.")


if __name__ == "__main__":
    main()
