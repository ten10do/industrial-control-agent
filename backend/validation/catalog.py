import re
import unicodedata
from collections.abc import Sequence
from itertools import product


_SEPARATOR_RE = re.compile(r"[\s,，。;；:：、|/\\()\[\]{}<>《》\"'`~!！?？]+")
_NAME_SEPARATOR_RE = re.compile(r"[\s_\-./\\:：,，;；]+")
_SENTENCE_SPLIT_RE = re.compile(r"(?:[。！？!?；;\r\n]+|(?<!\d)\.(?!\d))")
_EVIDENCE_SEPARATOR_RE = re.compile(
    r"(?P<hard>[:：|｜—–]+|\s+(?:-|/|->|→)\s+|(?:但是|然而|但)|"
    r"\b(?:but|however)\b)"
    r"|(?P<conjunction>(?:并且|而且|且)|\band\b)"
    r"|(?P<comma>[,，、]+)"
)
_BETWEEN_AND_RE = re.compile(
    r"(\bbetween\b[^,，:：;；.!?。！？]{0,48}?)\band\b",
    re.IGNORECASE,
)
_BETWEEN_AND_PLACEHOLDER = "__between_pair__"
_OWNER_DETAIL_CONNECTORS = frozenset(
    {
        "",
        "的",
        "的接触器",
        "的辅助触点",
        "的接触器辅助触点",
        "的接触器的",
        "的辅助触点的",
        "的接触器辅助触点的",
        "状态",
        "接触器",
        "接触器的",
        "辅助触点",
        "辅助触点的",
        "接触器辅助触点",
        "接触器辅助触点的",
        "status",
        "contactor",
        "auxiliarycontact",
        "s",
    }
)
_NON_RUNTIME_CONDITION_TERMS = (
    "安装",
    "配置",
    "设置",
    "参数",
    "阈值",
    "调试",
    "测试",
    "维护",
    "检修",
    "install",
    "configure",
    "configuration",
    "setting",
    "parameter",
    "threshold",
    "commission",
    "test",
    "maintenance",
)
_RESULT_CHAIN_BREAK_TERMS = (
    "操作员",
    "工作人员",
    "系统配置",
    "温控",
    "正常操作",
    "正常停机",
    "维护",
    "检修",
    "调试",
    "测试",
    "operator",
    "system configuration",
    "normal operation",
    "normal shutdown",
    "maintenance",
    "commission",
    "test",
)
_CONDITION_PREFIX_RE = re.compile(
    r"^(?:(?:设备|系统|回路|电机|水泵|风机|阀门|传感器|执行器|反馈|电源)?"
    r"(?:发生|出现|检测到)?"
    r"(?:故障|异常|失效|断电|失电|过载|超时|低液位|缺水|急停)"
    r"|(?:故障|异常|急停|过载|超时)(?:清除|恢复|复位))"
)
_OWNER_DETAIL_CONNECTOR_RE = re.compile(
    r"^(?:的)?(?:(?:主|辅助)?接触器(?:辅助触点)?|辅助触点)(?:的)?$"
    r"|^(?:the)?(?:main|auxiliary)?contactor(?:auxiliarycontact)?s?$"
)
_NEGATION_BEFORE_RE = re.compile(
    r"(?:未(?:设置|配置|定义|提供|包含|使用|检测到)?|没有|无|缺少|无法|并非|不(?:能|会|可|含|具备)?|"
    r"\b(?:not|no|without|missing|lack(?:s|ing)?)\b)\s*(?:明确|任何|有效|可靠)?"
    r"(?:[\w\u3400-\u9fff-]+\s*){0,3}$"
)
_NEGATION_AFTER_RE = re.compile(
    r"^\s*(?:[\w\u3400-\u9fff-]{0,12}\s*)?"
    r"(?:未(?:设置|配置|定义|提供|实现)?|没有|缺失|不存在|不可用|不足|"
    r"\bis\s+missing\b|\bmissing\b|\babsent\b|\bundefined\b|"
    r"\bnot\s+(?:set|configured|defined|available)\b)"
)


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return _SEPARATOR_RE.sub(" ", normalized).strip()


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    return _NAME_SEPARATOR_RE.sub("", normalized).strip()


def normalize_address(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").upper()
    address = re.sub(r"\s+", "", normalized).lstrip("%")
    if address.startswith(("IX", "QX")):
        address = f"{address[0]}{address[2:]}"
    return address


def contains_any(text: str, terms: Sequence[str]) -> bool:
    normalized = normalize_text(text)
    return any(normalize_text(term) in normalized for term in terms)


def _term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term)
    if re.fullmatch(r"[a-z0-9][a-z0-9 -]*", term):
        return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])")
    return re.compile(escaped)


