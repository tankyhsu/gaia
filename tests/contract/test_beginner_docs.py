"""Keep the first-time Gaia journey concrete and connected to a real example."""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCS = _REPO_ROOT / "developer-docs"
_EXAMPLE_README = _REPO_ROOT / "examples" / "function_task" / "README.md"
_MKDOCS_CONFIG = _REPO_ROOT / "mkdocs.yml"


def test_beginner_journey_starts_with_outcomes_before_internals() -> None:
    landing = (_DOCS / "index.md").read_text()
    tutorial = (_DOCS / "getting-started.md").read_text()

    assert landing.index("Gaia 能做什么") < landing.index("推荐学习顺序")
    assert "make demo" in tutorial
    assert "examples/function_task" in tutorial
    assert "不需要先理解 Runtime" in tutorial


def test_runtime_profiles_keep_commands_ports_and_data_owners_explicit() -> None:
    profiles = (_DOCS / "runtime-profiles.md").read_text()
    developer_guide = (_DOCS / "developer-guide.md").read_text()
    showcase = (_DOCS / "showcase.md").read_text()
    mechanisms = (_DOCS / "mechanisms.md").read_text()
    production_like = (_DOCS / "production-like.md").read_text()

    for mode in ("in_process", "make demo", "make dev-full", "make prod-up", "Helm/Kubernetes"):
        assert mode in profiles
    for port in ("4180/#demo", "8010", "4173", "4181", "8088"):
        assert port in profiles

    assert "scripts/temporal_dev_server.py" in developer_guide
    assert "make infra-up" in developer_guide
    assert "并不包含 Temporal" in developer_guide
    assert "依赖完整时尝试启动" in showcase
    assert "列表不读取 Temporal Visibility" in mechanisms
    assert "Gaia `/v1/runs` 审计投影" in production_like


def test_panorama_names_every_system_boundary() -> None:
    panorama = (_DOCS / "architecture.md").read_text()

    for layer in ("接入层", "控制层", "编排层", "业务扩展层", "基础设施层"):
        assert layer in panorama

    for owner in (
        "Gaia PostgreSQL",
        "Temporal PostgreSQL",
        "LangGraph",
        "Langfuse",
        "客户业务系统",
    ):
        assert owner in panorama

    assert "Gaia 能保证的" in panorama
    assert "Gaia 不能单独保证的" in panorama
    assert "Runtime Safety 与 Integration Sandbox" in panorama
    assert "不是任意代码执行容器" in panorama


def test_minimal_example_has_a_first_time_reading_guide() -> None:
    example = _EXAMPLE_README.read_text()

    for filename in ("flows.py", "tools.py", "gaia.yaml", "app.py"):
        assert filename in example

    assert "不要从复制 Runtime" in example
    assert "20 分钟走通 Gaia" in example


def test_core_diagrams_use_responsive_native_canvases() -> None:
    styles = (_DOCS / "stylesheets" / "extra.css").read_text()
    diagram_docs = [
        _DOCS / "index.md",
        _DOCS / "getting-started.md",
        _DOCS / "architecture.md",
    ]

    assert all("```mermaid" not in path.read_text() for path in diagram_docs)
    assert ".gaia-architecture" in styles
    assert ".gaia-module-map" in styles
    assert ".gaia-journey" in styles


def test_case_studies_map_concrete_behavior_to_framework_mechanisms() -> None:
    guide = (_DOCS / "try-it.md").read_text()
    screenshot = _DOCS / "assets" / "demo-console-overview.png"
    recording = _DOCS / "assets" / "business-builder-walkthrough.gif"

    assert screenshot.stat().st_size > 50_000
    assert recording.stat().st_size > 100_000
    assert "business-builder-walkthrough.gif" in guide
    assert "Case 1：员工请假办理" in guide
    assert "Case 2：新员工权限开通" in guide
    assert "Case 3：员工制度与个人假期问答" in guide
    assert "对应的 Gaia 能力" in guide
    assert "这些 Case 不证明什么" in guide
    assert not (_DOCS / "business-guide.md").exists()

    positioning = "\n".join(
        [
            (_REPO_ROOT / "mkdocs.yml").read_text(),
            (_REPO_ROOT / "README.md").read_text(),
            (_DOCS / "index.md").read_text(),
        ]
    )
    assert "业务构建者" not in positioning
