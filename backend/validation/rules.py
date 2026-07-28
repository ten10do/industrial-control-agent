from collections import defaultdict

from .base import ValidationRule
from .catalog import (
    ACTUATOR_FAULT_TERMS,
    ALARM_TERMS,
    AUTO_TERMS,
    CUT_OUTPUT_TERMS,
    DEADLINE_NOT_REACHED_TERMS,
    DRY_RUN_TERMS,
    EMERGENCY_STOP_TERMS,
    EMERGENCY_TRIGGER_TERMS,
    EXCLUSIVE_ACTION_COMPOUND_TERMS,
    EXCLUSIVE_ACTION_PAIRS,
    FAULT_TERMS,
    FEEDBACK_ABNORMAL_TERMS,
    FEEDBACK_DEVICE_GROUPS,
    FEEDBACK_TERMS,
    GENERIC_EXCLUSIVE_TERMS,
    GLOBAL_SAFE_OUTPUT_ACTION_TERMS,
    INTERLOCK_TERMS,
    IMMEDIATE_ACTION_TERMS,
    LEVEL_ABNORMAL_TERMS,
    LOW_LEVEL_TERMS,
    MANUAL_AUTHORITY_TERMS,
    MANUAL_TERMS,
    MODE_SELECT_TERMS,
    NO_SIMULTANEOUS_TERMS,
    NORMAL_OPERATION_TERMS,
    OVERLOAD_EVENT_TERMS,
    OVERLOAD_TERMS,
    OVERLOAD_PROTECTION_TERMS,
    PRIORITY_TERMS,
    RESET_TERMS,
    RESTART_TERMS,
    RUN_STATE_TERMS,
    SAFE_OUTPUT_DEVICE_GROUPS,
    SAFE_OUTPUT_ACTION_TERMS,
    SHARED_SAFE_OUTPUT_ACTION_TERMS,
    SAFE_STATE_TERMS,
    SENSOR_FAULT_TERMS,
    SENSOR_TERMS,
    SHUTDOWN_LOGIC_TERMS,
    START_TERMS,
    START_INHIBIT_TERMS,
    STOP_TERMS,
    TIMEOUT_EVENT_TERMS,
    TIMEOUT_TERMS,
    TIMER_TERMS,
    WATER_SYSTEM_TERMS,
    address_direction,
    applicable_exclusive_pairs,
    canonical_signal_type,
    contains_any,
    contains_any_affirmed,
    expected_direction,
    expected_signal_kind,
    normalize_address,
    normalize_name,
    terms_cooccur,
    terms_follow_condition,
    terms_follow_trigger,
    terms_near,
    terms_near_owner,
)
from .device_semantics import (
    ACTUATOR_KINDS,
    MOTION_KINDS,
    MOTOR_KINDS,
    PUMP_KINDS,
    RUN_STOP_KINDS,
    TIMEOUT_KINDS,
    DeviceScope,
    has_controlled_device,
    multi_device_scopes,
)
from .models import RuleResult, RuleStatus, Severity, ValidationContext, ValidationIOPoint


def _point_label(point: ValidationIOPoint) -> str:
    return point.device or point.signal_name or point.address or "未命名点位"


def _missing_evidence(missing: list[str]) -> list[str]:
    return [f"缺少：{item}" for item in missing]


def _instance_failures(
    scopes: tuple[DeviceScope, ...],
    checker,
) -> list[tuple[str, list[str]]]:
    failures: list[tuple[str, list[str]]] = []
    for scope in scopes:
        missing = [
            name
            for name, present in checker(scope.plan_text).items()
            if not present
        ]
        if missing:
            failures.append((scope.device.label, missing))
    return failures


def _instance_failure_evidence(
    failures: list[tuple[str, list[str]]],
) -> list[str]:
    return [
        f"{device}缺少：{'、'.join(missing)}"
        for device, missing in failures
    ]


def _instance_failure_devices(
    failures: list[tuple[str, list[str]]],
) -> list[str]:
    return [device for device, _ in failures]


def _start_stop_checks(text: str) -> dict[str, bool]:
    return {
        "启动条件": contains_any_affirmed(text, START_TERMS),
        "停止条件": contains_any_affirmed(text, STOP_TERMS),
        "停机输出处理": contains_any_affirmed(text, SHUTDOWN_LOGIC_TERMS),
        "运行状态或反馈": contains_any_affirmed(text, RUN_STATE_TERMS),
    }


