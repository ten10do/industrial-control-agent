import re
import unicodedata
from collections.abc import Sequence


_SEPARATOR_RE = re.compile(r"[\s,，。;；:：、|/\\()\[\]{}<>《》\"'`~!！?？]+")
_NAME_SEPARATOR_RE = re.compile(r"[\s_\-./\\:：,，;；]+")
_NEGATION_BEFORE_RE = re.compile(
    r"(?:未(?:设置|配置|定义|提供|包含|使用|检测到)?|没有|无|缺少|无法|不(?:能|会|可|含|具备)?|"
    r"not|no|without|missing|lack(?:s|ing)?)\s*(?:明确|任何|有效|可靠)?"
    r"(?:[\w\u3400-\u9fff-]+\s*){0,3}$"
)
_NEGATION_AFTER_RE = re.compile(
    r"^\s*(?:[\w\u3400-\u9fff-]{0,12}\s*)?"
    r"(?:未(?:设置|配置|定义|提供|实现)?|没有|缺失|不存在|不可用|不足|"
    r"is\s+missing|missing|absent|undefined|not\s+(?:set|configured|defined|available))"
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


def _is_negated(normalized_text: str, start: int, end: int) -> bool:
    before = normalized_text[max(0, start - 28) : start]
    after = normalized_text[end : min(len(normalized_text), end + 24)]
    return bool(_NEGATION_BEFORE_RE.search(before) or _NEGATION_AFTER_RE.match(after))


def affirmed_term_positions(text: str, terms: Sequence[str]) -> list[int]:
    normalized = normalize_text(text)
    positions: list[int] = []
    for term in terms:
        normalized_term = normalize_text(term)
        if not normalized_term:
            continue
        for match in re.finditer(re.escape(normalized_term), normalized):
            if not _is_negated(normalized, match.start(), match.end()):
                positions.append(match.start())
    return positions


def contains_any_affirmed(text: str, terms: Sequence[str]) -> bool:
    return bool(affirmed_term_positions(text, terms))


def matched_terms(text: str, terms: Sequence[str]) -> list[str]:
    normalized = normalize_text(text)
    return [term for term in terms if normalize_text(term) in normalized]


def terms_near(
    text: str,
    left_terms: Sequence[str],
    right_terms: Sequence[str],
    *,
    window: int = 80,
) -> bool:
    left_positions = affirmed_term_positions(text, left_terms)
    right_positions = affirmed_term_positions(text, right_terms)
    return any(abs(left - right) <= window for left in left_positions for right in right_positions)


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
    "输送",
    "传送",
    "阀门",
    "电磁阀",
    "气缸",
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
CUT_OUTPUT_TERMS = (
    "断开输出",
    "切断输出",
    "立即停止",
    "失电",
    "断电",
    "de-energize",
    "disconnect output",
    "stop all",
)
PRIORITY_TERMS = ("最高优先级", "优先于", "急停优先", "highest priority", "overrides")
RESET_TERMS = ("人工复位", "手动复位", "复位后", "reset", "manual reset")
OVERLOAD_TERMS = ("过载", "热继电器", "电机保护器", "overload", "thermal relay")
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
TIMER_TERMS = ("计时", "定时器", "计时器", "timer", "timing")
TIMEOUT_TERMS = ("超时", "到位超时", "动作超时", "timeout")
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
        if contains_any(text, left_terms) and contains_any(text, right_terms)
    ]


def is_monitoring_only(text: str) -> bool:
    return contains_any(text, MONITOR_ONLY_TERMS)
