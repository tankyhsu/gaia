"""Text templates used by Gaia project scaffolding."""

from gaia.templates.catalog import (
    COMPONENT_STARTERS,
    SCENARIO_TEMPLATES,
    ScenarioTemplate,
    selected_starters,
)
from gaia.templates.project import project_files, python_module_name
from gaia.templates.workflow import workflow_files

__all__ = [
    "COMPONENT_STARTERS",
    "SCENARIO_TEMPLATES",
    "ScenarioTemplate",
    "project_files",
    "python_module_name",
    "selected_starters",
    "workflow_files",
]