def _emergency_stop_checks(text: str) -> dict[str, bool]:
    emergency_cut = terms_cooccur(
        text,
        EMERGENCY_STOP_TERMS,
        CUT_OUTPUT_TERMS,
    ) or terms_follow_trigger(
        text,
        EMERGENCY_STOP_TERMS,
        EMERGENCY_TRIGGER_TERMS,
        CUT_OUTPUT_TERMS,
    )
    immediate_emergency_cut = emergency_cut and terms_cooccur(
        text,
        EMERGENCY_STOP_TERMS,
        IMMEDIATE_ACTION_TERMS,
        CUT_OUTPUT_TERMS,
    )
    return {
        "急停输入": contains_any_affirmed(text, EMERGENCY_STOP_TERMS),
        "急停后输出断开": emergency_cut,
        "急停优先级": terms_cooccur(
            text,
            EMERGENCY_STOP_TERMS,
            PRIORITY_TERMS,
        )
        or immediate_emergency_cut,
        "复位说明": terms_cooccur(
            text,
            EMERGENCY_STOP_TERMS,
            RESET_TERMS,
        )
        or terms_follow_trigger(
            text,
            EMERGENCY_STOP_TERMS,
            EMERGENCY_TRIGGER_TERMS,
            RESET_TERMS,
        )
        or (
            emergency_cut
            and terms_cooccur(
                text,
                RESET_TERMS,
                RESTART_TERMS,
            )
        ),
    }


def _overload_checks(text: str) -> dict[str, bool]:
    return {
        "过载检测信号": contains_any_affirmed(text, OVERLOAD_TERMS),
        "热继电器或等效保护": contains_any_affirmed(
            text,
            OVERLOAD_PROTECTION_TERMS,
        ),
        "过载停机": terms_near(text, OVERLOAD_EVENT_TERMS, STOP_TERMS),
        "过载报警": terms_near(text, OVERLOAD_EVENT_TERMS, ALARM_TERMS),
    }


def _dry_run_checks(text: str) -> dict[str, bool]:
    return {
        "低液位或缺水检测": contains_any_affirmed(text, LOW_LEVEL_TERMS),
        "防干转逻辑": contains_any_affirmed(text, DRY_RUN_TERMS)
        or terms_near(
            text,
            LOW_LEVEL_TERMS,
            START_INHIBIT_TERMS,
        ),
        "缺水停泵": terms_near(text, LOW_LEVEL_TERMS, STOP_TERMS)
        or terms_near(
            text,
            LOW_LEVEL_TERMS,
            START_INHIBIT_TERMS,
        ),
        "缺水报警": terms_near(text, LOW_LEVEL_TERMS, ALARM_TERMS),
    }


def _timeout_checks(text: str) -> dict[str, bool]:
    return {
        "动作计时": contains_any_affirmed(text, TIMER_TERMS)
        or contains_any_affirmed(
            text,
            DEADLINE_NOT_REACHED_TERMS,
        ),
        "到位超时判断": contains_any_affirmed(text, TIMEOUT_TERMS)
        or contains_any_affirmed(
            text,
            DEADLINE_NOT_REACHED_TERMS,
        ),
        "超时停止": terms_near(text, TIMEOUT_EVENT_TERMS, STOP_TERMS),
        "超时报警": terms_near(text, TIMEOUT_EVENT_TERMS, ALARM_TERMS),
    }


def _mode_checks(text: str) -> dict[str, bool]:
    return {
        "模式选择或切换": contains_any_affirmed(text, MODE_SELECT_TERMS),
        "模式互锁": contains_any_affirmed(text, INTERLOCK_TERMS),
        "手动权限": contains_any_affirmed(text, MANUAL_AUTHORITY_TERMS),
        "禁止同时生效": contains_any_affirmed(
            text,
            NO_SIMULTANEOUS_TERMS,
        ),
    }


def _safe_scope_covered(text: str, kind: str) -> bool:
    safe_context_terms = FAULT_TERMS + SAFE_STATE_TERMS
    scoped_action_terms = STOP_TERMS + CUT_OUTPUT_TERMS
    if kind == "valve":
        scoped_action_terms += (
            "关闭",
            "打开",
            "安全位置",
            "closed",
            "open",
            "safe position",
        )
    elif kind == "heater":
        scoped_action_terms += (
            "关闭",
            "off",
        )
    elif kind in {"cylinder", "actuator"}:
        scoped_action_terms += (
            "安全位置",
            "safe position",
        )
    return terms_cooccur(
        text,
        safe_context_terms,
        scoped_action_terms,
    ) or terms_follow_condition(
        text,
        (safe_context_terms,),
        scoped_action_terms,
        forbidden_detail_terms=NORMAL_OPERATION_TERMS,
    )


def _interlock_uncovered(text: str, pairs: list[str]) -> list[str]:
    uncovered: list[str] = []
    for label, left_terms, right_terms in EXCLUSIVE_ACTION_PAIRS:
        if label not in pairs:
            continue
        covered = terms_cooccur(
            text,
            left_terms,
            right_terms,
            INTERLOCK_TERMS,
        ) or terms_follow_condition(
            text,
            (left_terms, right_terms),
            INTERLOCK_TERMS,
        )
        compound_terms = EXCLUSIVE_ACTION_COMPOUND_TERMS.get(label, ())
        covered = covered or (
            bool(compound_terms)
            and terms_cooccur(
                text,
                compound_terms,
                INTERLOCK_TERMS,
            )
        )
        if not covered:
            uncovered.append(label)
    if "互斥输出" in pairs:
        generic_covered = terms_cooccur(
            text,
            GENERIC_EXCLUSIVE_TERMS,
            INTERLOCK_TERMS,
        ) or terms_follow_condition(
            text,
            (GENERIC_EXCLUSIVE_TERMS,),
            INTERLOCK_TERMS,
        )
        if not generic_covered:
            uncovered.append("互斥输出")
    return uncovered


