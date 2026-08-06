"""Text templates used by Gaia project scaffolding."""

from gaia.templates.catalog import (
    BUSINESS_SCENARIO_TEMPLATES,
    COMPONENT_STARTERS,
    SCENARIO_TEMPLATES,
    ScenarioExample,
    ScenarioTemplate,
    selected_starters,
)
from gaia.templates.project import project_files, python_module_name
from gaia.templates.workflow import workflow_files

__all__ = [
    "BUSINESS_SCENARIO_TEMPLATES",
    "COMPONENT_STARTERS",
    "SCENARIO_TEMPLATES",
    "ScenarioExample",
    "ScenarioTemplate",
    "project_files",
    "python_module_name",
    "selected_starters",
    "workflow_files",
]
