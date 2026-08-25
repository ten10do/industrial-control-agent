from backend.tests.validation_fixtures import (
    default_rule_result,
    io_point,
    monitoring_context,
    validation_context,
)
from backend.validation import RuleStatus, Severity, build_default_engine
from backend.validation.catalog import is_monitoring_only

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


def test_second_review_missing_protection_phrases_do_not_pass() -> None:
    cases = (
        ("EMERGENCY_STOP_MISSING", "电机控制", "未设置急停"),
        (
            "MOTOR_OVERLOAD_PROTECTION_MISSING",
            "三相异步电机控制",
            "没有过载保护",
        ),
        (
            "MUTUAL_INTERLOCK_MISSING",
            "电机正转和反转控制",
            "缺少互锁",
        ),
        (
            "PUMP_DRY_RUN_PROTECTION_MISSING",
            "水箱低液位水泵控制",
            "未配置低液位停泵",
        ),
        (
            "ACTION_TIMEOUT_PROTECTION_MISSING",
            "电动阀门控制",
            "无动作超时报警",
        ),
        (
            "SAFE_STATE_UNDEFINED",
            "电机控制",
            "尚未定义安全停机状态",
        ),
    )

    for rule_id, scenario_text, plan_text in cases:
        result = default_rule_result(
            rule_id,
            validation_context(
                scenario_text=scenario_text,
                plan_text=plan_text,
            ),
        )

        assert result.status == RuleStatus.FAILED, rule_id


def test_second_review_positive_protection_phrases_pass() -> None:
    cases = (
        (
            "EMERGENCY_STOP_MISSING",
            "电机控制",
            "急停触发后立即切断所有危险输出，故障复位后方可重新启动",
        ),
        (
            "MOTOR_OVERLOAD_PROTECTION_MISSING",
            "三相异步电机控制",
            "电机配置热继电器，过载后停机并报警",
        ),
        (
            "MUTUAL_INTERLOCK_MISSING",
            "电机正转和反转控制",
            "正反转接触器采用电气和程序双重互锁",
        ),
        (
            "PUMP_DRY_RUN_PROTECTION_MISSING",
            "水箱低液位水泵控制",
            "低液位时禁止水泵启动并执行缺水报警",
        ),
        (
            "ACTION_TIMEOUT_PROTECTION_MISSING",
            "电动阀门控制",
            "阀门在限定时间内未到位时停止输出并报警",
        ),
        (
            "SAFE_STATE_UNDEFINED",
            "电机和加热器控制",
            "故障状态下电机和加热器均保持关闭",
        ),
    )

    for rule_id, scenario_text, plan_text in cases:
        result = default_rule_result(
            rule_id,
            validation_context(
                scenario_text=scenario_text,
                plan_text=plan_text,
            ),
        )

        assert result.status == RuleStatus.PASSED, rule_id


def test_second_review_protection_phrase_variants_pass() -> None:
    cases = (
        (
            "EMERGENCY_STOP_MISSING",
            "电机控制",
            "急停动作后即刻断开危险输出，手动复位后才能再次启动",
        ),
        (
            "MUTUAL_INTERLOCK_MISSING",
            "电机正转和反转控制",
            "forward/reverse contactors use a hardware interlock",
        ),
        (
            "PUMP_DRY_RUN_PROTECTION_MISSING",
            "水箱低液位水泵控制",
            "缺水时启动闭锁并报警",
        ),
        (
            "ACTION_TIMEOUT_PROTECTION_MISSING",
            "电动阀门控制",
            "阀门未在规定时间内到位则停止并告警",
        ),
        (
            "SAFE_STATE_UNDEFINED",
            "电机和加热器控制",
            "设备故障时电机和加热器全部保持停止",
        ),
    )

    for rule_id, scenario_text, plan_text in cases:
        result = default_rule_result(
            rule_id,
            validation_context(
                scenario_text=scenario_text,
                plan_text=plan_text,
            ),
        )

        assert result.status == RuleStatus.PASSED, rule_id