class DuplicateAddressRule(ValidationRule):
    rule_id = "IO_DUPLICATE_ADDRESS"
    name = "I/O 地址重复"
    category = "io"
    default_severity = Severity.HIGH

    def validate(self, context: ValidationContext) -> RuleResult:
        if not context.structured_io_available:
            return self.not_applicable("当前结果没有可可靠解析的结构化 I/O 点表。")

        groups: dict[str, list[ValidationIOPoint]] = defaultdict(list)
        for point in context.io_points:
            address = normalize_address(point.address)
            if address:
                groups[address].append(point)
        conflicts = {address: points for address, points in groups.items() if len(points) > 1}
        if not conflicts:
            return self.passed("未发现重复 I/O 地址。")

        evidence = [
            f"{address}：{'、'.join(_point_label(point) for point in points)}"
            for address, points in conflicts.items()
        ]
        related = [_point_label(point) for points in conflicts.values() for point in points]
        return self.result(
            status=RuleStatus.FAILED,
            message="发现同一 I/O 地址被多个点位使用。",
            evidence=evidence,
            recommendation="为冲突点位分配唯一地址，并复核输入、输出地址区。",
            related_items=related,
        )


class DuplicateNameRule(ValidationRule):
    rule_id = "IO_DUPLICATE_NAME"
    name = "I/O 点位名称重复"
    category = "io"
    default_severity = Severity.MEDIUM

    def validate(self, context: ValidationContext) -> RuleResult:
        if not context.structured_io_available:
            return self.not_applicable("当前结果没有可可靠解析的结构化 I/O 点表。")

        groups: dict[str, list[ValidationIOPoint]] = defaultdict(list)
        for point in context.io_points:
            name = normalize_name(point.signal_name)
            if name:
                groups[name].append(point)
        conflicts = [points for points in groups.values() if len(points) > 1]
        if not conflicts:
            return self.passed("点位名称归一化后仍保持唯一。")

        evidence = [
            " / ".join(f"{point.signal_name} ({point.address or '无地址'})" for point in points)
            for points in conflicts
        ]
        related = [point.signal_name for points in conflicts for point in points if point.signal_name]
        return self.result(
            status=RuleStatus.FAILED,
            message="发现归一化后重复的 I/O 点位名称。",
            evidence=evidence,
            recommendation="使用唯一且含义明确的点位名称，并统一大小写和分隔符规范。",
            related_items=related,
        )


class IOTypeMismatchRule(ValidationRule):
    rule_id = "IO_TYPE_MISMATCH"
    name = "输入输出类型不匹配"
    category = "io"
    default_severity = Severity.HIGH

    def validate(self, context: ValidationContext) -> RuleResult:
        if not context.structured_io_available:
            return self.not_applicable("当前结果没有可可靠解析的结构化 I/O 点表。")

        issues: list[str] = []
        related: list[str] = []
        for point in context.io_points:
            actual = canonical_signal_type(point.signal_type)
            if actual is None:
                continue
            actual_direction = "input" if actual.endswith("I") else "output"
            actual_kind = "analog" if actual.startswith("A") else "digital"
            inferred_direction = (
                expected_direction(point.device)
                or expected_direction(point.signal_name)
                or expected_direction(point.description)
            )
            inferred_kind = (
                expected_signal_kind(point.device)
                or expected_signal_kind(point.signal_name)
                or expected_signal_kind(point.description)
            )
            address_kind = address_direction(point.address)

            mismatches: list[str] = []
            if inferred_direction and inferred_direction != actual_direction:
                mismatches.append(f"设备语义期望 {inferred_direction}，实际 {actual}")
            if address_kind and address_kind != actual_direction:
                mismatches.append(f"地址属于 {address_kind} 区，信号类型为 {actual}")
            if inferred_kind and inferred_kind != actual_kind:
                mismatches.append(f"信号语义期望 {inferred_kind}，实际 {actual}")
            if mismatches:
                label = _point_label(point)
                issues.append(f"{label} ({point.address or '无地址'})：{'；'.join(mismatches)}")
                related.append(label)

        if not issues:
            return self.passed("未发现明确的输入输出方向或模拟/数字类型冲突。")
        return self.result(
            status=RuleStatus.FAILED,
            message="发现 I/O 类型与地址区或设备语义不一致。",
            evidence=issues,
            recommendation="依据设备接线和 PLC 地址区修正 DI、DO、AI、AO 类型。",
            related_items=related,
        )


