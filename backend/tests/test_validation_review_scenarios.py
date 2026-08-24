import pytest

from backend.tests.validation_fixtures import (
    COMPLETE_MOTOR_PLAN,
    COMPLETE_MOTOR_SCENARIO,
    MOTOR_IO,
    SCENARIOS,
    complete_motor_context,
    complete_pump_context,
    io_point,
    monitoring_context,
    validation_context,
)
from backend.validation import RiskLevel, build_default_engine


def _existing_scenario(name: str):
    return next(case.context for case in SCENARIOS if case.name == name)


_NO_ESTOP_PLAN = COMPLETE_MOTOR_PLAN.replace(
    "急停具有最高优先级，触发后立即停止并切断输出，必须人工复位。急停报警。",
    "方案明确未设置急停保护。",
)
_NO_OVERLOAD_PLAN = COMPLETE_MOTOR_PLAN.replace(
    "热继电器提供过载保护，过载时停止并报警。",
    "方案明确没有过载保护，也未设置过载报警。",
)
_REVERSING_SCENARIO = (
    "三相异步电机正转和反转，启动按钮、停止按钮、急停按钮、热继电器、运行反馈和报警灯。"
)
_REVERSING_INTERLOCK_PLAN = (
    COMPLETE_MOTOR_PLAN + "正转与反转设置独立的硬件和程序互锁。"
)
_VALVE_IO = (
    io_point("I0.0", "启动按钮", "DI", "启动按钮"),
    io_point("I0.1", "停止按钮", "DI", "停止按钮"),
    io_point("I0.2", "急停按钮", "DI", "急停按钮"),
    io_point("I0.3", "开到位反馈", "DI", "阀门开到位限位"),
    io_point("Q0.0", "阀门动作", "DO", "电动阀门"),
    io_point("Q0.1", "报警输出", "DO", "报警灯"),
)
_VALVE_COMPLETE_PLAN = (
    "监视阀门开到位反馈。"
    "急停输入具有最高优先级，急停触发后立即切断输出，急停后必须人工复位并报警。"
    "阀门动作启动计时，到位超时后停止阀门并报警。"
    "阀门故障报警，反馈异常报警。"
    "阀门故障时阀门进入安全位置。"
)


REVIEW_SCENARIOS = (
    (
        "完整电机启停保护方案",
        complete_motor_context(),
        (),
        0,
        RiskLevel.LOW,
    ),
    (
        "明确写着未设置急停的方案",
        validation_context(
            scenario_text="三相异步电机，启动按钮、停止按钮、热继电器、运行反馈和报警灯。",
            plan_text=_NO_ESTOP_PLAN,
            io_points=tuple(point for point in MOTOR_IO if point.signal_name != "急停按钮"),
        ),
        ("EMERGENCY_STOP_MISSING",),
        30,
        RiskLevel.CRITICAL,
    ),
    (
        "明确写着没有过载保护的方案",
        validation_context(
            scenario_text=COMPLETE_MOTOR_SCENARIO,
            plan_text=_NO_OVERLOAD_PLAN,
            io_points=MOTOR_IO,
        ),
        (
            "MOTOR_OVERLOAD_PROTECTION_MISSING",
            "ALARM_COVERAGE_INCOMPLETE",
        ),
        23,
        RiskLevel.HIGH,
    ),
    (
        "正反转且具有互锁的方案",
        validation_context(
            scenario_text=_REVERSING_SCENARIO,
            plan_text=_REVERSING_INTERLOCK_PLAN,
            io_points=MOTOR_IO,
        ),
        (),
        0,
        RiskLevel.LOW,
    ),
    (
        "正反转但无互锁的方案",
        _existing_scenario("正反转无互锁"),
        ("MUTUAL_INTERLOCK_MISSING",),
        30,
        RiskLevel.CRITICAL,
    ),
    (
        "水泵具备低液位防干转",
        complete_pump_context(),
        (),
        0,
        RiskLevel.LOW,
    ),
    (
        "水泵缺少防干转",
        _existing_scenario("水泵缺少低液位保护"),
        ("PUMP_DRY_RUN_PROTECTION_MISSING",),
        30,
        RiskLevel.CRITICAL,
    ),
    (
        "阀门具备到位反馈和超时保护",
        validation_context(
            scenario_text="电动阀门，急停按钮、开到位反馈和报警灯。",
            plan_text=_VALVE_COMPLETE_PLAN,
            io_points=_VALVE_IO,
        ),
        (),
        0,
        RiskLevel.LOW,
    ),
    (
        "纯监测场景",
        monitoring_context(),
        (),
        0,
        RiskLevel.LOW,
    ),
    (
        "同时存在多个真实 critical 问题",
        _existing_scenario("多个 critical 问题同时存在"),
        (
            "EMERGENCY_STOP_MISSING",
            "MUTUAL_INTERLOCK_MISSING",
            "SAFE_STATE_UNDEFINED",
        ),
        90,
        RiskLevel.CRITICAL,
    ),
)


@pytest.mark.parametrize(
    ("name", "context", "expected_issue_ids", "expected_score", "expected_level"),
    REVIEW_SCENARIOS,
    ids=[case[0] for case in REVIEW_SCENARIOS],
)
def test_review_scenario_matches_expected_rules_and_risk(
    name,
    context,
    expected_issue_ids,
    expected_score,
    expected_level,
) -> None:
    report = build_default_engine().validate(context)

    assert tuple(result.rule_id for result in report.issues) == expected_issue_ids, name
    assert report.risk_score == expected_score, name
    assert report.risk_level == expected_level, name
    assert all(result.evidence for result in report.issues), name
