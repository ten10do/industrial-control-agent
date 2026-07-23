from collections import defaultdict

from .base import ValidationRule
from .catalog import (
    ACTUATOR_FAULT_TERMS,
    ACTUATOR_TERMS,
    ALARM_TERMS,
    AUTO_TERMS,
    CUT_OUTPUT_TERMS,
    DRY_RUN_TERMS,
    EMERGENCY_STOP_TERMS,
    EMERGENCY_TRIGGER_TERMS,
    EXCLUSIVE_ACTION_PAIRS,
    FAULT_TERMS,
    FEEDBACK_ABNORMAL_TERMS,
    FEEDBACK_DEVICE_GROUPS,
    FEEDBACK_TERMS,
    GENERIC_EXCLUSIVE_TERMS,
    GLOBAL_SAFE_OUTPUT_ACTION_TERMS,
    INTERLOCK_TERMS,
    LEVEL_ABNORMAL_TERMS,
    LOW_LEVEL_TERMS,
    MANUAL_AUTHORITY_TERMS,
    MANUAL_TERMS,
    MODE_SELECT_TERMS,
    MOTION_ACTUATOR_TERMS,
    MOTOR_TERMS,
    NO_SIMULTANEOUS_TERMS,
    NORMAL_OPERATION_TERMS,
    OVERLOAD_EVENT_TERMS,
    OVERLOAD_TERMS,
    OVERLOAD_PROTECTION_TERMS,
    PRIORITY_TERMS,
    PUMP_TERMS,
    RESET_TERMS,
    RUN_STATE_TERMS,
    RUN_STOP_ACTUATOR_TERMS,
    SAFE_OUTPUT_DEVICE_GROUPS,
    SAFE_OUTPUT_ACTION_TERMS,
    SAFE_STATE_TERMS,
    SENSOR_FAULT_TERMS,
    SENSOR_TERMS,
    SHUTDOWN_LOGIC_TERMS,
    START_TERMS,
    STOP_TERMS,
    TIMEOUT_ACTUATOR_TERMS,
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
    is_monitoring_only,
    normalize_address,
    normalize_name,
    terms_cooccur,
    terms_follow_condition,
    terms_follow_trigger,
    terms_near,
    terms_near_owner,
)
from .models import RuleResult, RuleStatus, Severity, ValidationContext, ValidationIOPoint


def _point_label(point: ValidationIOPoint) -> str:
    return point.device or point.signal_name or point.address or "未命名点位"