class StartStopIncompleteRule(ValidationRule):
    rule_id = "START_STOP_INCOMPLETE"
    name = "启停控制不完整"
    category = "control"
    default_severity = Severity.HIGH

    def validate(self, context: ValidationContext) -> RuleResult:
        if not has_controlled_device(context, RUN_STOP_KINDS):
            return self.not_applicable("当前场景未识别到需要启停控制的执行设备。")
        scopes = multi_device_scopes(context, RUN_STOP_KINDS)
        if scopes:
            failures = _instance_failures(scopes, _start_stop_checks)
            if not failures:
                return self.passed("方案包含各设备的启动、停止、停机处理和运行状态说明。")
            return self.result(
                status=RuleStatus.FAILED,
                message="部分执行设备的启停控制链路不完整。",
                evidence=_instance_failure_evidence(failures),
                recommendation="逐台补充启动条件、停止条件、停机输出处理和运行反馈。",
                related_items=_instance_failure_devices(failures),
            )
        checks = _start_stop_checks(context.plan_text)
        missing = [name for name, present in checks.items() if not present]
        if not missing:
            return self.passed("方案包含启动、停止、停机处理和运行状态说明。")
        return self.result(
            status=RuleStatus.FAILED,
            message="执行设备的启停控制链路不完整。",
            evidence=_missing_evidence(missing),
            recommendation="补充明确的启动条件、停止条件、停机输出处理和运行反馈。",
            related_items=missing,
        )


class EmergencyStopMissingRule(ValidationRule):
    rule_id = "EMERGENCY_STOP_MISSING"
    name = "急停逻辑缺失"
    category = "safety"
    default_severity = Severity.CRITICAL

    def validate(self, context: ValidationContext) -> RuleResult:
        if not has_controlled_device(context, MOTION_KINDS):
            return self.not_applicable("当前场景未识别到运动机构或危险执行器。")
        scopes = multi_device_scopes(context, MOTION_KINDS)
        if scopes:
            failures = _instance_failures(scopes, _emergency_stop_checks)
            if not failures:
                return self.passed("各运动设备的急停输入、输出切断、优先级和复位说明完整。")
            return self.result(
                status=RuleStatus.FAILED,
                message="部分运动设备缺少完整急停安全链路。",
                evidence=_instance_failure_evidence(failures),
                recommendation="逐台补充急停输入、最高优先级输出切断和人工复位要求。",
                related_items=_instance_failure_devices(failures),
            )
        checks = _emergency_stop_checks(context.plan_text)
        missing = [name for name, present in checks.items() if not present]
        if not missing:
            return self.passed("急停输入、输出切断、优先级和复位说明完整。")
        return self.result(
            status=RuleStatus.FAILED,
            message="急停安全链路缺少必要说明。",
            evidence=_missing_evidence(missing),
            recommendation="补充硬接线急停输入、最高优先级输出切断和人工复位要求。",
            related_items=missing,
        )


class MotorOverloadProtectionMissingRule(ValidationRule):
    rule_id = "MOTOR_OVERLOAD_PROTECTION_MISSING"
    name = "电机过载保护缺失"
    category = "protection"
    default_severity = Severity.HIGH

    def validate(self, context: ValidationContext) -> RuleResult:
        if not has_controlled_device(context, MOTOR_KINDS):
            return self.not_applicable("当前场景未识别到电机、水泵或风机。")
        scopes = multi_device_scopes(context, MOTOR_KINDS)
        if scopes:
            failures = _instance_failures(scopes, _overload_checks)
            if not failures:
                return self.passed("各电机类设备均包含过载检测、停机和报警。")
            return self.result(
                status=RuleStatus.FAILED,
                message="部分电机类设备的过载保护不完整。",
                evidence=_instance_failure_evidence(failures),
                recommendation="逐台增加过载检测或等效保护，并联动停机和报警。",
                related_items=_instance_failure_devices(failures),
            )
        checks = _overload_checks(context.plan_text)
        missing = [name for name, present in checks.items() if not present]
        if not missing:
            return self.passed("方案包含过载检测、停机和报警。")
        return self.result(
            status=RuleStatus.FAILED,
            message="电机类设备的过载保护不完整。",
            evidence=_missing_evidence(missing),
            recommendation="增加热继电器或等效过载信号，并联动停机和报警。",
            related_items=missing,
        )


