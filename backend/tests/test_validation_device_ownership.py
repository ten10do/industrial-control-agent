import pytest

from backend.tests.validation_fixtures import (
    default_rule_result,
    io_point,
    validation_context,
)
from backend.validation import RiskLevel, RuleStatus, build_default_engine
from backend.validation.device_semantics import (
    ACTUATOR_KINDS,
    PUMP_KINDS,
    controlled_device_instances,
    has_controlled_device,
)


MOTOR_RULE_EXPECTATIONS = {
    "START_STOP_INCOMPLETE": RuleStatus.FAILED,
    "EMERGENCY_STOP_MISSING": RuleStatus.FAILED,
    "MOTOR_OVERLOAD_PROTECTION_MISSING": RuleStatus.FAILED,
    "MUTUAL_INTERLOCK_MISSING": RuleStatus.FAILED,
    "ACTUATOR_FEEDBACK_MISSING": RuleStatus.WARNING,
    "ALARM_COVERAGE_INCOMPLETE": RuleStatus.WARNING,
    "MODE_INTERLOCK_MISSING": RuleStatus.FAILED,
    "SAFE_STATE_UNDEFINED": RuleStatus.FAILED,
}

COMPLETE_MOTOR_INSTANCE_PLAN = (
    "{device}配置启动条件、停止条件、复位输出和运行反馈。"
    "{device}配置急停报警，急停具有最高优先级，触发后立即切断输出并要求人工复位。"
    "{device}配置热继电器过载保护，过载时停止并报警。"
    "{device}正转和反转输出设置程序互锁。"
    "{device}通过模式选择开关切换自动模式和手动模式，设置模式互锁、手动权限并禁止同时生效。"
    "{device}故障和反馈异常均报警，故障时停止并进入安全状态。"
)


def multi_motor_context(*, second_complete: bool = False):
    second_plan = (
        COMPLETE_MOTOR_INSTANCE_PLAN.format(device="2号电机")
        if second_complete
        else (
            "2号电机未设置启动条件。"
            "2号电机未设置停止条件。"
            "2号电机未设置停机输出处理。"
            "2号电机未设置急停。"
            "2号电机未设置过载保护。"
            "2号电机未设置运行反馈。"
            "2号电机未设置故障报警。"
            "2号电机未设置正反转互锁。"
            "2号电机未设置模式选择、模式互锁、手动权限及同时生效限制。"
            "2号电机未设置安全停机状态。"
        )
    )
    return validation_context(
        scenario_text=(
            "1号电机和2号电机均需启动停止、正转反转、自动模式和手动模式控制、急停、"
            "过载保护、运行反馈、故障报警和安全停机。"
        ),
        plan_text=(
            COMPLETE_MOTOR_INSTANCE_PLAN.format(device="1号电机")
            + second_plan
        ),
        structured_io_available=False,
    )


@pytest.mark.parametrize(
    ("scenario_text", "output_devices"),
    [
        ("水箱液位监测，无水泵、无电机，仅控制排水阀。", "排水阀"),
        ("水箱液位监测，不控制水泵，只控制排水阀。", "排水阀"),
        ("只监测水泵状态，同时控制排水阀。", "排水阀"),
        ("Tank level monitoring; no pump or motor, only control the drain valve.", "drain valve"),
    ],
)
def test_absent_or_uncontrolled_motor_devices_do_not_trigger_motor_or_pump_rules(
    scenario_text: str,
    output_devices: str,
) -> None:
    context = validation_context(
        scenario_text=scenario_text,
        plan_text="排水阀按液位命令开启或关闭。",
        output_devices=output_devices,
        io_points=(
            io_point("Q0.0", "排水阀输出", "DO", output_devices),
        ),
    )

    overload = default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context)
    dry_run = default_rule_result("PUMP_DRY_RUN_PROTECTION_MISSING", context)
    valve_timeout = default_rule_result("ACTION_TIMEOUT_PROTECTION_MISSING", context)

    assert overload.status == RuleStatus.NOT_APPLICABLE
    assert dry_run.status == RuleStatus.NOT_APPLICABLE
    assert valve_timeout.status == RuleStatus.FAILED