def test_second_review_equivalent_terms_still_respect_negation() -> None:
    cases = (
        (
            "EMERGENCY_STOP_MISSING",
            "电机控制",
            "急停触发后不立即切断所有危险输出，复位后重新启动",
        ),
        (
            "MUTUAL_INTERLOCK_MISSING",
            "电机正转和反转控制",
            "正反转未采用互锁",
        ),
        (
            "PUMP_DRY_RUN_PROTECTION_MISSING",
            "水箱低液位水泵控制",
            "低液位时未设置启动闭锁但报警",
        ),
        (
            "ACTION_TIMEOUT_PROTECTION_MISSING",
            "电动阀门控制",
            "阀门未在规定时间内到位时不停止输出且不报警",
        ),
        (
            "SAFE_STATE_UNDEFINED",
            "电机和加热器控制",
            "故障状态下电机和加热器并非均保持关闭",
        ),
    )

    for rule_id, scenario_text, plan_text in cases:
        result = default_rule_result(
            rule_id,
            validation_context(
                scenario_text=scenario_text,
                plan_text=plan_text,
            ),
        )

        assert result.status == RuleStatus.FAILED, rule_id


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


def test_negated_monitoring_only_phrase_does_not_disable_control_rules() -> None:
    context = validation_context(
        scenario_text="这不是只监测系统，需要控制电机启停。",
        plan_text="启动条件满足后运行。",
    )

    result = default_rule_result("EMERGENCY_STOP_MISSING", context)

    assert result.status == RuleStatus.FAILED


def test_negation_in_previous_sentence_does_not_negate_emergency_stop() -> None:
    context = validation_context(
        scenario_text="电机控制",
        plan_text=(
            "未配置温度传感器。"
            "急停已配置，急停触发后立即切断输出，急停具有最高优先级，急停后人工复位。"
        ),
    )

    result = default_rule_result("EMERGENCY_STOP_MISSING", context)

    assert result.status == RuleStatus.PASSED


def test_english_no_inside_normal_does_not_negate_emergency_stop() -> None:
    context = validation_context(
        scenario_text="motor control",
        plan_text=(
            "Normal emergency stop de-energize outputs; "
            "emergency stop has highest priority; "
            "emergency stop requires manual reset."
        ),
    )

    result = default_rule_result("EMERGENCY_STOP_MISSING", context)

    assert result.status == RuleStatus.PASSED


def test_unrelated_stop_and_alarm_sentences_do_not_satisfy_overload_actions() -> None:
    context = validation_context(
        scenario_text="三相异步电机控制",
        plan_text=(
            "热继电器提供过载保护。"
            "操作员按停止按钮执行正常停机。"
            "系统配置通用报警。"
        ),
    )

    result = default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert "过载停机" in result.evidence
    assert "过载报警" in result.evidence


