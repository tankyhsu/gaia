from examples.controlled_task.runner import ControlledTaskRunner
from examples.controlled_task.starter import STARTER
from gaia.components import ComponentRegistry
from gaia.config import GaiaApplicationConfig
from gaia.starters.core import evaluate_conditions


def test_example_starter_contributes_runner_and_write_tools() -> None:
    config = GaiaApplicationConfig()
    registry = ComponentRegistry()
    report = evaluate_conditions(STARTER, config, registry)
    assert report.matched is True
    STARTER.contribute(registry, config)
    instances = registry.instantiate()
    assert isinstance(instances["controlled-task-runner"], ControlledTaskRunner)
    assert instances["controlled-task-write-tools"].names == ("set_resource_status",)