def test_negated_capability_does_not_make_the_device_disappear() -> None:
    missing_overload = validation_context(
        scenario_text="没有水泵过载保护。",
        plan_text="未配置过载保护。",
    )
    missing_alarm = validation_context(
        scenario_text="无水泵故障报警。",
        plan_text="未配置故障报警。",
    )

    overload = default_rule_result(
        "MOTOR_OVERLOAD_PROTECTION_MISSING",
        missing_overload,
    )
    alarm = default_rule_result("ALARM_COVERAGE_INCOMPLETE", missing_alarm)

    assert overload.status == RuleStatus.FAILED
    assert alarm.status == RuleStatus.WARNING


def test_input_only_device_does_not_override_structured_output_ownership() -> None:
    context = validation_context(
        scenario_text="水泵运行反馈，排水阀控制。",
        input_devices="水泵运行反馈",
        output_devices="排水阀",
        plan_text="排水阀按命令开启和关闭。",
        io_points=(
            io_point("I0.0", "水泵运行反馈", "DI", "水泵"),
            io_point("Q0.0", "排水阀输出", "DO", "排水阀"),
        ),
    )

    assert (
        default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context).status
        == RuleStatus.NOT_APPLICABLE
    )
    assert (
        default_rule_result("ACTION_TIMEOUT_PROTECTION_MISSING", context).status
        == RuleStatus.FAILED
    )


def test_generic_absence_conflicting_with_output_is_treated_as_ambiguous() -> None:
    context = validation_context(
        scenario_text="无水泵。",
        output_devices="水泵",
        control_requirements="无水泵。",
        structured_io_available=False,
    )

    result = default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context)

    assert result.status == RuleStatus.NOT_APPLICABLE


def test_absent_backup_pump_is_not_discovered_as_a_controlled_instance() -> None:
    context = validation_context(
        scenario_text="无备用水泵，主水泵由 PLC 控制。",
        structured_io_available=False,
    )

    instances = controlled_device_instances(context, ACTUATOR_KINDS)

    assert [(instance.label, instance.kind) for instance in instances] == [
        ("主水泵", "pump")
    ]


@pytest.mark.parametrize(
    "scenario_text",
    (
        "无备用水泵。",
        "不控制备用水泵。",
        "仅监测备用水泵。",
        "水泵不存在。",
        "水泵不受控制。",
        "The pump is not controlled.",
        "Water pump monitoring only.",
    ),
)
def test_negated_or_uncontrolled_device_mentions_do_not_trigger_rules(
    scenario_text: str,
) -> None:
    context = validation_context(
        scenario_text=scenario_text,
        structured_io_available=False,
    )

    assert not has_controlled_device(context, PUMP_KINDS)
    assert (
        default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context).status
        == RuleStatus.NOT_APPLICABLE
    )


@pytest.mark.parametrize(
    "scenario_text",
    (
        "No pump, motor, or fan is installed.",
        "There is no pump or electric motor.",
    ),
)
def test_english_absence_lists_do_not_trigger_motor_rules(
    scenario_text: str,
) -> None:
    context = validation_context(
        scenario_text=scenario_text,
        structured_io_available=False,
    )

    assert (
        default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context).status
        == RuleStatus.NOT_APPLICABLE
    )


@pytest.mark.parametrize(
    ("scenario_text", "first_device", "second_device"),
    (
        ("1号和2号电机均需要运行反馈。", "1号电机", "2号电机"),
        ("P-1和P-10水泵均需要运行反馈。", "P-1水泵", "P-10水泵"),
    ),
)
def test_shorthand_instance_lists_keep_each_device_separate(
    scenario_text: str,
    first_device: str,
    second_device: str,
) -> None:
    context = validation_context(
        scenario_text=scenario_text,
        plan_text=(
            f"{first_device}配置运行反馈。"
            f"{second_device}未配置运行反馈。"
        ),
        structured_io_available=False,
    )

    result = default_rule_result("ACTUATOR_FEEDBACK_MISSING", context)

    assert result.status == RuleStatus.WARNING
    assert result.related_items == [second_device]


