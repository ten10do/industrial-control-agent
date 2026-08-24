from dataclasses import dataclass

from backend.validation import (
    RiskLevel,
    RuleStatus,
    ValidationContext,
    ValidationIOPoint,
    build_default_engine,
)


def io_point(
    address: str,
    signal_name: str,
    signal_type: str,
    device: str,
    description: str = "",
) -> ValidationIOPoint:
    return ValidationIOPoint(
        address=address,
        signal_name=signal_name,
        signal_type=signal_type,
        device=device,
        description=description,
    )


def validation_context(
    *,
    scenario_text: str = "",
    plan_text: str = "",
    io_points: tuple[ValidationIOPoint, ...] = (),
    structured_io_available: bool = True,
    request_id: str = "validation-test-1",
    source: str = "validate",
    **fields: str,
) -> ValidationContext:
    return ValidationContext(
        source=source,
        request_id=request_id,
        scenario_text=scenario_text,
        plan_text=plan_text,
        io_points=io_points,
        structured_io_available=structured_io_available,
        **fields,
    )


def default_rule_result(rule_id: str, context: ValidationContext):
    rule = next(rule for rule in build_default_engine().rules if rule.rule_id == rule_id)
    return rule.validate(context)


def issue_ids(context: ValidationContext) -> tuple[str, ...]:
    report = build_default_engine().validate(context)
    return tuple(result.rule_id for result in report.issues)


MOTOR_IO = (
    io_point("I0.0", "启动按钮", "DI", "启动按钮", "启动命令"),
    io_point("I0.1", "停止按钮", "DI", "停止按钮", "停止命令"),
    io_point("I0.2", "急停按钮", "DI", "急停按钮", "紧急停止输入"),
    io_point("I0.3", "过载保护", "DI", "热继电器", "过载保护触点"),
    io_point("I0.4", "电机运行反馈", "DI", "接触器反馈", "运行状态确认"),
    io_point("Q0.0", "电机运行", "DO", "电机接触器", "驱动电机"),
    io_point("Q0.1", "故障报警", "DO", "报警灯", "异常报警输出"),
)

COMPLETE_MOTOR_SCENARIO = (
    "三相异步电机，启动按钮、停止按钮、急停按钮、热继电器、接触器运行反馈和故障报警灯。"
)
COMPLETE_MOTOR_PLAN = (
    "启动条件满足后运行，停止条件有效时复位输出并停止。监视电机运行状态和电机运行反馈。"
    "急停具有最高优先级，触发后立即停止并切断输出，必须人工复位。急停报警。"
    "热继电器提供过载保护，过载时停止并报警。电机故障报警，反馈异常报警。"
    "故障时所有重要输出进入默认停止的安全状态。"
)


def complete_motor_context(**updates: str) -> ValidationContext:
    values = {
        "scenario_text": COMPLETE_MOTOR_SCENARIO,
        "plan_text": COMPLETE_MOTOR_PLAN,
        "io_points": MOTOR_IO,
    }
    values.update(updates)
    return validation_context(**values)


MONITORING_IO = (
    io_point("AI0", "温度测量", "AI", "温度变送器", "4-20mA 模拟量"),
    io_point("AI1", "压力测量", "AI", "压力变送器", "4-20mA 模拟量"),
)
MONITORING_SCENARIO = "温度与压力采集监测"
MONITORING_PLAN = "连续采集温度与压力模拟量，越限时生成监测告警。"


def monitoring_context(**updates: str) -> ValidationContext:
    values = {
        "scenario_text": MONITORING_SCENARIO,
        "plan_text": MONITORING_PLAN,
        "io_points": MONITORING_IO,
    }
    values.update(updates)
    return validation_context(**values)


