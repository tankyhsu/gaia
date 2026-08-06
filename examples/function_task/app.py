"""ASGI composition root for the `function_task` reference application."""

from pathlib import Path

from fastapi import FastAPI

from gaia.api.app import create_app
from gaia.application import GaiaApplication


def build() -> FastAPI:
    return create_app(
        gaia_application=GaiaApplication.from_config(Path(__file__).parent / "gaia.yaml")
    )
