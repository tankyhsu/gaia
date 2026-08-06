"""Small, opinionated catalog used by ``gaia init``."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScenarioExample:
    """A business-facing reference application for one scenario template."""

    name: str
    description: str
    path: str


@dataclass(frozen=True)
class ScenarioTemplate:
    template_id: str
    name: str
    description: str
    recommended_components: tuple[str, ...] = ()
    example: ScenarioExample | None = None


SCENARIO_TEMPLATES: dict[str, ScenarioTemplate] = {
    "basic": ScenarioTemplate(
        template_id="basic",
        name="最小技术骨架",
        description="用于验证项目结构、模型调用和测试链路，不作为独立业务应用。",
    ),
    "knowledge": ScenarioTemplate(
        template_id="knowledge",
        name="基于企业知识回答",
        description="适合导入企业资料、按权限检索，并在回答中标明信息来源。",
        recommended_components=("rag",),
        example=ScenarioExample(
            name="员工手册",
            description="根据企业制度回答员工问题，并展示可核对的条款来源。",
            path="/#handbook",
        ),
    ),
    "approval": ScenarioTemplate(
        template_id="approval",
        name="连接并操作业务系统",
        description="适合调用企业接口执行操作，并在关键步骤加入人工确认。",
        example=ScenarioExample(
            name="入职权限开通",
            description="生成岗位权限草案，经规则校验和 IT 授权后再写入 IAM。",
            path="/#onboarding",
        ),
    ),
}

BUSINESS_SCENARIO_TEMPLATES: dict[str, ScenarioTemplate] = {
    template_id: SCENARIO_TEMPLATES[template_id] for template_id in ("knowledge", "approval")
}


COMPONENT_STARTERS: dict[str, tuple[str, str]] = {
    "model": ("外部模型", "model-openai-compatible"),
    "prompt-registry": ("Prompt Registry", "prompt-postgres"),
    "rag": ("知识检索", "rag-postgres"),
    "cache": ("Redis 缓存", "cache-redis"),
    "outbox": ("事务消息", "outbox-postgres"),
}


def selected_starters(
    template_id: str,
    components: tuple[str, ...] = (),
    explicit_starters: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Resolve template and component choices to a dependency-complete starter list."""

    from gaia.config import GaiaApplicationConfig
    from gaia.starters import BUILTIN_STARTERS, STARTER_DEPENDENCIES

    template = SCENARIO_TEMPLATES[template_id]
    requested_components = (*template.recommended_components, *components)
    requested = [
        *(COMPONENT_STARTERS[component_id][1] for component_id in requested_components),
        *explicit_starters,
    ]
    selected = [str(starter) for starter in GaiaApplicationConfig().starters]

    def add(starter_id: str) -> None:
        for dependency in STARTER_DEPENDENCIES.get(starter_id, ()):
            add(dependency)
        capabilities = set(BUILTIN_STARTERS[starter_id].descriptor.capabilities)
        selected[:] = [
            current
            for current in selected
            if not capabilities.intersection(BUILTIN_STARTERS[current].descriptor.capabilities)
        ]
        selected.append(starter_id)

    for starter_id in requested:
        add(starter_id)
    return tuple(selected)