PUMP_IO = (
    io_point("I0.0", "启动按钮", "DI", "启动按钮"),
    io_point("I0.1", "停止按钮", "DI", "停止按钮"),
    io_point("I0.2", "急停按钮", "DI", "急停按钮"),
    io_point("I0.3", "低液位", "DI", "低液位开关"),
    io_point("I0.4", "过载保护", "DI", "热继电器"),
    io_point("I0.5", "水泵运行反馈", "DI", "接触器反馈"),
    io_point("Q0.0", "水泵运行", "DO", "水泵接触器"),
    io_point("Q0.1", "报警输出", "DO", "报警灯"),
)
COMPLETE_PUMP_SCENARIO = "水塔水泵，低液位开关、急停按钮、热继电器、运行反馈和报警灯。"
COMPLETE_PUMP_PLAN = (
    "启动条件满足后水泸运行，停止条件有效时复位输出并停止，监视水泵运行状态和水泵运行反馈。"
    "急停最高优先级，触发后立即停止并切断输出，人工复位；急停报警。"
    "热继电器提供过载保护，过载停止并报警。低液位检测触发防干转，缺水时停止水泵并报警。"
    "电机故障报警，反馈异常报警，液位过低报警。水泵故障时水泵停止并进入安全状态。"
)


def complete_pump_context(**updates: str) -> ValidationContext:
    values = {
        "scenario_text": COMPLETE_PUMP_SCENARIO,
        "plan_text": COMPLETE_PUMP_PLAN,
        "io_points": PUMP_IO,
    }
    values.update(updates)
    return validation_context(**values)


@dataclass(frozen=True)
class ScenarioCase:
    name: str
    context: ValidationContext
    expected_score: int
    expected_level: RiskLevel
    expected_issue_ids: tuple[str, ...]


_NO_ESTOP_SCENARIO = "三相异步电机，启动按钮、停止按钮、热继电器、运行反馈和报警灯。"
_NO_ESTOP_PLAN = (
    "启动条件满足后运行，停止条件有效时复位输出并停止，监视电机运行状态和电机运行反馈。"
    "热继电器提供过载保护，过载时停止并报警。电机故障报警，反馈异常报警。"
    "电机故障时电机停止并进入安全状态。"
)
_NO_ESTOP_IO = tuple(point for point in MOTOR_IO if point.signal_name != "急停按钮")

_REVERSING_SCENARIO = (
    "三相异步电机正转和反转，启动按钮、停止按钮、急停按钮、热继电器、运行反馈和报警灯。"
)
_REVERSING_PLAN = COMPLETE_MOTOR_PLAN.replace(
    "启动条件满足后运行",
    "启动条件满足后可正转或反转运行",
)

_DRY_RUN_MISSING_SCENARIO = "水塔水泵，高液位开关、急停按钮、热继电器、运行反馈和报警灯。"
_DRY_RUN_MISSING_PLAN = (
    "启动条件满足后水泸运行，停止条件有效时复位输出并停止，监视水泵运行状态和水泵运行反馈。"
    "急停最高优先级，触发后立即停止并切断输出，人工复位；急停报警。"
    "热继电器提供过载保护，过载停止并报警。高液位报警。"
    "电机故障报警，反馈异常报警。水泵故障时水泵停止并进入安全状态。"
)

_VALVE_SCENARIO = "电动阀门，启动按钮、停止按钮、急停按钮、开到位反馈和报警灯。"
_VALVE_TIMEOUT_PLAN = (
    "启动条件满足后动作，停止条件有效时复位输出并停止，监视阀门状态和阀门开到位反馈。"
    "急停最高优先级，触发后立即停止并切断输出，人工复位；急停报警。"
    "阀门故障报警，反馈异常报警，到位超时报警。阀门故障时阀门进入安全位置。"
)
_VALVE_IO = (
    io_point("I0.0", "启动按钮", "DI", "启动按钮"),
    io_point("I0.1", "停止按钮", "DI", "停止按钮"),
    io_point("I0.2", "急停按钮", "DI", "急停按钮"),
    io_point("I0.3", "开到位反馈", "DI", "开到位限位"),
    io_point("Q0.0", "阀门动作", "DO", "电动阀门"),
    io_point("Q0.1", "报警输出", "DO", "报警灯"),
)

_MODE_SCENARIO = COMPLETE_MOTOR_SCENARIO + " 系统具有自动模式和手动模式。"
_MODE_PLAN = COMPLETE_MOTOR_PLAN + " 通过模式选择开关切换，手动权限由授权人员控制。"