def test_three_device_shorthand_list_keeps_every_instance() -> None:
    context = validation_context(
        scenario_text="1号、2号和3号电机均需要过载保护。",
        plan_text=(
            "1号电机未配置过载保护。"
            "2号电机配置热继电器过载保护，过载时停止并报警。"
            "3号电机配置热继电器过载保护，过载时停止并报警。"
        ),
        structured_io_available=False,
    )

    result = default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert result.related_items == ["1号电机"]


def test_only_controlled_instance_cannot_borrow_excluded_peers_evidence() -> None:
    context = validation_context(
        scenario_text="不控制1号电机，只控制2号电机。",
        plan_text=(
            "1号电机配置热继电器过载保护，过载时停止并报警。"
            "2号电机未配置过载保护。"
        ),
        structured_io_available=False,
    )

    result = default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert result.related_items == ["2号电机"]


def test_controlled_instance_cannot_borrow_excluded_other_kind_evidence() -> None:
    context = validation_context(
        scenario_text="只控制1号电机，不控制备用阀门。",
        plan_text="1号电机配置启动命令和备用阀门配置开到位反馈。",
        structured_io_available=False,
    )

    result = default_rule_result("ACTUATOR_FEEDBACK_MISSING", context)

    assert result.status == RuleStatus.WARNING
    assert result.related_items == ["1号电机"]


def test_contrasting_device_clauses_do_not_share_evidence() -> None:
    context = validation_context(
        scenario_text="1号电机和2号电机均需要运行反馈。",
        plan_text="1号电机配置运行反馈但2号电机未配置运行反馈。",
        structured_io_available=False,
    )

    result = default_rule_result("ACTUATOR_FEEDBACK_MISSING", context)

    assert result.status == RuleStatus.WARNING
    assert result.related_items == ["2号电机"]


def test_main_and_backup_compound_valves_keep_separate_timeout_evidence() -> None:
    context = validation_context(
        scenario_text="主排水阀和备用排水阀均需要动作超时保护。",
        plan_text=(
            "主排水阀设置动作计时，到位超时后停止并报警。"
            "备用排水阀未设置动作超时保护。"
        ),
        structured_io_available=False,
    )

    result = default_rule_result("ACTION_TIMEOUT_PROTECTION_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert result.related_items == ["备用排水阀"]


def test_ownerless_new_sentence_does_not_inherit_previous_device() -> None:
    context = validation_context(
        scenario_text="1号电机和2号电机均需要运行反馈。",
        plan_text=(
            "1号电机配置运行反馈。"
            "2号电机未配置运行反馈。"
            "运行反馈已配置。"
        ),
        structured_io_available=False,
    )

    result = default_rule_result("ACTUATOR_FEEDBACK_MISSING", context)

    assert result.status == RuleStatus.WARNING
    assert result.related_items == ["2号电机"]


def test_explicit_every_device_evidence_covers_all_instances() -> None:
    context = validation_context(
        scenario_text="1号电机和2号电机均需要运行反馈。",
        plan_text="每台设备均配置运行反馈。",
        structured_io_available=False,
    )

    result = default_rule_result("ACTUATOR_FEEDBACK_MISSING", context)

    assert result.status == RuleStatus.PASSED


def test_repeated_fields_in_one_output_point_do_not_create_a_phantom_instance() -> None:
    context = validation_context(
        scenario_text="水泵控制。",
        io_points=(
            io_point(
                "Q0.0",
                "水泵 P-1",
                "DO",
                "P-1水泵",
                "P-1水泵运行输出",
            ),
        ),
    )

    instances = controlled_device_instances(context, ACTUATOR_KINDS)

    assert [(instance.label, instance.kind) for instance in instances] == [
        ("P-1水泵", "pump")
    ]


def test_english_absent_backup_keeps_only_controlled_main_pump() -> None:
    context = validation_context(
        scenario_text="No backup pump; main pump is controlled.",
        structured_io_available=False,
    )

    instances = controlled_device_instances(context, ACTUATOR_KINDS)

    assert [(instance.label, instance.kind) for instance in instances] == [
        ("main pump", "pump")
    ]


def test_collection_requirement_does_not_turn_input_device_into_controlled_output() -> None:
    context = validation_context(
        scenario_text="采集水泵运行反馈，控制排水阀。",
        control_requirements="采集水泵运行反馈，控制排水阀。",
        input_devices="水泵运行反馈",
        output_devices="排水阀",
        structured_io_available=False,
    )

    assert (
        default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context).status
        == RuleStatus.NOT_APPLICABLE
    )
    assert (
        default_rule_result("ACTION_TIMEOUT_PROTECTION_MISSING", context).status
        == RuleStatus.FAILED
    )


