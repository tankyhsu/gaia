"""ASGI composition root for the `function_task` reference application."""

import os
from pathlib import Path

from fastapi import FastAPI

from gaia.api.app import create_app
from gaia.application import GaiaApplication
from gaia.config import resolve_config_path

DEFAULT_CONFIG = Path(__file__).parent / "gaia.yaml"


def application_config_path() -> Path:
    return resolve_config_path() if os.environ.get("GAIA_CONFIG_PATH") else DEFAULT_CONFIG


def build() -> FastAPI:
    return create_app(
        gaia_application=GaiaApplication.from_config(application_config_path())
    )