class MutualInterlockMissingRule(ValidationRule):
    rule_id = "MUTUAL_INTERLOCK_MISSING"
    name = "互锁保护缺失"
    category = "interlock"
    default_severity = Severity.CRITICAL

    def validate(self, context: ValidationContext) -> RuleResult:
        if not has_controlled_device(context, ACTUATOR_KINDS):
            return self.not_applicable("当前场景未识别到受控的互斥输出设备。")
        applicability_text = f"{context.scenario_text}\n{context.plan_text}"
        pairs = applicable_exclusive_pairs(applicability_text)
        if contains_any(context.scenario_text, GENERIC_EXCLUSIVE_TERMS):
            pairs.append("互斥输出")
        if not pairs:
            return self.not_applicable("当前场景未识别到明确的互斥动作对。")

        scopes = multi_device_scopes(context, ACTUATOR_KINDS)
        if scopes:
            failures = []
            for scope in scopes:
                scoped_pairs = applicable_exclusive_pairs(
                    f"{scope.scenario_text}\n{scope.plan_text}"
                )
                if contains_any(scope.scenario_text, GENERIC_EXCLUSIVE_TERMS):
                    scoped_pairs.append("互斥输出")
                if not scoped_pairs:
                    continue
                missing = _interlock_uncovered(scope.plan_text, scoped_pairs)
                failures.append((scope.device.label, missing))
            failures = [
                (device, missing)
                for device, missing in failures
                if missing
            ]
            if not failures:
                return self.passed("各设备的互斥动作均有明确互锁说明。")
            return self.result(
                status=RuleStatus.FAILED,
                message="部分设备的互斥输出缺少明确联锁保护。",
                evidence=_instance_failure_evidence(failures),
                recommendation="逐台增加硬件和程序双重互锁，禁止互斥输出同时有效。",
                related_items=_instance_failure_devices(failures),
            )
        uncovered = _interlock_uncovered(context.plan_text, pairs)
        if not uncovered:
            return self.passed("互斥动作均有明确的互锁说明。")
        return self.result(
            status=RuleStatus.FAILED,
            message="互斥输出缺少明确的联锁保护。",
            evidence=[f"未覆盖互锁动作：{label}" for label in uncovered],
            recommendation="增加硬件和程序双重互锁，禁止互斥输出同时有效。",
            related_items=uncovered,
        )


class ActuatorFeedbackMissingRule(ValidationRule):
    rule_id = "ACTUATOR_FEEDBACK_MISSING"
    name = "执行器反馈缺失"
    category = "feedback"
    default_severity = Severity.MEDIUM

    def validate(self, context: ValidationContext) -> RuleResult:
        if not has_controlled_device(context, ACTUATOR_KINDS):
            return self.not_applicable("当前场景未识别到需要状态确认的重要执行器。")

        scopes = multi_device_scopes(context, ACTUATOR_KINDS)
        if scopes:
            missing_devices = [
                scope.device.label
                for scope in scopes
                if not contains_any_affirmed(scope.plan_text, FEEDBACK_TERMS)
            ]
            if not missing_devices:
                return self.passed("方案包含各重要执行器的运行、故障或到位反馈。")
            return self.result(
                status=RuleStatus.WARNING,
                message="部分重要执行器缺少明确反馈信号。",
                evidence=[f"{device}缺少反馈" for device in missing_devices],
                recommendation="逐台增加运行、故障或到位反馈，并用于状态确认。",
                related_items=missing_devices,
            )
        device_groups = [
            (label, terms)
            for (label, terms), kind in zip(
                FEEDBACK_DEVICE_GROUPS,
                (
                    "motor",
                    "pump",
                    "fan",
                    "compressor",
                    "valve",
                    "conveyor",
                    "lift",
                    "cylinder",
                ),
                strict=True,
            )
            if has_controlled_device(context, (kind,))
        ]
        missing = [
            label
            for label, terms in device_groups
            if not terms_near_owner(
                context.plan_text,
                terms,
                FEEDBACK_TERMS,
                tuple(group_terms for _, group_terms in FEEDBACK_DEVICE_GROUPS),
            )
        ]
        if not device_groups and contains_any_affirmed(context.plan_text, FEEDBACK_TERMS):
            return self.passed("方案包含执行器运行、故障或到位反馈。")
        if device_groups and not missing:
            return self.passed("方案包含各类重要执行器的运行、故障或到位反馈。")
        return self.result(
            status=RuleStatus.WARNING,
            message="部分或全部重要执行器缺少明确反馈信号。",
            evidence=[
                f"缺少反馈：{label}" for label in missing
            ] or ["未命中运行反馈、故障反馈或到位反馈。"],
            recommendation="为重要执行器增加运行、故障或到位反馈，并用于状态确认。",
            related_items=missing,
        )