def _is_negated(normalized_text: str, start: int, end: int) -> bool:
    before = normalized_text[max(0, start - 28) : start]
    after = normalized_text[end : min(len(normalized_text), end + 24)]
    return bool(_NEGATION_BEFORE_RE.search(before) or _NEGATION_AFTER_RE.match(after))


def _sentences(text: str) -> list[str]:
    return [sentence for sentence in _SENTENCE_SPLIT_RE.split(text or "") if sentence.strip()]


def _protect_exclusive_pair_conjunctions(sentence: str) -> str:
    protected_sentence = _BETWEEN_AND_RE.sub(
        rf"\1{_BETWEEN_AND_PLACEHOLDER}",
        sentence,
    )
    for _, left_terms, right_terms in EXCLUSIVE_ACTION_PAIRS:
        for left_term, right_term in product(left_terms, right_terms):
            if not (
                re.fullmatch(r"[a-z][a-z ]*", left_term)
                and re.fullmatch(r"[a-z][a-z ]*", right_term)
            ):
                continue
            for first_term, second_term in (
                (left_term, right_term),
                (right_term, left_term),
            ):
                pattern = re.compile(
                    rf"(?<![a-z0-9])({re.escape(first_term)})"
                    rf"(\s+(?:command|commands|output|outputs|motion|direction|action))?"
                    rf"\s+and\s+({re.escape(second_term)})"
                    rf"(\s+(?:command|commands|output|outputs|motion|direction|action))?"
                    rf"(?![a-z0-9])",
                    re.IGNORECASE,
                )
                protected_sentence = pattern.sub(
                    rf"\1\2 {_BETWEEN_AND_PLACEHOLDER} \3\4",
                    protected_sentence,
                )
    return protected_sentence


def _evidence_units(sentence: str) -> list[tuple[str, str]]:
    protected_sentence = _protect_exclusive_pair_conjunctions(sentence)
    units: list[tuple[str, str]] = []
    start = 0
    preceding_separator = "start"
    for match in _EVIDENCE_SEPARATOR_RE.finditer(protected_sentence):
        clause = protected_sentence[start : match.start()]
        if clause.strip():
            units.append(
                (
                    clause.replace(_BETWEEN_AND_PLACEHOLDER, "and"),
                    preceding_separator,
                )
            )
        preceding_separator = match.lastgroup or "hard"
        start = match.end()
    clause = protected_sentence[start:]
    if clause.strip():
        units.append(
            (
                clause.replace(_BETWEEN_AND_PLACEHOLDER, "and"),
                preceding_separator,
            )
        )
    return units


def _evidence_clauses(sentence: str) -> list[str]:
    return [clause for clause, _ in _evidence_units(sentence)]


def _affirmed_positions_in_clause(clause: str, terms: Sequence[str]) -> list[int]:
    return [
        start
        for start, _ in _affirmed_spans_in_clause(clause, terms)
    ]


