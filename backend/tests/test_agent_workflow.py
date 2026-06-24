from backend.agent_core import generate_control_plan, optimize_control_plan
from backend.llm_client import FakeLLMClient
from backend.schemas import GenerateRequest, OptimizeRequest


SAFETY_NOTICE_FRAGMENT = "专业工程师复核"


def test_generate_control_plan_returns_stable_fields() -> None:
    request = GenerateRequest(
        control_object="水塔水位控制系统",
        input_devices="高液位传感器、低液位传感器、启动按钮、停止按钮",
        output_devices="水泵、运行指示灯、故障报警灯",
        control_requirements="低液位启动水泵，高液位停止水泵，传感器异常时报警。",
    )

    response = generate_control_plan(request, FakeLLMClient())

    assert set(response.model_dump()) == {
        "requirement_analysis",
        "io_table",
        "control_logic",
        "safety_design",
        "ladder_idea",
        "report_markdown",
        "safety_notice",
    }
    assert isinstance(response.io_table, list)
    assert response.io_table
    assert response.report_markdown.strip()
    assert SAFETY_NOTICE_FRAGMENT in response.safety_notice
    assert response.safety_notice in response.report_markdown


def test_optimize_control_plan_returns_stable_fields() -> None:
    request = OptimizeRequest(
        original_report="# 原始方案\n\n使用液位信号控制水泵启停。",
        optimize_requirement="补充传感器故障保护和调试步骤。",
    )

    response = optimize_control_plan(request, FakeLLMClient())

    assert set(response.model_dump()) == {
        "optimized_report",
        "change_summary",
        "safety_notice",
    }
    assert response.optimized_report.strip()
    assert response.change_summary.strip()
    assert SAFETY_NOTICE_FRAGMENT in response.safety_notice
    assert response.safety_notice in response.optimized_report