class AlarmCoverageIncompleteRule(ValidationRule):
    rule_id = "ALARM_COVERAGE_INCOMPLETE"
    name = "报警覆盖不足"
    category = "alarm"
    default_severity = Severity.MEDIUM

    def validate(self, context: ValidationContext) -> RuleResult:
        scenario = context.scenario_text
        scopes = multi_device_scopes(context, ACTUATOR_KINDS)
        if scopes:
            failures: list[tuple[str, list[str]]] = []
            for scope in scopes:
                expectations: list[tuple[str, tuple[str, ...]]] = []
                if contains_any_affirmed(
                    scope.scenario_text,
                    EMERGENCY_STOP_TERMS,
                ):
                    expectations.append(("急停", EMERGENCY_STOP_TERMS))
                if scope.device.kind in MOTOR_KINDS:
                    expectations.append(("过载", OVERLOAD_EVENT_TERMS))
                if (
                    scope.device.kind == "pump"
                    and contains_any(scope.scenario_text, WATER_SYSTEM_TERMS)
                ):
                    expectations.append(("液位异常", LEVEL_ABNORMAL_TERMS))
                expectations.extend(
                    (
                        ("执行器故障", ACTUATOR_FAULT_TERMS),
                        ("反馈异常", FEEDBACK_ABNORMAL_TERMS),
                    )
                )
                if scope.device.kind in TIMEOUT_KINDS:
                    expectations.append(("动作超时", TIMEOUT_EVENT_TERMS))
                missing = [
                    label
                    for label, condition_terms in expectations
                    if not terms_near(
                        scope.plan_text,
                        condition_terms,
                        ALARM_TERMS,
                    )
                ]
                if missing:
                    failures.append((scope.device.label, missing))
            if not failures:
                return self.passed("各设备的重要异常均有对应报警说明。")
            return self.result(
                status=RuleStatus.WARNING,
                message="部分设备未覆盖全部相关报警。",
                evidence=_instance_failure_evidence(failures),
                recommendation="逐台补充缺失异常的报警触发、保持和复位说明。",
                related_items=_instance_failure_devices(failures),
            )

        expectations: list[tuple[str, tuple[str, ...]]] = []
        if contains_any(scenario, EMERGENCY_STOP_TERMS):
            expectations.append(("急停", EMERGENCY_STOP_TERMS))
        if has_controlled_device(context, MOTOR_KINDS):
            expectations.append(("过载", OVERLOAD_EVENT_TERMS))
        if contains_any(scenario, WATER_SYSTEM_TERMS):
            expectations.append(("液位异常", LEVEL_ABNORMAL_TERMS))
        if contains_any(scenario, SENSOR_TERMS):
            expectations.append(("传感器异常", SENSOR_FAULT_TERMS))
        if has_controlled_device(context, ACTUATOR_KINDS):
            expectations.append(("执行器故障", ACTUATOR_FAULT_TERMS))
            expectations.append(("反馈异常", FEEDBACK_ABNORMAL_TERMS))
        if has_controlled_device(context, TIMEOUT_KINDS):
            expectations.append(("动作超时", TIMEOUT_EVENT_TERMS))
        if not expectations:
            return self.not_applicable("当前场景未识别到需要报警覆盖的异常类型。")

        missing = [
            label
            for label, condition_terms in expectations
            if not terms_near(context.plan_text, condition_terms, ALARM_TERMS)
        ]
        if not missing:
            return self.passed("当前场景的重要异常均有对应报警说明。")
        return self.result(
            status=RuleStatus.WARNING,
            message="方案未覆盖全部场景相关报警。",
            evidence=[f"缺少报警覆盖：{label}" for label in missing],
            recommendation="为缺失的异常类型增加报警触发、保持和复位说明。",
            related_items=missing,
        )


class PumpDryRunProtectionMissingRule(ValidationRule):
    rule_id = "PUMP_DRY_RUN_PROTECTION_MISSING"
    name = "水泵防干转保护缺失"
    category = "protection"
    default_severity = Severity.CRITICAL

    def validate(self, context: ValidationContext) -> RuleResult:
        scenario = context.scenario_text
        if not (
            has_controlled_device(context, PUMP_KINDS)
            and contains_any(scenario, WATER_SYSTEM_TERMS)
        ):
            return self.not_applicable("当前场景不是包含水泵及液位条件的供液系统。")
        scopes = multi_device_scopes(context, PUMP_KINDS)
        if scopes:
            failures = _instance_failures(scopes, _dry_run_checks)
            if not failures:
                return self.passed("各水泵均包含低液位检测、防干转、停泵和报警。")
            return self.result(
                status=RuleStatus.FAILED,
                message="部分水泵的防干转保护链路不完整。",
                evidence=_instance_failure_evidence(failures),
                recommendation="逐台增加低液位或缺水检测，并联动停泵、防干转和报警。",
                related_items=_instance_failure_devices(failures),
            )
        checks = _dry_run_checks(context.plan_text)
        missing = [name for name, present in checks.items() if not present]
        if not missing:
            return self.passed("方案包含低液位检测、防干转、停泵和报警。")
        return self.result(
            status=RuleStatus.FAILED,
            message="水泵防干转保护链路不完整。",
            evidence=_missing_evidence(missing),
            recommendation="增加低液位或缺水检测，并联动停泵、防干转和报警。",
            related_items=missing,
        )