def test_unrelated_safety_phrases_do_not_complete_emergency_stop_chain() -> None:
    context = validation_context(
        scenario_text="电机控制",
        plan_text=(
            "急停输入已配置。"
            "设备故障时切断输出。"
            "启动命令具有最高优先级。"
            "维护完成后人工复位。"
        ),
    )

    result = default_rule_result("EMERGENCY_STOP_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert "急停后输出断开" in result.evidence
    assert "急停优先级" in result.evidence
    assert "复位说明" in result.evidence


def test_each_exclusive_action_pair_requires_its_own_interlock_evidence() -> None:
    context = validation_context(
        scenario_text="电机正转和反转，并控制阀门开阀和关阀",
        plan_text=(
            "正转与反转设置硬件和程序互锁。"
            "开阀按钮控制开阀，关阀按钮控制关阀。"
        ),
    )

    result = default_rule_result("MUTUAL_INTERLOCK_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert result.related_items == ["开阀/关阀"]


def test_each_exclusive_action_pair_passes_with_its_own_interlock_evidence() -> None:
    context = validation_context(
        scenario_text="电机正转和反转，并控制阀门开阀和关阀",
        plan_text=(
            "正转与反转设置硬件和程序互锁。"
            "开阀与关阀也设置独立的程序互锁。"
        ),
    )

    result = default_rule_result("MUTUAL_INTERLOCK_MISSING", context)

    assert result.status == RuleStatus.PASSED


def test_safe_state_must_cover_each_important_output() -> None:
    context = validation_context(
        scenario_text="电机和加热器控制",
        plan_text=(
            "故障时电机停止并进入安全状态。"
            "加热器在正常停机时关闭。"
        ),
    )

    result = default_rule_result("SAFE_STATE_UNDEFINED", context)

    assert result.status == RuleStatus.FAILED
    assert "加热器" in result.related_items


def test_global_safe_state_can_cover_all_important_outputs_explicitly() -> None:
    context = validation_context(
        scenario_text="电机和加热器控制",
        plan_text="故障时停止所有输出，所有重要输出进入安全状态。",
    )

    result = default_rule_result("SAFE_STATE_UNDEFINED", context)

    assert result.status == RuleStatus.PASSED


def test_feedback_for_another_device_does_not_cover_single_device_scenario() -> None:
    context = validation_context(
        scenario_text="水泵控制",
        plan_text="水泵按启停命令运行。电机运行反馈用于另一套设备的状态显示。",
    )

    result = default_rule_result("ACTUATOR_FEEDBACK_MISSING", context)

    assert result.status == RuleStatus.WARNING
    assert result.related_items == ["水泵"]


def test_partial_no_control_phrase_does_not_make_whole_scenario_monitoring_only() -> None:
    context = validation_context(
        scenario_text="不控制照明，只控制电机启停。",
        plan_text="启动条件满足后电机运行。",
    )

    result = default_rule_result("EMERGENCY_STOP_MISSING", context)

    assert result.status == RuleStatus.FAILED


def test_english_partial_no_control_does_not_override_required_control() -> None:
    context = validation_context(
        scenario_text="No control of lighting; motor control required.",
        plan_text="The motor starts when the start condition is true.",
    )

    result = default_rule_result("EMERGENCY_STOP_MISSING", context)

    assert result.status == RuleStatus.FAILED


def test_negation_does_not_cross_contrast_and_conjunction_boundaries() -> None:
    context = validation_context(
        scenario_text="电机控制",
        plan_text=(
            "未配置温度传感器但急停已配置且急停触发后立即切断输出"
            "且急停具有最高优先级且急停后必须人工复位。"
        ),
    )

    result = default_rule_result("EMERGENCY_STOP_MISSING", context)

    assert result.status == RuleStatus.PASSED


def test_unrelated_comma_clauses_do_not_complete_emergency_stop_chain() -> None:
    context = validation_context(
        scenario_text="电机控制",
        plan_text=(
            "急停输入已配置，设备故障时切断输出，"
            "启动命令具有最高优先级，维护完成后人工复位。"
        ),
    )

    result = default_rule_result("EMERGENCY_STOP_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert "急停后输出断开" in result.evidence
    assert "急停优先级" in result.evidence
    assert "复位说明" in result.evidence


def test_unrelated_comma_clauses_do_not_satisfy_overload_actions() -> None:
    context = validation_context(
        scenario_text="三相异步电机控制",
        plan_text=(
            "热继电器提供过载保护，操作员按停止按钮执行正常停机，"
            "系统配置通用报警。"
        ),
    )

    result = default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert "过载停机" in result.evidence
    assert "过载报警" in result.evidence


def test_unrelated_comma_clauses_do_not_satisfy_timeout_actions() -> None:
    context = validation_context(
        scenario_text="电动阀门开关控制",
        plan_text=(
            "动作开始时启动计时，到位超时判断，"
            "操作员按停止按钮正常停机，系统配置通用报警。"
        ),
    )

    result = default_rule_result("ACTION_TIMEOUT_PROTECTION_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert "超时停止" in result.evidence
    assert "超时报警" in result.evidence


def test_interlock_for_another_action_pair_does_not_cover_reversing_motor() -> None:
    context = validation_context(
        scenario_text="电机正转和反转，并控制阀门开阀和关阀",
        plan_text="正转与反转由按钮控制，开阀与关阀设置程序互锁。",
    )

    result = default_rule_result("MUTUAL_INTERLOCK_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert result.related_items == ["正转/反转"]


def test_feedback_for_unknown_other_device_does_not_cover_water_pump() -> None:
    context = validation_context(
        scenario_text="水泵控制",
        plan_text="水泵按启停命令运行。压缩机运行反馈用于另一套设备。",
    )

    result = default_rule_result("ACTUATOR_FEEDBACK_MISSING", context)

    assert result.status == RuleStatus.WARNING
    assert result.related_items == ["水泵"]


def test_feedback_for_unlisted_other_device_does_not_cover_water_pump() -> None:
    context = validation_context(
        scenario_text="水泵控制",
        plan_text="水泵按启停命令运行。机器人运行反馈用于另一套设备。",
    )

    result = default_rule_result("ACTUATOR_FEEDBACK_MISSING", context)

    assert result.status == RuleStatus.WARNING
    assert result.related_items == ["水泵"]


def test_normal_heater_shutdown_does_not_define_heater_fault_safe_state() -> None:
    context = validation_context(
        scenario_text="电机和加热器控制",
        plan_text="电机故障时电机停止并进入安全状态，加热器关闭仅用于正常温控。",
    )

    result = default_rule_result("SAFE_STATE_UNDEFINED", context)

    assert result.status == RuleStatus.FAILED
    assert "加热器" in result.related_items


def test_conjunction_boundaries_do_not_join_unrelated_evidence() -> None:
    cases = (
        (
            "EMERGENCY_STOP_MISSING",
            "电机控制",
            "急停输入已配置但设备故障时切断输出且启动命令具有最高优先级且维护后人工复位。",
            RuleStatus.FAILED,
        ),
        (
            "MOTOR_OVERLOAD_PROTECTION_MISSING",
            "三相异步电机控制",
            "热继电器提供过载保护但操作员按停止按钮正常停机且系统配置通用报警。",
            RuleStatus.FAILED,
        ),
        (
            "ACTION_TIMEOUT_PROTECTION_MISSING",
            "电动阀门控制",
            "动作启动计时且检测到位超时但操作员按停止按钮正常停机且系统配置通用报警。",
            RuleStatus.FAILED,
        ),
        (
            "MUTUAL_INTERLOCK_MISSING",
            "电机正转和反转，并控制阀门开阀和关阀",
            "正转与反转由按钮控制但开阀与关阀设置程序互锁。",
            RuleStatus.FAILED,
        ),
        (
            "ACTUATOR_FEEDBACK_MISSING",
            "水泵控制",
            "水泵按命令运行但机器人运行反馈用于另一套设备。",
            RuleStatus.WARNING,
        ),
        (
            "SAFE_STATE_UNDEFINED",
            "电机和加热器控制",
            "电机故障时电机停止但加热器关闭仅用于正常温控。",
            RuleStatus.FAILED,
        ),
    )

    for rule_id, scenario_text, plan_text, expected_status in cases:
        result = default_rule_result(
            rule_id,
            validation_context(
                scenario_text=scenario_text,
                plan_text=plan_text,
            ),
        )

        assert result.status == expected_status, rule_id


def test_emergency_trigger_continuation_stops_at_unrelated_condition() -> None:
    context = validation_context(
        scenario_text="电机控制",
        plan_text=(
            "急停输入已配置且急停具有最高优先级，触发后仅记录状态，"
            "设备故障时切断输出，维护结束后人工复位。"
        ),
    )

    result = default_rule_result("EMERGENCY_STOP_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert "急停后输出断开" in result.evidence
    assert "复位说明" in result.evidence


def test_condition_clause_can_link_to_immediate_protection_result() -> None:
    passing_cases = (
        (
            "EMERGENCY_STOP_MISSING",
            "电机控制",
            "急停时，立即切断输出并人工复位。急停具有最高优先级。",
        ),
        (
            "MOTOR_OVERLOAD_PROTECTION_MISSING",
            "三相异步电机控制",
            "热继电器提供过载保护。发生过载时，电机停止并报警。",
        ),
        (
            "ACTION_TIMEOUT_PROTECTION_MISSING",
            "电动阀门控制",
            "阀门动作使用定时器。到位超时时，停止阀门并报警。",
        ),
        (
            "MUTUAL_INTERLOCK_MISSING",
            "电机正转和反转",
            "正转与反转之间，设置硬件和程序互锁。",
        ),
        (
            "SAFE_STATE_UNDEFINED",
            "电机和加热器控制",
            "故障时，电机停止且加热器关闭。",
        ),
    )

    for rule_id, scenario_text, plan_text in passing_cases:
        result = default_rule_result(
            rule_id,
            validation_context(
                scenario_text=scenario_text,
                plan_text=plan_text,
            ),
        )

        assert result.status == RuleStatus.PASSED, rule_id


def test_monitoring_control_system_noun_is_not_control_intent() -> None:
    assert is_monitoring_only("电机控制系统仅监测运行状态，不控制电机输出。")
    assert is_monitoring_only(
        "Control system for monitoring only; no actuator control."
    )


def test_monitoring_only_does_not_hide_control_of_another_actuator() -> None:
    assert not is_monitoring_only(
        "仅监测电机，不控制电机，但控制输送带运行。"
    )
    assert not is_monitoring_only(
        "Monitoring only for the motor but controls conveyor movement."
    )


def test_result_conjunctions_preserve_one_condition_chain() -> None:
    passing_cases = (
        (
            "EMERGENCY_STOP_MISSING",
            "电机控制",
            "急停时，立即切断输出且人工复位。急停具有最高优先级。",
        ),
        (
            "MOTOR_OVERLOAD_PROTECTION_MISSING",
            "三相异步电机控制",
            "热继电器提供过载保护。发生过载时，电机停止且报警。",
        ),
        (
            "ACTION_TIMEOUT_PROTECTION_MISSING",
            "电动阀门控制",
            "阀门动作使用定时器。到位超时时，停止阀门且报警。",
        ),
        (
            "MUTUAL_INTERLOCK_MISSING",
            "Motor forward and reverse control",
            "Between forward and reverse, use hardware interlock.",
        ),
        (
            "EMERGENCY_STOP_MISSING",
            "Motor control",
            (
                "On emergency stop, de-energize outputs and require manual reset. "
                "Emergency stop has highest priority."
            ),
        ),
    )

    for rule_id, scenario_text, plan_text in passing_cases:
        result = default_rule_result(
            rule_id,
            validation_context(
                scenario_text=scenario_text,
                plan_text=plan_text,
            ),
        )

        assert result.status == RuleStatus.PASSED, rule_id


def test_configuration_completion_is_not_a_protection_trigger() -> None:
    cases = (
        (
            "MOTOR_OVERLOAD_PROTECTION_MISSING",
            "三相异步电机控制",
            "安装热继电器并提供过载保护后，操作员停止电机并测试报警。",
        ),
        (
            "MOTOR_OVERLOAD_PROTECTION_MISSING",
            "三相异步电机控制",
            "安装热继电器后，操作员停止电机并测试报警。",
        ),
        (
            "ACTION_TIMEOUT_PROTECTION_MISSING",
            "电动阀门控制",
            "阀门动作使用定时器。配置超时参数后，操作员停止阀门并测试报警。",
        ),
        (
            "MOTOR_OVERLOAD_PROTECTION_MISSING",
            "三相异步电机控制",
            "热继电器已安装。测试过载后，操作员停止电机并测试报警。",
        ),
    )

    for rule_id, scenario_text, plan_text in cases:
        result = default_rule_result(
            rule_id,
            validation_context(
                scenario_text=scenario_text,
                plan_text=plan_text,
            ),
        )

        assert result.status == RuleStatus.FAILED, rule_id


def test_colons_do_not_join_unrelated_emergency_evidence() -> None:
    result = default_rule_result(
        "EMERGENCY_STOP_MISSING",
        validation_context(
            scenario_text="电机控制",
            plan_text=(
                "急停输入已配置：设备故障时切断输出："
                "启动命令最高优先级：维护后人工复位。"
            ),
        ),
    )

    assert result.status == RuleStatus.FAILED
    assert "急停后输出断开" in result.evidence
    assert "急停优先级" in result.evidence
    assert "复位说明" in result.evidence


def test_passive_control_intent_prevents_monitoring_only_bypass() -> None:
    scenarios = (
        "仅监测电机，但输送带由 PLC 驱动。",
        "仅监测电机，但输送带启停。",
        "仅监测电机状态，但 PLC 使输送带运行。",
        "只采集温度，同时 PLC 令水泵运行。",
        "Monitoring only for the motor; the conveyor is controlled by PLC.",
        "Monitoring only for the motor; conveyor operation is commanded by PLC.",
        "Monitoring only for motor status, while the PLC runs the conveyor.",
    )

    assert all(not is_monitoring_only(scenario) for scenario in scenarios)


def test_condition_result_chain_supports_all_conjoined_actions() -> None:
    emergency = default_rule_result(
        "EMERGENCY_STOP_MISSING",
        validation_context(
            scenario_text="电机控制",
            plan_text=(
                "急停时，切断输出且锁存报警且人工复位。"
                "急停具有最高优先级。"
            ),
        ),
    )
    safe_state = default_rule_result(
        "SAFE_STATE_UNDEFINED",
        validation_context(
            scenario_text="电机、加热器和阀门控制",
            plan_text="故障时，电机停止且加热器关闭且阀门关闭。",
        ),
    )

    assert emergency.status == RuleStatus.PASSED
    assert safe_state.status == RuleStatus.PASSED

    comma_emergency = default_rule_result(
        "EMERGENCY_STOP_MISSING",
        validation_context(
            scenario_text="电机控制",
            plan_text=(
                "急停时，切断输出，锁存报警，人工复位。"
                "急停具有最高优先级。"
            ),
        ),
    )
    comma_safe_state = default_rule_result(
        "SAFE_STATE_UNDEFINED",
        validation_context(
            scenario_text="电机、加热器和阀门控制",
            plan_text="故障时，电机停止，加热器关闭，阀门关闭。",
        ),
    )

    assert comma_emergency.status == RuleStatus.PASSED
    assert comma_safe_state.status == RuleStatus.PASSED


def test_plain_english_action_pairs_keep_pair_relationship() -> None:
    plans = (
        "Forward and reverse are protected by a hardware interlock.",
        "Reverse and forward are protected by a hardware interlock.",
        "Open valve and close valve commands use an interlock.",
        "Forward command and reverse command use an interlock.",
    )
    scenarios = (
        "Motor forward and reverse control",
        "Motor forward and reverse control",
        "Open valve and close valve control",
        "Motor forward and reverse control",
    )

    for scenario_text, plan_text in zip(scenarios, plans, strict=True):
        result = default_rule_result(
            "MUTUAL_INTERLOCK_MISSING",
            validation_context(
                scenario_text=scenario_text,
                plan_text=plan_text,
            ),
        )

        assert result.status == RuleStatus.PASSED, plan_text


def test_timeout_parameter_configuration_is_not_timeout_event() -> None:
    result = default_rule_result(
        "ACTION_TIMEOUT_PROTECTION_MISSING",
        validation_context(
            scenario_text="电动阀门控制",
            plan_text=(
                "阀门动作使用定时器。"
                "使用定时器设置超时后，操作员停止阀门且测试报警。"
            ),
        ),
    )

    assert result.status == RuleStatus.FAILED
    assert "超时停止" in result.evidence
    assert "超时报警" in result.evidence


def test_hard_boundaries_and_unknown_owner_do_not_join_evidence() -> None:
    emergency_plans = (
        "急停已配置 | 故障切断输出 | 启动命令最高优先级 | 维护后人工复位。",
        "急停已配置 —— 故障切断输出 —— 启动命令最高优先级 —— 维护后人工复位。",
        "急停已配置 / 故障切断输出 / 启动命令最高优先级 / 维护后人工复位。",
    )
    for plan_text in emergency_plans:
        emergency = default_rule_result(
            "EMERGENCY_STOP_MISSING",
            validation_context(
                scenario_text="电机控制",
                plan_text=plan_text,
            ),
        )
        assert emergency.status == RuleStatus.FAILED, plan_text

    feedback = default_rule_result(
        "ACTUATOR_FEEDBACK_MISSING",
        validation_context(
            scenario_text="水泵控制",
            plan_text="水泵系统误显示机器人运行反馈用于另一套设备。",
        ),
    )

    assert feedback.status == RuleStatus.WARNING
    assert feedback.related_items == ["水泵"]

    explicit_feedback = default_rule_result(
        "ACTUATOR_FEEDBACK_MISSING",
        validation_context(
            scenario_text="水泵控制",
            plan_text="监视水泵的接触器辅助触点运行反馈。",
        ),
    )

    assert explicit_feedback.status == RuleStatus.PASSED

    for plan_text in (
        "监视水泵的接触器运行反馈。",
        "监视电机接触器的运行反馈。",
        "水泵主接触器运行反馈用于状态确认。",
    ):
        explicit_feedback = default_rule_result(
            "ACTUATOR_FEEDBACK_MISSING",
            validation_context(
                scenario_text="水泵控制" if "水泵" in plan_text else "电机控制",
                plan_text=plan_text,
            ),
        )
        assert explicit_feedback.status == RuleStatus.PASSED, plan_text


def test_monitoring_start_stop_state_is_not_control_intent() -> None:
    scenarios = (
        "仅监测电机启动和停止状态，不控制电机。",
        "只监测电机启动次数，不输出控制。",
        "仅监测启动电机的次数，不输出控制。",
    )

    assert all(is_monitoring_only(scenario) for scenario in scenarios)


def test_alternate_cause_terminates_condition_result_chain() -> None:
    emergency = default_rule_result(
        "EMERGENCY_STOP_MISSING",
        validation_context(
            scenario_text="电机控制",
            plan_text=(
                "急停输入已配置并具有最高优先级。"
                "急停时，记录事件，设备故障切断输出，故障清除人工复位。"
            ),
        ),
    )
    overload = default_rule_result(
        "MOTOR_OVERLOAD_PROTECTION_MISSING",
        validation_context(
            scenario_text="三相异步电机控制",
            plan_text=(
                "热继电器提供过载保护。"
                "过载时，记录事件，设备故障停机且报警。"
            ),
        ),
    )
    safe_state = default_rule_result(
        "SAFE_STATE_UNDEFINED",
        validation_context(
            scenario_text="电机、加热器和阀门控制",
            plan_text=(
                "故障时，电机停止，温控程序使加热器关闭，"
                "手动使阀门关闭。"
            ),
        ),
    )

    assert emergency.status == RuleStatus.FAILED
    assert "急停后输出断开" in emergency.evidence
    assert "复位说明" in emergency.evidence
    assert overload.status == RuleStatus.FAILED
    assert "过载停机" in overload.evidence
    assert "过载报警" in overload.evidence
    assert safe_state.status == RuleStatus.FAILED
    assert safe_state.related_items == ["加热器", "阀门"]
