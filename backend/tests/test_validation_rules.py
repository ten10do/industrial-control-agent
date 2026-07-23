from backend.validation import RuleStatus, Severity, build_default_engine
from backend.tests.validation_fixtures import (
    default_rule_result,
    io_point,
    monitoring_context,
    validation_context,
)


EXPECTED_RULES = (
    ("IO_DUPLICATE_ADDRESS", Severity.HIGH),
    ("IO_DUPLICATE_NAME", Severity.MEDIUM),
    ("IO_TYPE_MISMATCH", Severity.HIGH),
    ("START_STOP_INCOMPLETE", Severity.HIGH),
    ("EMERGENCY_STOP_MISSING", Severity.CRITICAL),
    ("MOTOR_OVERLOAD_PROTECTION_MISSING", Severity.HIGH),
    ("MUTUAL_INTERLOCK_MISSING", Severity.CRITICAL),
    ("ACTUATOR_FEEDBACK_MISSING", Severity.MEDIUM),
    ("ALARM_COVERAGE_INCOMPLETE", Severity.MEDIUM),
    ("PUMP_DRY_RUN_PROTECTION_MISSING", Severity.CRITICAL),
    ("ACTION_TIMEOUT_PROTECTION_MISSING", Severity.HIGH),
    ("MODE_INTERLOCK_MISSING", Severity.HIGH),
    ("SAFE_STATE_UNDEFINED", Severity.CRITICAL),
    ("IO_TABLE_INCOMPLETE", Severity.HIGH),
)


def test_default_engine_has_all_fourteen_rules_in_fixed_order() -> None:
    rules = build_default_engine().rules

    assert tuple((rule.rule_id, rule.default_severity) for rule in rules) == EXPECTED_RULES


def test_duplicate_io_address_is_detected_after_normalization() -> None:
    context = validation_context(
        io_points=(
            io_point(" i0.0 ", "启动按钮", "DI", "启动按钮"),
            io_point("I0.0", "停止按钮", "DI", "停止按钮"),
        )
    )

    result = default_rule_result("IO_DUPLICATE_ADDRESS", context)

    assert result.status == RuleStatus.FAILED
    assert "I0.0" in result.evidence
    assert result.related_items == ["启动按钮", "停止按钮"]


def test_duplicate_io_name_is_detected_after_case_and_separator_normalization() -> None:
    context = validation_context(
        io_points=(
            io_point("I0.0", "Pump_Run", "DI", "运行反馈"),
            io_point("I0.1", " pump-run ", "DI", "备用反馈"),
        )
    )

    result = default_rule_result("IO_DUPLICATE_NAME", context)

    assert result.status == RuleStatus.FAILED
    assert "Pump_Run" in result.evidence
    assert "pump-run" in result.evidence


def test_input_device_assigned_to_output_is_detected() -> None:
    context = validation_context(
        io_points=(io_point("Q0.0", "急停按钮", "DO", "急停按钮"),)
    )

    result = default_rule_result("IO_TYPE_MISMATCH", context)

    assert result.status == RuleStatus.FAILED
    assert "急停按钮" in result.evidence
    assert "actual DO" not in result.evidence


def test_normal_io_table_passes_all_io_consistency_rules() -> None:
    context = validation_context(
        io_points=(
            io_point("I0.0", "启动按钮", "DI", "启动按钮"),
            io_point("Q0.0", "电机运行", "DO", "电机接触器"),
        )
    )

    statuses = {
        rule_id: default_rule_result(rule_id, context).status
        for rule_id in (
            "IO_DUPLICATE_ADDRESS",
            "IO_DUPLICATE_NAME",
            "IO_TYPE_MISMATCH",
            "IO_TABLE_INCOMPLETE",
        )
    }

    assert statuses == {
        "IO_DUPLICATE_ADDRESS": RuleStatus.PASSED,
        "IO_DUPLICATE_NAME": RuleStatus.PASSED,
        "IO_TYPE_MISMATCH": RuleStatus.PASSED,
        "IO_TABLE_INCOMPLETE": RuleStatus.PASSED,
    }


def test_empty_io_table_is_detected() -> None:
    result = default_rule_result(
        "IO_TABLE_INCOMPLETE",
        validation_context(io_points=(), structured_io_available=True),
    )

    assert result.status == RuleStatus.FAILED
    assert "为空" in result.message


def test_incomplete_io_row_is_detected() -> None:
    context = validation_context(
        io_points=(io_point("", "", "unknown", "", ""),)
    )

    result = default_rule_result("IO_TABLE_INCOMPLETE", context)

    assert result.status == RuleStatus.FAILED
    assert "地址" in result.evidence
    assert "点位名称" in result.evidence
    assert "有效信号类型" in result.evidence
    assert "设备名称" in result.evidence


def test_analog_signal_declared_as_digital_is_detected() -> None:
    context = validation_context(
        io_points=(
            io_point(
                "I0.0",
                "温度测量",
                "DI",
                "温度变送器",
                "4-20mA 模拟量输入",
            ),
        )
    )

    result = default_rule_result("IO_TYPE_MISMATCH", context)

    assert result.status == RuleStatus.FAILED
    assert "analog" in result.evidence


def test_start_stop_incomplete_is_detected_for_motor() -> None:
    context = validation_context(
        scenario_text="电机控制",
        plan_text="启动条件满足后运行。",
    )

    result = default_rule_result("START_STOP_INCOMPLETE", context)

    assert result.status == RuleStatus.FAILED
    assert "停止条件" in result.evidence
    assert "运行状态或反馈" in result.evidence


