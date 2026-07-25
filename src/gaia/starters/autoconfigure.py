"""Deterministic Starter assembly with inspectable match reports."""

from __future__ import annotations

from dataclasses import dataclass

from gaia.components.core import ComponentRegistry
from gaia.config.models import GaiaApplicationConfig, ImportedStarterRef
from gaia.starters.core import ConditionReport, GaiaStarter, evaluate_conditions


@dataclass(frozen=True)
class AutoConfigurationReport:
    positive: tuple[ConditionReport, ...]
    negative: tuple[ConditionReport, ...]


class AutoConfigurator:
    def __init__(self, starters: dict[str, GaiaStarter]) -> None:
        self._starters = starters

    def configure(
        self,
        config: GaiaApplicationConfig,
        registry: ComponentRegistry | None = None,
        *,
        starter_ids: tuple[str, ...] | None = None,
    ) -> tuple[ComponentRegistry, AutoConfigurationReport]:
        target = registry or ComponentRegistry()
        positive: list[ConditionReport] = []
        negative: list[ConditionReport] = []
        selected = (
            starter_ids
            if starter_ids is not None
            else tuple(starter_id for starter_id in config.starters if isinstance(starter_id, str))
        )
        if starter_ids is None and any(
            isinstance(starter_id, ImportedStarterRef) for starter_id in config.starters
        ):
            raise ValueError("CONFIG_STARTER_IMPORT_UNRESOLVED")
        for starter_id in selected:
            starter = self._starters.get(starter_id)
            if starter is None:
                raise ValueError(f"CONFIG_STARTER_NOT_FOUND:{starter_id}")
            report = evaluate_conditions(starter, config, target)
            if report.matched:
                starter.contribute(target, config)
                positive.append(report)
            else:
                negative.append(report)
        return target, AutoConfigurationReport(tuple(positive), tuple(negative))