class ActionTimeoutProtectionMissingRule(ValidationRule):
    rule_id = "ACTION_TIMEOUT_PROTECTION_MISSING"
    name = "动作超时保护缺失"
    category = "protection"
    default_severity = Severity.HIGH

    def validate(self, context: ValidationContext) -> RuleResult:
        if not has_controlled_device(context, TIMEOUT_KINDS):
            return self.not_applicable("当前场景未识别到需要到位确认的阀门或运动机构。")
        scopes = multi_device_scopes(context, TIMEOUT_KINDS)
        if scopes:
            failures = _instance_failures(scopes, _timeout_checks)
            if not failures:
                return self.passed("各设备均包含动作计时、超时判断、停止和报警。")
            return self.result(
                status=RuleStatus.FAILED,
                message="部分设备缺少完整动作超时保护。",
                evidence=_instance_failure_evidence(failures),
                recommendation="逐台增加动作定时、到位超时判断，并联动停止和报警。",
                related_items=_instance_failure_devices(failures),
            )
        checks = _timeout_checks(context.plan_text)
        missing = [name for name, present in checks.items() if not present]
        if not missing:
            return self.passed("方案包含动作计时、超时判断、停止和报警。")
        return self.result(
            status=RuleStatus.FAILED,
            message="需要到位反馈的动作缺少完整超时保护。",
            evidence=_missing_evidence(missing),
            recommendation="增加动作定时、到位超时判断，并联动停止和报警。",
            related_items=missing,
        )


class ModeInterlockMissingRule(ValidationRule):
    rule_id = "MODE_INTERLOCK_MISSING"
    name = "自动/手动模式互锁缺失"
    category = "interlock"
    default_severity = Severity.HIGH

    def validate(self, context: ValidationContext) -> RuleResult:
        if not has_controlled_device(context, ACTUATOR_KINDS):
            return self.not_applicable("当前场景未识别到受控的自动/手动输出设备。")
        applicability_text = f"{context.scenario_text}\n{context.plan_text}"
        if not (
            contains_any(applicability_text, AUTO_TERMS)
            and contains_any(applicability_text, MANUAL_TERMS)
        ):
            return self.not_applicable("当前场景未同时定义自动和手动模式。")
        scopes = multi_device_scopes(context, ACTUATOR_KINDS)
        if scopes:
            applicable_scopes = tuple(
                scope
                for scope in scopes
                if (
                    contains_any(
                        f"{scope.scenario_text}\n{scope.plan_text}",
                        AUTO_TERMS,
                    )
                    and contains_any(
                        f"{scope.scenario_text}\n{scope.plan_text}",
                        MANUAL_TERMS,
                    )
                )
            )
            if not applicable_scopes:
                return self.not_applicable("当前场景未为具体设备同时定义自动和手动模式。")
            failures = _instance_failures(applicable_scopes, _mode_checks)
            if not failures:
                return self.passed("各设备的自动/手动模式切换、权限和互锁说明完整。")
            return self.result(
                status=RuleStatus.FAILED,
                message="部分设备的自动/手动模式缺少互锁或权限约束。",
                evidence=_instance_failure_evidence(failures),
                recommendation="逐台增加唯一模式选择、互锁条件和手动操作权限控制。",
                related_items=_instance_failure_devices(failures),
            )
        checks = _mode_checks(context.plan_text)
        missing = [name for name, present in checks.items() if not present]
        if not missing:
            return self.passed("自动/手动模式切换、权限和互锁说明完整。")
        return self.result(
            status=RuleStatus.FAILED,
            message="自动/手动模式可能同时生效或缺少权限约束。",
            evidence=_missing_evidence(missing),
            recommendation="增加唯一模式选择、互锁条件和手动操作权限控制。",
            related_items=missing,
        )