@pytest.mark.parametrize(
    "control_requirements",
    (
        "不需要控制水泵，只控制排水阀。",
        "水泵无需控制，只控制排水阀。",
        "监测对象为水泵，只控制排水阀。",
        "对水泵进行监测，只控制排水阀。",
        "Do not control the pump; only control the drain valve.",
        "No control of the pump; only control the drain valve.",
    ),
)
def test_common_monitoring_phrases_do_not_trigger_pump_control_rules(
    control_requirements: str,
) -> None:
    context = validation_context(
        scenario_text=control_requirements,
        control_requirements=control_requirements,
        output_devices="排水阀",
        structured_io_available=False,
    )

    assert (
        default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context).status
        == RuleStatus.NOT_APPLICABLE
    )


@pytest.mark.parametrize(
    "control_object",
    (
        "水泵状态监测",
        "无水泵，仅控制排水阀",
    ),
)
def test_control_object_is_not_unconditional_output_evidence(
    control_object: str,
) -> None:
    context = validation_context(
        scenario_text=control_object,
        control_object=control_object,
        output_devices="排水阀",
        structured_io_available=False,
    )

    assert (
        default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context).status
        == RuleStatus.NOT_APPLICABLE
    )


def test_optimize_keeps_device_applicability_from_original_report() -> None:
    context = validation_context(
        source="optimize",
        scenario_text="原方案控制电机启停，并要求过载保护。",
        control_requirements="请加强安全保护。",
        plan_text="优化方案仍未配置过载保护。",
        structured_io_available=False,
    )

    result = default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context)

    assert result.status == RuleStatus.FAILED


def test_multiple_owners_in_one_conjunction_keep_separate_predicates() -> None:
    context = validation_context(
        scenario_text="1号电机和2号电机均需要运行反馈。",
        plan_text="1号电机配置运行反馈和2号电机未配置运行反馈。",
        structured_io_available=False,
    )

    result = default_rule_result("ACTUATOR_FEEDBACK_MISSING", context)

    assert result.status == RuleStatus.WARNING
    assert result.related_items == ["2号电机"]


