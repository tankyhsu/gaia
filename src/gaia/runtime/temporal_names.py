"""Stable names shared by Gaia Temporal clients, Workflows, and Activities."""

from temporalio.common import SearchAttributeKey

GAIA_RUNTIME_WORKFLOW = "gaia.runtime"
GAIA_SCENARIO_ACTIVITY = "gaia.runtime.run_scenario"
GAIA_COMMAND_ACTIVITY = "gaia.runtime.execute_command"
GAIA_AUDIT_ACTIVITY = "gaia.runtime.record_audit"

GAIA_ORGANIZATION_SEARCH_ATTRIBUTE = SearchAttributeKey.for_keyword(
    "GaiaOrganization"
)
GAIA_SCENARIO_SEARCH_ATTRIBUTE = SearchAttributeKey.for_keyword("GaiaScenarioId")
GAIA_STATUS_SEARCH_ATTRIBUTE = SearchAttributeKey.for_keyword("GaiaRunStatus")