def _missing_evidence(missing: list[str]) -> list[str]:
    return [f"缺少：{item}" for item in missing]


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
        if is_monitoring_only(context.scenario_text):
            return self.not_applicable("当前场景明确为纯监测，不执行设备启停控制。")
        if not contains_any(context.scenario_text, RUN_STOP_ACTUATOR_TERMS):
            return self.not_applicable("当前场景未识别到需要启停控制的执行设备。")
        checks = {
            "启动条件": contains_any_affirmed(context.plan_text, START_TERMS),
            "停止条件": contains_any_affirmed(context.plan_text, STOP_TERMS),
            "停机输出处理": contains_any_affirmed(context.plan_text, SHUTDOWN_LOGIC_TERMS),
            "运行状态或反馈": contains_any_affirmed(context.plan_text, RUN_STATE_TERMS),
        }
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
        if is_monitoring_only(context.scenario_text):
            return self.not_applicable("当前场景明确为纯监测，不控制运动机构或危险执行器。")
        if not contains_any(context.scenario_text, MOTION_ACTUATOR_TERMS):
            return self.not_applicable("当前场景未识别到运动机构或危险执行器。")
        checks = {
            "急停输入": contains_any_affirmed(context.plan_text, EMERGENCY_STOP_TERMS),
            "急停后输出断开": terms_cooccur(
                context.plan_text,
                EMERGENCY_STOP_TERMS,
                CUT_OUTPUT_TERMS,
            )
            or terms_follow_trigger(
                context.plan_text,
                EMERGENCY_STOP_TERMS,
                EMERGENCY_TRIGGER_TERMS,
                CUT_OUTPUT_TERMS,
            ),
            "急停优先级": terms_cooccur(
                context.plan_text,
                EMERGENCY_STOP_TERMS,
                PRIORITY_TERMS,
            ),
            "复位说明": terms_cooccur(
                context.plan_text,
                EMERGENCY_STOP_TERMS,
                RESET_TERMS,
            )
            or terms_follow_trigger(
                context.plan_text,
                EMERGENCY_STOP_TERMS,
                EMERGENCY_TRIGGER_TERMS,
                RESET_TERMS,
            ),
        }
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
        if is_monitoring_only(context.scenario_text):
            return self.not_applicable("当前场景明确为纯监测，不负责电机类设备保护控制。")
        if not contains_any(context.scenario_text, MOTOR_TERMS):
            return self.not_applicable("当前场景未识别到电机、水泵或风机。")
        checks = {
            "过载检测信号": contains_any_affirmed(context.plan_text, OVERLOAD_TERMS),
            "热继电器或等效保护": contains_any_affirmed(
                context.plan_text,
                OVERLOAD_PROTECTION_TERMS,
            ),
            "过载停机": terms_near(context.plan_text, OVERLOAD_EVENT_TERMS, STOP_TERMS),
            "过载报警": terms_near(context.plan_text, OVERLOAD_EVENT_TERMS, ALARM_TERMS),
        }
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
        if is_monitoring_only(context.scenario_text):
            return self.not_applicable("当前场景明确为纯监测，不执行互斥输出动作。")
        applicability_text = f"{context.scenario_text}\n{context.plan_text}"
        pairs = applicable_exclusive_pairs(applicability_text)
        if contains_any(context.scenario_text, GENERIC_EXCLUSIVE_TERMS):
            pairs.append("互斥输出")
        if not pairs:
            return self.not_applicable("当前场景未识别到明确的互斥动作对。")

        uncovered: list[str] = []
        for label, left_terms, right_terms in EXCLUSIVE_ACTION_PAIRS:
            if label not in pairs:
                continue
            covered = terms_cooccur(
                context.plan_text,
                left_terms,
                right_terms,
                INTERLOCK_TERMS,
            ) or terms_follow_condition(
                context.plan_text,
                (left_terms, right_terms),
                INTERLOCK_TERMS,
            )
            if not covered:
                uncovered.append(label)
        if "互斥输出" in pairs:
            generic_covered = terms_cooccur(
                context.plan_text,
                GENERIC_EXCLUSIVE_TERMS,
                INTERLOCK_TERMS,
            ) or terms_follow_condition(
                context.plan_text,
                (GENERIC_EXCLUSIVE_TERMS,),
                INTERLOCK_TERMS,
            )
            if not generic_covered:
                uncovered.append("互斥输出")
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
        if is_monitoring_only(context.scenario_text):
            return self.not_applicable("当前场景明确为纯监测，不负责执行器动作确认。")
        if not contains_any(context.scenario_text, ACTUATOR_TERMS):
            return self.not_applicable("当前场景未识别到需要状态确认的重要执行器。")

        device_groups = [
            (label, terms)
            for label, terms in FEEDBACK_DEVICE_GROUPS
            if contains_any(context.scenario_text, terms)
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
        expectations: list[tuple[str, tuple[str, ...]]] = []
        scenario = context.scenario_text
        if contains_any(scenario, EMERGENCY_STOP_TERMS):
            expectations.append(("急停", EMERGENCY_STOP_TERMS))
        if contains_any(scenario, MOTOR_TERMS):
            expectations.append(("过载", OVERLOAD_EVENT_TERMS))
        if contains_any(scenario, WATER_SYSTEM_TERMS):
            expectations.append(("液位异常", LEVEL_ABNORMAL_TERMS))
        if contains_any(scenario, SENSOR_TERMS):
            expectations.append(("传感器异常", SENSOR_FAULT_TERMS))
        if contains_any(scenario, ACTUATOR_TERMS):
            expectations.append(("执行器故障", ACTUATOR_FAULT_TERMS))
            expectations.append(("反馈异常", FEEDBACK_ABNORMAL_TERMS))
        if contains_any(scenario, TIMEOUT_ACTUATOR_TERMS):
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
        if is_monitoring_only(scenario):
            return self.not_applicable("当前场景明确为纯监测，不负责水泵防干转控制。")
        if not (contains_any(scenario, PUMP_TERMS) and contains_any(scenario, WATER_SYSTEM_TERMS)):
            return self.not_applicable("当前场景不是包含水泵及液位条件的供液系统。")
        checks = {
            "低液位或缺水检测": contains_any_affirmed(context.plan_text, LOW_LEVEL_TERMS),
            "防干转逻辑": contains_any_affirmed(context.plan_text, DRY_RUN_TERMS),
            "缺水停泵": terms_near(context.plan_text, LOW_LEVEL_TERMS, STOP_TERMS),
            "缺水报警": terms_near(context.plan_text, LOW_LEVEL_TERMS, ALARM_TERMS),
        }
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
        if is_monitoring_only(context.scenario_text):
            return self.not_applicable("当前场景明确为纯监测，不执行需要到位确认的动作。")
        if not contains_any(context.scenario_text, TIMEOUT_ACTUATOR_TERMS):
            return self.not_applicable("当前场景未识别到需要到位确认的阀门或运动机构。")
        checks = {
            "动作计时": contains_any_affirmed(context.plan_text, TIMER_TERMS),
            "到位超时判断": contains_any_affirmed(context.plan_text, TIMEOUT_TERMS),
            "超时停止": terms_near(context.plan_text, TIMEOUT_EVENT_TERMS, STOP_TERMS),
            "超时报警": terms_near(context.plan_text, TIMEOUT_EVENT_TERMS, ALARM_TERMS),
        }
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
        if is_monitoring_only(context.scenario_text):
            return self.not_applicable("当前场景明确为纯监测，不执行自动/手动输出控制。")
        applicability_text = f"{context.scenario_text}\n{context.plan_text}"
        if not (
            contains_any(applicability_text, AUTO_TERMS)
            and contains_any(applicability_text, MANUAL_TERMS)
        ):
            return self.not_applicable("当前场景未同时定义自动和手动模式。")
        checks = {
            "模式选择或切换": contains_any_affirmed(context.plan_text, MODE_SELECT_TERMS),
            "模式互锁": contains_any_affirmed(context.plan_text, INTERLOCK_TERMS),
            "手动权限": contains_any_affirmed(context.plan_text, MANUAL_AUTHORITY_TERMS),
            "禁止同时生效": contains_any_affirmed(
                context.plan_text,
                NO_SIMULTANEOUS_TERMS,
            ),
        }
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
        if is_monitoring_only(context.scenario_text):
            return self.not_applicable("当前场景明确为纯监测，不控制重要输出。")
        if not contains_any(context.scenario_text, ACTUATOR_TERMS):
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
        applicable_groups = [
            (label, action_terms)
            for label, scenario_terms, action_terms in SAFE_OUTPUT_DEVICE_GROUPS
            if contains_any(context.scenario_text, scenario_terms)
        ]
        uncovered: list[str] = []
        for label, action_terms in applicable_groups:
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