def test_multiple_owners_in_one_conjunction_keep_emergency_stop_separate() -> None:
    context = validation_context(
        scenario_text="1号电机和2号电机均需要急停保护。",
        plan_text=(
            "1号电机急停具有最高优先级并立即切断输出并要求人工复位"
            "和2号电机无急停。"
        ),
        structured_io_available=False,
    )

    result = default_rule_result("EMERGENCY_STOP_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert result.related_items == ["2号电机"]


def test_safe_state_requires_an_action_valid_for_the_device_kind() -> None:
    context = validation_context(
        scenario_text="1号电机和2号电机均需要故障安全状态。",
        plan_text=(
            "1号电机故障时打开启动输出。"
            "2号电机故障时停止并进入安全状态。"
        ),
        structured_io_available=False,
    )

    result = default_rule_result("SAFE_STATE_UNDEFINED", context)

    assert result.status == RuleStatus.FAILED
    assert result.related_items == ["1号电机"]


def test_time_word_after_does_not_create_a_phantom_motor() -> None:
    context = validation_context(
        scenario_text="1号电机和2号电机受控，故障后电机停止。",
        structured_io_available=False,
    )

    instances = controlled_device_instances(context, ACTUATOR_KINDS)

    assert [instance.label for instance in instances] == ["1号电机", "2号电机"]


def test_equivalent_prefix_and_suffix_numbers_share_canonical_instance_keys() -> None:
    context = validation_context(
        scenario_text="1号电机和2号电机均受控。",
        output_devices="电机1、电机2",
        control_requirements="1号电机和2号电机均受控。",
        structured_io_available=False,
    )

    instances = controlled_device_instances(context, ACTUATOR_KINDS)

    assert len(instances) == 2
    assert {instance.key for instance in instances} == {"motor:1", "motor:2"}


def test_single_explicit_instance_uses_owned_feedback_and_safe_state() -> None:
    context = validation_context(
        scenario_text="1号电机控制。",
        plan_text="1号电机配置运行反馈。1号电机故障时停止。",
        structured_io_available=False,
    )

    assert (
        default_rule_result("ACTUATOR_FEEDBACK_MISSING", context).status
        == RuleStatus.PASSED
    )
    assert (
        default_rule_result("SAFE_STATE_UNDEFINED", context).status
        == RuleStatus.PASSED
    )


@pytest.mark.parametrize(
    "plan_text",
    (
        "1号电机配置热继电器过载保护。过载时停止并报警。",
        "1号电机配置热继电器过载保护，但过载时停止并报警。",
    ),
)
def test_single_explicit_instance_keeps_ownerless_followup_evidence(
    plan_text: str,
) -> None:
    context = validation_context(
        scenario_text="1号电机需要过载保护。",
        plan_text=plan_text,
        structured_io_available=False,
    )

    assert (
        default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context).status
        == RuleStatus.PASSED
    )


def test_emergency_alarm_expectation_is_scoped_to_the_device() -> None:
    context = validation_context(
        scenario_text="1号电机需要急停。2号加热器仅执行温度控制。",
        plan_text=(
            "1号电机配置急停报警、过载报警、电机故障报警和反馈异常报警。"
            "2号加热器配置执行器故障报警和反馈异常报警。"
        ),
        structured_io_available=False,
    )

    result = default_rule_result("ALARM_COVERAGE_INCOMPLETE", context)

    assert result.status == RuleStatus.PASSED


def test_plural_english_devices_are_discovered_and_scoped() -> None:
    context = validation_context(
        scenario_text=(
            "Motors M-1 and M-2 are controlled and require overload protection."
        ),
        plan_text=(
            "Motor M-1 has thermal relay overload protection and stops with an alarm "
            "on overload. Motor M-2 has no overload protection."
        ),
        structured_io_available=False,
    )

    result = default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert any("m-2" in item.casefold() for item in result.related_items)


def test_english_oxford_comma_list_keeps_all_devices() -> None:
    context = validation_context(
        scenario_text=(
            "The motors M-1, M-2, and M-3 are controlled and require run feedback."
        ),
        plan_text=(
            "Motor M-1 has run feedback. "
            "Motor M-2 has run feedback. "
            "Motor M-3 has no run feedback."
        ),
        structured_io_available=False,
    )

    instances = controlled_device_instances(context, ACTUATOR_KINDS)
    result = default_rule_result("ACTUATOR_FEEDBACK_MISSING", context)

    assert len(instances) == 3
    assert result.status == RuleStatus.WARNING
    assert len(result.related_items) == 1
    assert "m-3" in result.related_items[0].casefold()


def test_postposed_missing_capability_keeps_device_applicable() -> None:
    context = validation_context(
        scenario_text="水泵未设置过载保护。",
        plan_text="水泵未设置过载保护。",
        structured_io_available=False,
    )

    result = default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context)

    assert result.status == RuleStatus.FAILED