_DUPLICATE_ADDRESS_IO = (
    MONITORING_IO[0],
    MONITORING_IO[1].model_copy(update={"address": "AI0"}),
)

_MULTI_CRITICAL_SCENARIO = (
    "三相异步电机正转和反转，启动按钮、停止按钮、热继电器、运行反馈和报警灯。"
)
_MULTI_CRITICAL_PLAN = (
    "启动条件满足后正转或反转运行，停止条件有效时复位输出并停止。"
    "监视电机运行状态和电机运行反馈。热继电器提供过载保护，过载停止并报警。"
    + ("定期检查控制回路与接线状态。" * 12)
    + "电机故障报警，反馈异常报警。"
)


SCENARIOS: tuple[ScenarioCase, ...] = (
    ScenarioCase(
        "正常电机启停",
        complete_motor_context(),
        0,
        RiskLevel.LOW,
        (),
    ),
    ScenarioCase(
        "缺少急停的电机控制",
        validation_context(
            scenario_text=_NO_ESTOP_SCENARIO,
            plan_text=_NO_ESTOP_PLAN,
            io_points=_NO_ESTOP_IO,
        ),
        30,
        RiskLevel.CRITICAL,
        ("EMERGENCY_STOP_MISSING",),
    ),
    ScenarioCase(
        "正反转无互锁",
        validation_context(
            scenario_text=_REVERSING_SCENARIO,
            plan_text=_REVERSING_PLAN,
            io_points=MOTOR_IO,
        ),
        30,
        RiskLevel.CRITICAL,
        ("MUTUAL_INTERLOCK_MISSING",),
    ),
    ScenarioCase(
        "水泵缺少低液位保护",
        validation_context(
            scenario_text=_DRY_RUN_MISSING_SCENARIO,
            plan_text=_DRY_RUN_MISSING_PLAN,
            io_points=PUMP_IO,
        ),
        30,
        RiskLevel.CRITICAL,
        ("PUMP_DRY_RUN_PROTECTION_MISSING",),
    ),
    ScenarioCase(
        "阀门缺少到位超时",
        validation_context(
            scenario_text=_VALVE_SCENARIO,
            plan_text=_VALVE_TIMEOUT_PLAN,
            io_points=_VALVE_IO,
        ),
        15,
        RiskLevel.HIGH,
        ("ACTION_TIMEOUT_PROTECTION_MISSING",),
    ),
    ScenarioCase(
        "自动手动模式无互斥",
        validation_context(
            scenario_text=_MODE_SCENARIO,
            plan_text=_MODE_PLAN,
            io_points=MOTOR_IO,
        ),
        15,
        RiskLevel.HIGH,
        ("MODE_INTERLOCK_MISSING",),
    ),
    ScenarioCase(
        "重复 I/O 地址",
        monitoring_context(io_points=_DUPLICATE_ADDRESS_IO),
        15,
        RiskLevel.HIGH,
        ("IO_DUPLICATE_ADDRESS",),
    ),
    ScenarioCase(
        "纯监测场景",
        monitoring_context(),
        0,
        RiskLevel.LOW,
        (),
    ),
    ScenarioCase(
        "完整保护方案",
        complete_pump_context(),
        0,
        RiskLevel.LOW,
        (),
    ),
    ScenarioCase(
        "多个 critical 问题同时存在",
        validation_context(
            scenario_text=_MULTI_CRITICAL_SCENARIO,
            plan_text=_MULTI_CRITICAL_PLAN,
            io_points=MOTOR_IO,
        ),
        90,
        RiskLevel.CRITICAL,
        (
            "EMERGENCY_STOP_MISSING",
            "MUTUAL_INTERLOCK_MISSING",
            "SAFE_STATE_UNDEFINED",
        ),
    ),
)


def assert_only_expected_issues(case: ScenarioCase) -> None:
    report = build_default_engine().validate(case.context)
    assert report.risk_score == case.expected_score
    assert report.risk_level == case.expected_level
    assert tuple(result.rule_id for result in report.issues) == case.expected_issue_ids
    assert all(
        result.status in (RuleStatus.WARNING, RuleStatus.FAILED)
        for result in report.issues
    )