def test_motion_equipment_without_emergency_stop_is_detected() -> None:
    context = validation_context(
        scenario_text="输送带电机",
        plan_text="启动后运行，停止按钮触发后复位输出。",
    )

    result = default_rule_result("EMERGENCY_STOP_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert "急停输入" in result.evidence


def test_emergency_stop_is_not_applicable_to_monitoring_only_context() -> None:
    result = default_rule_result("EMERGENCY_STOP_MISSING", monitoring_context())

    assert result.status == RuleStatus.NOT_APPLICABLE


def test_motor_without_overload_protection_source_is_detected() -> None:
    context = validation_context(
        scenario_text="三相异步电机",
        plan_text="过载时停止并报警，但未配置保护器件。",
    )

    result = default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert "保护" in result.message


def test_pump_without_dry_run_protection_is_detected() -> None:
    context = validation_context(
        scenario_text="水塔和补水泵",
        plan_text="水泵按启动和停止命令运行。",
    )

    result = default_rule_result("PUMP_DRY_RUN_PROTECTION_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert "防干转逻辑" in result.evidence


def test_valve_without_action_timeout_protection_is_detected() -> None:
    context = validation_context(
        scenario_text="电动阀门和开到位反馈",
        plan_text="发出开阀命令后等待到位反馈。",
    )

    result = default_rule_result("ACTION_TIMEOUT_PROTECTION_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert "动作计时" in result.evidence
    assert "超时报警" in result.evidence


def test_mutually_exclusive_outputs_without_interlock_are_detected() -> None:
    context = validation_context(
        scenario_text="电机正转和反转",
        plan_text="正转按钮控制正转，反转按钮控制反转。",
    )

    result = default_rule_result("MUTUAL_INTERLOCK_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert result.related_items == ["正转/反转"]


def test_important_actuator_without_feedback_returns_warning() -> None:
    context = validation_context(
        scenario_text="水泵控制",
        plan_text="启动后水泸运行，停止后关闭输出。",
    )

    result = default_rule_result("ACTUATOR_FEEDBACK_MISSING", context)

    assert result.status == RuleStatus.WARNING
    assert result.severity == Severity.MEDIUM


def test_missing_alarm_coverage_returns_warning_with_missing_types() -> None:
    context = validation_context(
        scenario_text="水箱水泵和液位传感器",
        plan_text="仅配置过载报警。",
    )

    result = default_rule_result("ALARM_COVERAGE_INCOMPLETE", context)

    assert result.status == RuleStatus.WARNING
    assert "液位异常" in result.related_items
    assert "传感器异常" in result.related_items


def test_auto_manual_modes_without_exclusion_are_detected() -> None:
    context = validation_context(
        scenario_text="电机具有自动模式",
        plan_text="也可手动操作，通过模式选择开关切换，手动权限由授权人员控制。",
    )

    result = default_rule_result("MODE_INTERLOCK_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert "模式互锁" in result.evidence
    assert "禁止同时生效" in result.evidence


def test_important_output_without_safe_default_state_is_detected() -> None:
    context = validation_context(
        scenario_text="加热器控制",
        plan_text="温度低时开启加热器。",
    )

    result = default_rule_result("SAFE_STATE_UNDEFINED", context)

    assert result.status == RuleStatus.FAILED
    assert result.severity == Severity.CRITICAL


def test_negated_emergency_stop_details_do_not_count_as_protection() -> None:
    context = validation_context(
        scenario_text="电机控制",
        plan_text="未设置急停，无法切断输出，急停没有最高优先级，也无人工复位。",
    )

    result = default_rule_result("EMERGENCY_STOP_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert "急停输入" in result.evidence
    assert "急停后输出断开" in result.evidence
    assert "急停优先级" in result.evidence
    assert "复位说明" in result.evidence


def test_negated_interlock_does_not_count_as_protection() -> None:
    context = validation_context(
        scenario_text="电机正转和反转",
        plan_text="正转和反转输出均已定义，但未设置互锁。",
    )

    result = default_rule_result("MUTUAL_INTERLOCK_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert result.related_items == ["正转/反转"]


def test_negated_safe_state_does_not_pass() -> None:
    context = validation_context(
        scenario_text="加热器控制",
        plan_text="故障处理尚未定义安全状态，也未设置加热器关闭动作。",
    )

    result = default_rule_result("SAFE_STATE_UNDEFINED", context)

    assert result.status == RuleStatus.FAILED


def test_monitor_only_motor_makes_control_and_safety_rules_not_applicable() -> None:
    context = validation_context(
        scenario_text="仅监测电机状态，不控制电机",
        plan_text="采集运行状态并显示趋势。",
    )

    statuses = {
        rule_id: default_rule_result(rule_id, context).status
        for rule_id in (
            "START_STOP_INCOMPLETE",
            "EMERGENCY_STOP_MISSING",
            "MOTOR_OVERLOAD_PROTECTION_MISSING",
            "ACTUATOR_FEEDBACK_MISSING",
            "SAFE_STATE_UNDEFINED",
        )
    }

    assert set(statuses.values()) == {RuleStatus.NOT_APPLICABLE}


def test_valve_open_close_control_does_not_require_motor_start_stop_terms() -> None:
    context = validation_context(
        scenario_text="电动阀门开关控制",
        plan_text="开阀命令驱动阀门，到位后停止；关阀命令驱动阀门，到位后停止。",
    )

    result = default_rule_result("START_STOP_INCOMPLETE", context)

    assert result.status == RuleStatus.NOT_APPLICABLE