def test_chinese_shared_absence_list_does_not_trigger_motor_rules() -> None:
    requirement = "无水泵、电机和风机，仅控制排水阀。"
    context = validation_context(
        scenario_text=requirement,
        control_requirements=requirement,
        output_devices="排水阀",
        structured_io_available=False,
    )

    result = default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context)

    assert result.status == RuleStatus.NOT_APPLICABLE


@pytest.mark.parametrize(
    "requirement",
    (
        "无水泵，电机，风机，仅控制排水阀。",
        "无水泵/电机/风机，仅控制排水阀。",
        "无水泵或电机或风机，仅控制排水阀。",
        "没有水泵,电机,风机，只控制排水阀。",
    ),
)
def test_chinese_absence_lists_support_common_separators(
    requirement: str,
) -> None:
    context = validation_context(
        scenario_text=requirement,
        control_requirements=requirement,
        output_devices="排水阀",
        structured_io_available=False,
    )

    assert (
        default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context).status
        == RuleStatus.NOT_APPLICABLE
    )


@pytest.mark.parametrize(
    "output_devices",
    (
        "无水泵，仅排水阀",
        "不控制水泵，仅排水阀",
    ),
)
def test_negated_strong_output_does_not_leak_nested_aliases(
    output_devices: str,
) -> None:
    context = validation_context(
        output_devices=output_devices,
        structured_io_available=False,
    )

    assert not has_controlled_device(context, PUMP_KINDS)
    assert (
        default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context).status
        == RuleStatus.NOT_APPLICABLE
    )


def test_shared_owner_subset_keeps_its_common_predicate() -> None:
    context = validation_context(
        scenario_text="1号、2号和3号电机均需要运行反馈。",
        plan_text="1号和2号电机均配置运行反馈而3号电机未配置运行反馈。",
        structured_io_available=False,
    )

    result = default_rule_result("ACTUATOR_FEEDBACK_MISSING", context)

    assert result.status == RuleStatus.WARNING
    assert result.related_items == ["3号电机"]


def test_shared_uncontrolled_instance_list_keeps_all_members_excluded() -> None:
    context = validation_context(
        scenario_text="不控制1号和2号电机，只控制3号电机。",
        structured_io_available=False,
    )

    instances = controlled_device_instances(context, ACTUATOR_KINDS)

    assert [instance.label for instance in instances] == ["3号电机"]