def _affirmed_spans_in_clause(
    clause: str,
    terms: Sequence[str],
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    normalized_clause = normalize_text(clause)
    for term in terms:
        normalized_term = normalize_text(term)
        if not normalized_term:
            continue
        for match in _term_pattern(normalized_term).finditer(normalized_clause):
            if not _is_negated(normalized_clause, match.start(), match.end()):
                spans.append((match.start(), match.end()))
    return spans


def _affirmed_positions_in_sentence(sentence: str, terms: Sequence[str]) -> list[int]:
    positions: list[int] = []
    offset = 0
    for clause in _evidence_clauses(sentence):
        normalized_clause = normalize_text(clause)
        positions.extend(
            offset + position
            for position in _affirmed_positions_in_clause(clause, terms)
        )
        offset += len(normalized_clause) + 1
    return positions


def affirmed_term_positions(text: str, terms: Sequence[str]) -> list[int]:
    positions: list[int] = []
    offset = 0
    for sentence in _sentences(text):
        normalized_sentence = normalize_text(sentence)
        positions.extend(
            offset + position
            for position in _affirmed_positions_in_sentence(sentence, terms)
        )
        offset += len(normalized_sentence) + 1
    return positions


def contains_any_affirmed(text: str, terms: Sequence[str]) -> bool:
    return bool(affirmed_term_positions(text, terms))


def matched_terms(text: str, terms: Sequence[str]) -> list[str]:
    normalized = normalize_text(text)
    return [term for term in terms if normalize_text(term) in normalized]


def terms_follow_inline_condition(
    text: str,
    condition_terms: Sequence[str],
    detail_terms: Sequence[str],
    *,
    window: int = 80,
) -> bool:
    """Link a Chinese condition ending in 时/后/则 to its inline result."""
    for sentence in _sentences(text):
        for clause in _evidence_clauses(sentence):
            normalized_clause = normalize_text(clause)
            for _, condition_end in _affirmed_spans_in_clause(
                clause,
                condition_terms,
            ):
                suffix = normalized_clause[condition_end:]
                boundary = re.match(r"^\s*(?:时|后|则)\s*", suffix)
                if not boundary:
                    continue
                condition_clause = normalized_clause[
                    : condition_end + boundary.end()
                ]
                if not _looks_like_condition(
                    condition_clause,
                    (condition_terms,),
                ):
                    continue
                result_clause = suffix[boundary.end():]
                if (
                    len(normalize_text(condition_clause))
                    + len(normalize_text(result_clause))
                    <= window
                    and _affirmed_positions_in_clause(
                        result_clause,
                        detail_terms,
                    )
                ):
                    return True
    return False


def terms_near(
    text: str,
    left_terms: Sequence[str],
    right_terms: Sequence[str],
    *,
    window: int = 80,
) -> bool:
    return terms_cooccur(
        text,
        left_terms,
        right_terms,
        window=window,
    ) or terms_follow_condition(
        text,
        (left_terms,),
        right_terms,
        window=window,
    ) or terms_follow_inline_condition(
        text,
        left_terms,
        right_terms,
        window=window,
    )


def terms_cooccur(
    text: str,
    *term_groups: Sequence[str],
    window: int = 80,
) -> bool:
    """Return true when affirmed terms from every group occur in one clause."""
    if not term_groups:
        return False
    for sentence in _sentences(text):
        for clause in _evidence_clauses(sentence):
            position_groups = [
                _affirmed_positions_in_clause(clause, terms)
                for terms in term_groups
            ]
            if any(not positions for positions in position_groups):
                continue
            if any(
                max(combination) - min(combination) <= window
                for combination in product(*position_groups)
            ):
                return True
    return False


def _looks_like_condition(
    clause: str,
    anchor_groups: Sequence[Sequence[str]],
) -> bool:
    normalized = normalize_text(clause)
    if any(
        normalize_text(term) in normalized
        for term in _NON_RUNTIME_CONDITION_TERMS
    ):
        return False
    chinese_condition = (
        normalized.endswith("之间")
        or normalized.endswith("则")
        or (
            normalized.endswith("时")
            and not normalized.endswith(("超时", "计时"))
        )
        or any(
            normalized.endswith(f"{normalize_text(term)}后")
            for terms in anchor_groups
            for term in terms
            if normalize_text(term)
        )
    )
    return chinese_condition or bool(
        re.search(r"\b(?:when|if|upon|on|between)\b", normalized)
    )


def _starts_new_condition(clause: str) -> bool:
    normalized = normalize_text(clause)
    return bool(
        _CONDITION_PREFIX_RE.match(normalized)
        or re.match(r"^(?:正常|常规|日常|维护|检修)", normalized)
        or re.match(r"^(?:.{1,16})(?:时|后)", normalized)
        or re.match(r"^(?:when|if|upon|on|after|normal|routine|maintenance)\b", normalized)
    )


def _continues_result_chain(clause: str) -> bool:
    normalized = normalize_text(clause)
    if re.match(r"^(?:手动|人工)(?!复位)", normalized):
        return False
    return not any(
        normalize_text(term) in normalized
        for term in _RESULT_CHAIN_BREAK_TERMS
    )


def _is_owner_detail_connector(value: str) -> bool:
    compact = value.replace(" ", "")
    return (
        compact in _OWNER_DETAIL_CONNECTORS
        or bool(_OWNER_DETAIL_CONNECTOR_RE.fullmatch(compact))
    )


def terms_follow_condition(
    text: str,
    anchor_groups: Sequence[Sequence[str]],
    detail_terms: Sequence[str],
    *,
    forbidden_detail_terms: Sequence[str] = (),
    window: int = 80,
) -> bool:
    """Link a condition to its comma result and continuing conjunction chain."""
    for sentence in _sentences(text):
        units = _evidence_units(sentence)
        for index, (clause, _) in enumerate(units):
            if not _looks_like_condition(clause, anchor_groups):
                continue
            if any(
                not _affirmed_positions_in_clause(clause, terms)
                for terms in anchor_groups
            ):
                continue
            for detail_index in range(index + 1, len(units)):
                detail_clause, separator = units[detail_index]
                if separator == "hard":
                    break
                if separator == "comma" and not _continues_result_chain(detail_clause):
                    break
                if (
                    detail_index > index + 1
                    and separator not in {"conjunction", "comma"}
                ):
                    break
                if _starts_new_condition(detail_clause):
                    break
                if forbidden_detail_terms and contains_any_affirmed(
                    detail_clause,
                    forbidden_detail_terms,
                ):
                    break
                detail_positions = _affirmed_positions_in_clause(
                    detail_clause,
                    detail_terms,
                )
                if detail_positions and (
                    len(normalize_text(clause))
                    + len(normalize_text(detail_clause))
                    <= window
                ):
                    return True
    return False


def terms_follow_trigger(
    text: str,
    subject_terms: Sequence[str],
    trigger_terms: Sequence[str],
    detail_terms: Sequence[str],
) -> bool:
    """Match details in the trigger clause or its immediate, unqualified result."""
    for sentence in _sentences(text):
        units = _evidence_units(sentence)
        for index, (clause, separator) in enumerate(units):
            trigger_positions = _affirmed_positions_in_clause(clause, trigger_terms)
            if not trigger_positions:
                continue
            subject_here = _affirmed_positions_in_clause(clause, subject_terms)
            subject_before = (
                index > 0
                and separator != "hard"
                and _affirmed_positions_in_clause(units[index - 1][0], subject_terms)
            )
            if not subject_here and not subject_before:
                continue
            if _affirmed_positions_in_clause(clause, detail_terms):
                return True
            for detail_index in range(index + 1, len(units)):
                detail_clause, detail_separator = units[detail_index]
                if detail_separator == "hard":
                    break
                if detail_separator == "comma" and not _continues_result_chain(
                    detail_clause
                ):
                    break
                if (
                    detail_index > index + 1
                    and detail_separator not in {"conjunction", "comma"}
                ):
                    break
                if _starts_new_condition(detail_clause):
                    break
                if _affirmed_positions_in_clause(detail_clause, detail_terms):
                    return True
    return False


def terms_near_owner(
    text: str,
    owner_terms: Sequence[str],
    detail_terms: Sequence[str],
    all_owner_groups: Sequence[Sequence[str]],
    *,
    window: int = 80,
) -> bool:
    """Associate feedback only through an explicit local device-feedback phrase."""
    for sentence in _sentences(text):
        for clause in _evidence_clauses(sentence):
            normalized_clause = normalize_text(clause)
            owner_spans = _affirmed_spans_in_clause(clause, owner_terms)
            detail_spans = _affirmed_spans_in_clause(clause, detail_terms)
            if not owner_spans or not detail_spans:
                continue
            competing_positions = [
                start
                for terms in all_owner_groups
                if tuple(terms) != tuple(owner_terms)
                for start, _ in _affirmed_spans_in_clause(clause, terms)
            ]
            for detail_start, _ in detail_spans:
                linked_owners = [
                    (owner_start, owner_end)
                    for owner_start, owner_end in owner_spans
                    if owner_end <= detail_start
                    and _is_owner_detail_connector(
                        normalized_clause[owner_end:detail_start]
                    )
                ]
                if not linked_owners:
                    continue
                owner_distance = min(
                    detail_start - owner_start
                    for owner_start, _ in linked_owners
                )
                competing_distance = min(
                    (
                        abs(competing_position - detail_start)
                        for competing_position in competing_positions
                    ),
                    default=window + 1,
                )
                if owner_distance <= window and owner_distance <= competing_distance:
                    return True
    return False


INPUT_DEVICE_TERMS = (
    "按钮",
    "按键",
    "开关",
    "急停",
    "传感器",
    "限位",
    "液位",
    "压力检测",
    "温度检测",
    "反馈",
    "button",
    "switch",
    "emergency stop",
    "e-stop",
    "sensor",
    "transmitter",
    "limit",
    "level",
    "feedback",
)

OUTPUT_DEVICE_TERMS = (
    "电机",
    "水泵",
    "风机",
    "电磁阀",
    "接触器",
    "指示灯",
    "蜂鸣器",
    "加热器",
    "气缸",
    "执行器",
    "motor",
    "pump",
    "fan",
    "solenoid",
    "contactor",
    "lamp",
    "buzzer",
    "heater",
    "actuator",
)

DIGITAL_TERMS = (
    "按钮",
    "开关",
    "急停",
    "限位",
    "到位",
    "触点",
    "数字量",
    "开关量",
    "button",
    "switch",
    "e-stop",
    "limit",
    "contact",
    "digital",
    "discrete",
)

ANALOG_TERMS = (
    "模拟量",
    "4-20ma",
    "0-10v",
    "变送器",
    "连续量",
    "analog",
    "transmitter",
)

ACTUATOR_TERMS = (
    "电机",
    "水泵",
    "风机",
    "输送带",
    "输送机",
    "传送带",
    "输送",
    "传送",
    "阀门",
    "电磁阀",
    "气缸",
    "升降机",
    "升降",
    "加热器",
    "执行器",
    "motor",
    "pump",
    "fan",
    "conveyor",
    "valve",
    "cylinder",
    "lift",
    "heater",
    "actuator",
)

RUN_STOP_ACTUATOR_TERMS = (
    "电机",
    "水泵",
    "风机",
    "输送机",
    "输送带",
    "传送带",
    "motor",
    "pump",
    "fan",
    "conveyor",
)

MOTION_ACTUATOR_TERMS = (
    "电机",
    "水泵",
    "风机",
    "输送",
    "传送",
    "阀门",
    "气缸",
    "升降",
    "机械",
    "motor",
    "pump",
    "fan",
    "conveyor",
    "valve",
    "cylinder",
    "lift",
    "motion",
)

MOTOR_TERMS = ("电机", "水泵", "风机", "motor", "pump", "fan")
PUMP_TERMS = ("水泵", "泵", "pump")
WATER_SYSTEM_TERMS = (
    "水箱",
    "水塔",
    "储液",
    "液位",
    "缺水",
    "低液位",
    "tank",
    "reservoir",
    "liquid level",
    "low level",
    "water",
)
SENSOR_TERMS = ("传感器", "检测器", "变送器", "sensor", "detector", "transmitter")
TIMEOUT_ACTUATOR_TERMS = (
    "阀门",
    "电磁阀",
    "升降",
    "输送",
    "传送",
    "气缸",
    "valve",
    "lift",
    "conveyor",
    "cylinder",
)

START_TERMS = ("启动", "起动", "运行命令", "start", "run command")
STOP_TERMS = ("停止", "停机", "断开输出", "失电", "stop", "shutdown", "de-energize")
SHUTDOWN_LOGIC_TERMS = (
    "复位输出",
    "切断输出",
    "断开输出",
    "输出失电",
    "停止所有",
    "reset output",
    "disable output",
    "de-energize",
)
RUN_STATE_TERMS = (
    "运行状态",
    "运行反馈",
    "接触器反馈",
    "到位",
    "状态反馈",
    "run status",
    "running feedback",
    "position feedback",
)
EMERGENCY_STOP_TERMS = ("急停", "紧急停止", "emergency stop", "e-stop")
EMERGENCY_TRIGGER_TERMS = (
    "触发后",
    "动作后",
    "急停后",
    "急停时",
    "发生急停时",
    "when triggered",
    "on activation",
    "on emergency stop",
)
CUT_OUTPUT_TERMS = (
    "断开输出",
    "切断输出",
    "断开危险输出",
    "断开所有危险输出",
    "切断危险输出",
    "切断所有危险输出",
    "立即停止",
    "失电",
    "断电",
    "de-energize",
    "disconnect output",
    "disconnect hazardous outputs",
    "de-energize hazardous outputs",
    "stop all",
)
IMMEDIATE_ACTION_TERMS = ("立即", "即刻", "immediately", "at once")
PRIORITY_TERMS = ("最高优先级", "优先于", "急停优先", "highest priority", "overrides")
RESET_TERMS = ("人工复位", "手动复位", "复位后", "reset", "manual reset")
RESTART_TERMS = ("重新启动", "再次启动", "重新起动", "restart", "start again")
OVERLOAD_TERMS = ("过载", "热继电器", "电机保护器", "overload", "thermal relay")
OVERLOAD_EVENT_TERMS = ("过载", "overload")
OVERLOAD_PROTECTION_TERMS = (
    "热继电器",
    "电机保护器",
    "过载保护",
    "过载继电器",
    "thermal relay",
    "motor protector",
    "motor protection",
    "overload relay",
    "overload protection",
)
ALARM_TERMS = ("报警", "告警", "蜂鸣", "alarm", "warning")
INTERLOCK_TERMS = (
    "互锁",
    "互斥",
    "禁止同时",
    "不得同时",
    "interlock",
    "mutually exclusive",
    "not simultaneously",
)
FEEDBACK_TERMS = (
    "运行反馈",
    "接触器反馈",
    "故障反馈",
    "开到位",
    "关到位",
    "到位信号",
    "限位反馈",
    "position feedback",
    "run feedback",
    "fault feedback",
    "limit feedback",
)
LOW_LEVEL_TERMS = ("低液位", "液位过低", "缺水", "无水", "low level", "water shortage", "no water")
DRY_RUN_TERMS = ("防干转", "干转保护", "空转保护", "dry run", "dry-running")
START_INHIBIT_TERMS = (
    "禁止启动",
    "禁止水泵启动",
    "禁止泵启动",
    "不允许启动",
    "启动闭锁",
    "启动禁止",
    "inhibit start",
    "start inhibited",
    "prevent pump start",
)
TIMER_TERMS = ("计时", "定时器", "计时器", "timer", "timing")
TIMEOUT_TERMS = ("超时", "到位超时", "动作超时", "timeout")
DEADLINE_NOT_REACHED_TERMS = (
    "限定时间内未到位",
    "规定时间内未到位",
    "设定时间内未到位",
    "未在限定时间内到位",
    "未在规定时间内到位",
    "未在设定时间内到位",
    "fails to reach position within",
    "not reached within the specified time",
)
TIMEOUT_EVENT_TERMS = (
    "到位超时",
    "动作超时",
    "timeout",
    "timed out",
) + DEADLINE_NOT_REACHED_TERMS
AUTO_TERMS = ("自动模式", "自动运行", "auto mode", "automatic mode")
MANUAL_TERMS = ("手动模式", "手动操作", "manual mode", "manual operation")
MODE_SELECT_TERMS = ("模式切换", "模式选择", "选择开关", "mode selection", "mode switch")
MANUAL_AUTHORITY_TERMS = (
    "手动权限",
    "授权",
    "权限控制",
    "manual permission",
    "authorized manual",
)
NO_SIMULTANEOUS_TERMS = (
    "禁止同时",
    "不得同时",
    "不能同时",
    "避免同时",
    "not simultaneously",
    "cannot run together",
)
SENSOR_FAULT_TERMS = ("传感器异常", "传感器故障", "sensor fault", "sensor failure")
ACTUATOR_FAULT_TERMS = (
    "执行器故障",
    "电机故障",
    "水泵故障",
    "阀门故障",
    "actuator fault",
    "motor fault",
    "pump fault",
    "valve fault",
)
LEVEL_ABNORMAL_TERMS = (
    "高液位",
    "低液位",
    "液位过高",
    "液位过低",
    "high level",
    "low level",
)
FEEDBACK_ABNORMAL_TERMS = (
    "反馈异常",
    "反馈故障",
    "反馈不一致",
    "feedback fault",
    "feedback mismatch",
)
FAULT_TERMS = (
    "故障",
    "异常",
    "急停",
    "fault",
    "failure",
    "emergency",
)
NORMAL_OPERATION_TERMS = (
    "正常",
    "常规",
    "日常",
    "维护",
    "检修",
    "normal",
    "routine",
    "maintenance",
)
SAFE_STATE_TERMS = (
    "安全状态",
    "故障安全",
    "安全位置",
    "默认关闭",
    "默认停止",
    "fail-safe",
    "safe state",
    "safe position",
)
SAFE_OUTPUT_ACTION_TERMS = (
    "电机停止",
    "水泵停止",
    "风机停止",
    "加热器关闭",
    "阀门关闭",
    "阀门打开",
    "阀门回到",
    "执行器停止",
    "输出进入默认停止",
    "输出默认停止",
    "停止所有输出",
    "所有输出失电",
    "输出失电",
    "切断输出",
    "断开输出",
    "motor stops",
    "pump stops",
    "fan stops",
    "heater off",
    "valve closed",
    "valve open",
    "safe valve position",
    "actuator stops",
    "stop outputs",
    "stop all outputs",
    "outputs de-energize",
    "de-energize outputs",
)
GLOBAL_SAFE_OUTPUT_ACTION_TERMS = (
    "所有重要输出进入默认停止",
    "所有重要输出进入安全状态",
    "停止所有输出",
    "所有输出失电",
    "all important outputs enter a safe state",
    "stop all outputs",
    "all outputs de-energize",
)
SHARED_SAFE_OUTPUT_ACTION_TERMS = (
    "均保持关闭",
    "均保持停止",
    "均关闭",
    "均停止",
    "全部保持关闭",
    "全部保持停止",
    "both remain off",
    "all remain off",
    "all remain stopped",
)
SAFE_OUTPUT_DEVICE_GROUPS = (
    (
        "电机",
        ("电机", "motor"),
        ("电机停止", "电机失电", "motor stops", "motor de-energizes"),
    ),
    (
        "水泵",
        ("水泵", "泵", "pump"),
        ("水泵停止", "水泵失电", "pump stops", "pump de-energizes"),
    ),
    (
        "风机",
        ("风机", "fan"),
        ("风机停止", "风机失电", "fan stops", "fan de-energizes"),
    ),
    (
        "加热器",
        ("加热器", "heater"),
        ("加热器关闭", "加热器失电", "heater off", "heater de-energizes"),
    ),
    (
        "阀门",
        ("阀门", "电磁阀", "valve", "solenoid"),
        (
            "阀门关闭",
            "阀门打开",
            "阀门回到",
            "安全位置",
            "valve closed",
            "valve open",
            "safe valve position",
        ),
    ),
    (
        "输送机构",
        ("输送", "传送", "conveyor"),
        ("输送机停止", "输送带停止", "传送带停止", "conveyor stops"),
    ),
    (
        "升降机构",
        ("升降", "lift"),
        ("升降停止", "升降机构停止", "lift stops"),
    ),
    (
        "气缸",
        ("气缸", "cylinder"),
        ("气缸停止", "气缸回到安全位置", "cylinder stops"),
    ),
)

MONITOR_ONLY_TERMS = (
    "仅监测",
    "只监测",
    "纯监测",
    "仅采集",
    "只采集",
    "不控制",
    "无需控制",
    "monitor only",
    "monitoring only",
    "read-only monitoring",
    "no control",
)
CONTROL_INTENT_TERMS = (
    "需要控制",
    "负责控制",
    "进行控制",
    "只控制",
    "执行控制",
    "执行启停",
    "控制电机",
    "控制水泵",
    "控制风机",
    "控制阀门",
    "控制执行器",
    "驱动电机",
    "驱动水泵",
    "control required",
    "requires control",
    "motor control required",
    "actuator control required",
)
CONTROL_ACTION_TERMS = (
    "使",
    "令",
    "让",
    "控制",
    "启停",
    "启动",
    "起动",
    "停止",
    "停机",
    "停运",
    "开启",
    "关闭",
    "开动",
    "驱动",
    "control",
    "controls",
    "controlled",
    "command",
    "commands",
    "commanded",
    "run",
    "runs",
    "running",
    "start",
    "starts",
    "stop",
    "stops",
    "drive",
    "drives",
    "driven",
    "actuate",
    "actuates",
    "actuated",
    "operate",
    "operates",
    "operated",
    "activate",
    "activates",
    "activated",
    "deactivate",
    "deactivates",
    "deactivated",
    "open",
    "opens",
    "opened",
    "close",
    "closes",
    "closed",
)
STATE_LIKE_CONTROL_ACTION_TERMS = frozenset(
    {
        "启停",
        "启动",
        "起动",
        "停止",
        "停机",
        "停运",
        "开启",
        "关闭",
        "开动",
        "start",
        "starts",
        "stop",
        "stops",
        "run",
        "runs",
        "running",
        "operate",
        "operates",
        "operated",
        "activate",
        "activates",
        "activated",
        "deactivate",
        "deactivates",
        "deactivated",
        "open",
        "opens",
        "opened",
        "close",
        "closes",
        "closed",
    }
)
CONTROL_STATE_MARKERS = (
    "状态",
    "次数",
    "计数",
    "频率",
    "status",
    "count",
    "times",
    "frequency",
)

GENERIC_EXCLUSIVE_TERMS = (
    "互斥输出",
    "不能同时动作",
    "不得同时动作",
    "禁止同时动作",
    "mutually exclusive outputs",
    "cannot operate simultaneously",
)

FEEDBACK_DEVICE_GROUPS = (
    ("电机", ("电机", "motor")),
    ("水泵", ("水泵", "泵", "pump")),
    ("风机", ("风机", "fan")),
    ("压缩机", ("压缩机", "compressor")),
    ("阀门", ("阀门", "电磁阀", "valve", "solenoid")),
    ("输送机构", ("输送", "传送", "conveyor")),
    ("升降机构", ("升降", "lift")),
    ("气缸", ("气缸", "cylinder")),
)

EXCLUSIVE_ACTION_PAIRS = (
    ("正转/反转", ("正转", "forward"), ("反转", "reverse")),
    ("上升/下降", ("上升", "提升", "raise", "upward"), ("下降", "lower", "downward")),
    ("开阀/关阀", ("开阀", "开启阀", "open valve"), ("关阀", "关闭阀", "close valve")),
    ("前进/后退", ("前进", "forward travel"), ("后退", "reverse travel")),
    ("加热/紧急冷却", ("加热", "heating"), ("紧急冷却", "emergency cooling")),
)
EXCLUSIVE_ACTION_COMPOUND_TERMS = {
    "正转/反转": ("正反转", "forward/reverse"),
}


def canonical_signal_type(value: str) -> str | None:
    compact = normalize_name(value)
    aliases = {
        "di": "DI",
        "digitalinput": "DI",
        "数字输入": "DI",
        "开关量输入": "DI",
        "do": "DO",
        "digitaloutput": "DO",
        "数字输出": "DO",
        "开关量输出": "DO",
        "ai": "AI",
        "analoginput": "AI",
        "模拟输入": "AI",
        "模拟量输入": "AI",
        "ao": "AO",
        "analogoutput": "AO",
        "模拟输出": "AO",
        "模拟量输出": "AO",
    }
    if compact in aliases:
        return aliases[compact]
    for alias, canonical in aliases.items():
        if len(alias) > 2 and alias in compact:
            return canonical
    return None


def address_direction(value: str) -> str | None:
    address = normalize_address(value).lstrip("%")
    if address.startswith(("I", "X")):
        return "input"
    if address.startswith(("Q", "Y")):
        return "output"
    return None


def expected_direction(text: str) -> str | None:
    has_input = contains_any(text, INPUT_DEVICE_TERMS)
    has_output = contains_any(text, OUTPUT_DEVICE_TERMS)
    if has_input == has_output:
        return None
    return "input" if has_input else "output"


def expected_signal_kind(text: str) -> str | None:
    has_analog = contains_any(text, ANALOG_TERMS)
    has_digital = contains_any(text, DIGITAL_TERMS)
    if has_analog == has_digital:
        return None
    return "analog" if has_analog else "digital"


def applicable_exclusive_pairs(text: str) -> list[str]:
    return [
        label
        for label, left_terms, right_terms in EXCLUSIVE_ACTION_PAIRS
        if (
            contains_any(text, left_terms)
            and contains_any(text, right_terms)
        )
        or contains_any(text, EXCLUSIVE_ACTION_COMPOUND_TERMS.get(label, ()))
    ]


def is_monitoring_only(text: str) -> bool:
    return (
        contains_any_affirmed(text, MONITOR_ONLY_TERMS)
        and not (
            contains_any_affirmed(text, CONTROL_INTENT_TERMS)
            or _has_structured_control_intent(text)
        )
    )


def _has_structured_control_intent(text: str) -> bool:
    for sentence in _sentences(text):
        for clause in _evidence_clauses(sentence):
            normalized_clause = normalize_text(clause)
            actuator_spans = _affirmed_spans_in_clause(
                clause,
                ACTUATOR_TERMS,
            )
            if not actuator_spans:
                continue
            for term in CONTROL_ACTION_TERMS:
                normalized_term = normalize_text(term)
                for match in _term_pattern(normalized_term).finditer(normalized_clause):
                    if _is_negated(normalized_clause, match.start(), match.end()):
                        continue
                    suffix = normalized_clause[match.end() :].lstrip()
                    if normalized_term == "使" and suffix.startswith("用"):
                        continue
                    if suffix.startswith(
                        (
                            "系统",
                            "器",
                            "柜",
                            "回路",
                            "逻辑",
                            "状态",
                            "反馈",
                            "信号",
                            "按钮",
                            "开关",
                            "次数",
                            "计数",
                            "频率",
                            "system",
                            "controller",
                            "cabinet",
                            "logic",
                            "status",
                            "feedback",
                            "signal",
                            "button",
                            "switch",
                            "count",
                            "times",
                            "frequency",
                        )
                    ):
                        continue
                    for actuator_start, actuator_end in actuator_spans:
                        if 0 <= actuator_start - match.start() <= 48:
                            if (
                                normalized_term in STATE_LIKE_CONTROL_ACTION_TERMS
                                and any(
                                    marker
                                    in normalized_clause[
                                        actuator_end : actuator_end + 24
                                    ]
                                    for marker in CONTROL_STATE_MARKERS
                                )
                            ):
                                continue
                            return True
                        if not (0 <= match.start() - actuator_end <= 48):
                            continue
                        between = normalized_clause[
                            actuator_end:match.start()
                        ].strip()
                        if (
                            normalized_term in STATE_LIKE_CONTROL_ACTION_TERMS
                            and any(
                                marker in suffix[:24]
                                for marker in CONTROL_STATE_MARKERS
                            )
                        ):
                            continue
                        if (
                            normalized_term
                            in {
                                "controlled",
                                "commanded",
                                "driven",
                                "actuated",
                                "operated",
                            }
                            or "由" in between
                            or normalized_term in STATE_LIKE_CONTROL_ACTION_TERMS
                            and not between
                        ):
                            return True
    return False