class SafeStateUndefinedRule(ValidationRule):
    rule_id = "SAFE_STATE_UNDEFINED"
    name = "安全默认状态未定义"
    category = "safety"
    default_severity = Severity.CRITICAL

    def validate(self, context: ValidationContext) -> RuleResult:
        if not has_controlled_device(context, ACTUATOR_KINDS):
            return self.not_applicable("当前场景未识别到需要定义安全状态的重要输出。")

        safe_context_terms = FAULT_TERMS + SAFE_STATE_TERMS
        has_global_safe_action = terms_cooccur(
            context.plan_text,
            safe_context_terms,
            GLOBAL_SAFE_OUTPUT_ACTION_TERMS,
        ) or terms_follow_condition(
            context.plan_text,
            (safe_context_terms,),
            GLOBAL_SAFE_OUTPUT_ACTION_TERMS,
            forbidden_detail_terms=NORMAL_OPERATION_TERMS,
        )
        scopes = multi_device_scopes(context, ACTUATOR_KINDS)
        if scopes:
            if has_global_safe_action:
                return self.passed("方案为所有重要输出定义了故障安全状态。")
            missing_devices = [
                scope.device.label
                for scope in scopes
                if not _safe_scope_covered(
                    scope.plan_text,
                    scope.device.kind,
                )
            ]
            if not missing_devices:
                return self.passed("方案逐台定义了故障、停机或急停状态下的安全输出动作。")
            return self.result(
                status=RuleStatus.FAILED,
                message="部分重要输出的故障安全状态不明确。",
                evidence=[
                    f"{device}未定义安全状态"
                    for device in missing_devices
                ],
                recommendation="逐台定义重要输出在故障、停机或急停时的安全动作。",
                related_items=missing_devices,
            )
        applicable_groups = [
            (label, scenario_terms, action_terms)
            for (label, scenario_terms, action_terms), kind in zip(
                SAFE_OUTPUT_DEVICE_GROUPS,
                (
                    "motor",
                    "pump",
                    "fan",
                    "heater",
                    "valve",
                    "conveyor",
                    "lift",
                    "cylinder",
                ),
                strict=True,
            )
            if has_controlled_device(context, (kind,))
        ]
        uncovered: list[str] = []
        for label, scenario_terms, action_terms in applicable_groups:
            if has_global_safe_action:
                continue
            covered = terms_cooccur(
                context.plan_text,
                safe_context_terms,
                action_terms,
            ) or terms_follow_condition(
                context.plan_text,
                (safe_context_terms,),
                action_terms,
                forbidden_detail_terms=NORMAL_OPERATION_TERMS,
            )
            covered = covered or terms_cooccur(
                context.plan_text,
                safe_context_terms,
                scenario_terms,
                SHARED_SAFE_OUTPUT_ACTION_TERMS,
            )
            if not covered:
                uncovered.append(label)
        if applicable_groups and not uncovered:
            return self.passed("方案定义了故障、停机或急停状态下的安全输出动作。")
        if not applicable_groups:
            generic_safe_action = terms_cooccur(
                context.plan_text,
                safe_context_terms,
                SAFE_OUTPUT_ACTION_TERMS,
            ) or terms_follow_condition(
                context.plan_text,
                (safe_context_terms,),
                SAFE_OUTPUT_ACTION_TERMS,
                forbidden_detail_terms=NORMAL_OPERATION_TERMS,
            )
            if generic_safe_action:
                return self.passed("方案定义了故障、停机或急停状态下的安全输出动作。")
        return self.result(
            status=RuleStatus.FAILED,
            message="重要输出在停机、急停或故障状态下的安全状态不明确。",
            evidence=(
                [f"未定义安全状态：{label}" for label in uncovered]
                or ["未发现故障安全状态或故障条件下的明确停机动作。"]
            ),
            recommendation="逐项定义电机、加热器、阀门等重要输出的故障安全状态。",
            related_items=uncovered,
        )


class IOTableIncompleteRule(ValidationRule):
    rule_id = "IO_TABLE_INCOMPLETE"
    name = "I/O 点表为空或结构不完整"
    category = "io"
    default_severity = Severity.HIGH

    def validate(self, context: ValidationContext) -> RuleResult:
        if not context.structured_io_available:
            return self.not_applicable("当前结果没有可可靠解析的结构化 I/O 点表。")
        if not context.io_points:
            return self.result(
                status=RuleStatus.FAILED,
                message="I/O 点表为空。",
                evidence=["未提供任何可校验的 I/O 点位。"],
                recommendation="补充地址、点位名称、信号类型和设备名称。",
            )

        incomplete: list[str] = []
        related: list[str] = []
        for index, point in enumerate(context.io_points, start=1):
            missing: list[str] = []
            if not point.address:
                missing.append("地址")
            if not point.signal_name:
                missing.append("点位名称")
            if not point.signal_type or canonical_signal_type(point.signal_type) is None:
                missing.append("有效信号类型")
            if not point.device:
                missing.append("设备名称")
            if missing:
                label = _point_label(point)
                incomplete.append(f"第 {index} 行 {label}：缺少{'、'.join(missing)}")
                related.append(label)
        if not incomplete:
            return self.passed("I/O 点表包含可解析的地址、名称、类型和设备信息。")
        return self.result(
            status=RuleStatus.FAILED,
            message="I/O 点表存在结构不完整的行。",
            evidence=incomplete,
            recommendation="补全每个点位的地址、名称、DI/DO/AI/AO 类型和设备名称。",
            related_items=related,
        )


DEFAULT_RULE_TYPES: tuple[type[ValidationRule], ...] = (
    DuplicateAddressRule,
    DuplicateNameRule,
    IOTypeMismatchRule,
    StartStopIncompleteRule,
    EmergencyStopMissingRule,
    MotorOverloadProtectionMissingRule,
    MutualInterlockMissingRule,
    ActuatorFeedbackMissingRule,
    AlarmCoverageIncompleteRule,
    PumpDryRunProtectionMissingRule,
    ActionTimeoutProtectionMissingRule,
    ModeInterlockMissingRule,
    SafeStateUndefinedRule,
    IOTableIncompleteRule,
)


def build_default_rules() -> list[ValidationRule]:
    return [rule_type() for rule_type in DEFAULT_RULE_TYPES]