@pytest.mark.parametrize(
    ("scenario_text", "first_device", "second_device"),
    (
        (
            "1号循环水泵和2号循环水泵均需要过载保护。",
            "1号循环水泵",
            "2号循环水泵",
        ),
        (
            "主供水泵和备用供水泵均需要过载保护。",
            "主供水泵",
            "备用供水泵",
        ),
    ),
)
def test_compound_pump_names_keep_instance_ownership(
    scenario_text: str,
    first_device: str,
    second_device: str,
) -> None:
    context = validation_context(
        scenario_text=scenario_text,
        plan_text=(
            f"{first_device}配置热继电器过载保护，过载时停止并报警。"
            f"{second_device}未配置过载保护。"
        ),
        structured_io_available=False,
    )

    result = default_rule_result("MOTOR_OVERLOAD_PROTECTION_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert result.related_items == [second_device]


@pytest.mark.parametrize(
    ("scenario_text", "plan_text", "missing_marker"),
    (
        (
            "1号和2号电机均需要运行反馈。",
            "1号和2号电机分别配置温度检测和运行反馈。",
            "1号",
        ),
        (
            "Motors M-1 and M-2 require run feedback.",
            (
                "Motors M-1 and M-2 respectively have temperature monitoring "
                "and run feedback."
            ),
            "m-1",
        ),
    ),
)
def test_respectively_maps_parallel_evidence_to_each_owner(
    scenario_text: str,
    plan_text: str,
    missing_marker: str,
) -> None:
    context = validation_context(
        scenario_text=scenario_text,
        plan_text=plan_text,
        structured_io_available=False,
    )

    result = default_rule_result("ACTUATOR_FEEDBACK_MISSING", context)

    assert result.status == RuleStatus.WARNING
    assert len(result.related_items) == 1
    assert missing_marker in result.related_items[0].casefold()


@pytest.mark.parametrize(
    ("rule_id", "expected_status"),
    MOTOR_RULE_EXPECTATIONS.items(),
)
def test_one_motor_instance_cannot_borrow_another_instances_evidence(
    rule_id: str,
    expected_status: RuleStatus,
) -> None:
    result = default_rule_result(rule_id, multi_motor_context())

    assert result.status == expected_status
    assert result.related_items == ["2号电机"]
    assert "2号电机" in result.evidence


@pytest.mark.parametrize("rule_id", MOTOR_RULE_EXPECTATIONS)
def test_each_motor_instance_with_complete_evidence_passes(rule_id: str) -> None:
    result = default_rule_result(
        rule_id,
        multi_motor_context(second_complete=True),
    )

    assert result.status == RuleStatus.PASSED


def test_multi_instance_issues_are_aggregated_once_per_rule_id() -> None:
    report = build_default_engine().validate(multi_motor_context())
    expected_rule_ids = tuple(MOTOR_RULE_EXPECTATIONS)
    issue_ids = tuple(result.rule_id for result in report.issues)

    assert report.total_rules == len(build_default_engine().rules)
    assert len(report.rule_results) == len({result.rule_id for result in report.rule_results})
    assert all(issue_ids.count(rule_id) == 1 for rule_id in expected_rule_ids)
    assert report.risk_score == 151
    assert report.risk_level == RiskLevel.CRITICAL


def test_one_pump_instance_cannot_cover_another_instances_dry_run_protection() -> None:
    context = validation_context(
        scenario_text=(
            "1号水泵和2号水泵位于水箱供液系统，均需低液位防干转保护。"
        ),
        plan_text=(
            "1号水泵配置低液位检测和防干转保护，缺水时停止并报警。"
            "2号水泵未配置低液位停泵、防干转和缺水报警。"
        ),
    )

    result = default_rule_result("PUMP_DRY_RUN_PROTECTION_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert result.related_items == ["2号水泵"]
    assert "2号水泵" in result.evidence


def test_one_valve_instance_cannot_cover_another_instances_timeout_protection() -> None:
    context = validation_context(
        scenario_text="1号排水阀和2号排水阀均需要动作超时保护。",
        plan_text=(
            "1号排水阀设置动作计时，到位超时后停止并报警。"
            "2号排水阀无动作计时、到位超时停止和超时报警。"
        ),
    )

    result = default_rule_result("ACTION_TIMEOUT_PROTECTION_MISSING", context)

    assert result.status == RuleStatus.FAILED
    assert result.related_items == ["2号排水阀"]
    assert "2号排水阀" in result.evidence


def test_similar_instance_names_do_not_share_feedback_evidence() -> None:
    context = validation_context(
        scenario_text="P-1水泵和P-10水泵均需要运行反馈。",
        plan_text=(
            "P-10水泵配置运行反馈。"
            "P-1水泵未配置运行反馈。"
        ),
    )

    result = default_rule_result("ACTUATOR_FEEDBACK_MISSING", context)

    assert result.status == RuleStatus.WARNING
    assert result.related_items == ["P-1水泵"]


def test_explicit_universal_evidence_covers_all_motor_instances() -> None:
    context = validation_context(
        scenario_text="1号电机和2号电机均需要完整保护。",
        plan_text=(
            "所有电机均配置启动条件、停止条件、复位输出和运行反馈。"
            "所有电机均配置热继电器过载保护，过载时全部停止并报警。"
            "所有电机故障时均停止并进入安全状态。"
        ),
    )

    for rule_id in (
        "START_STOP_INCOMPLETE",
        "MOTOR_OVERLOAD_PROTECTION_MISSING",
        "ACTUATOR_FEEDBACK_MISSING",
        "SAFE_STATE_UNDEFINED",
    ):
        assert default_rule_result(rule_id, context).status == RuleStatus.PASSED
