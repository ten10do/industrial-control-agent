import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .catalog import canonical_signal_type, normalize_name, normalize_text
from .models import ValidationContext


MOTOR_KINDS = frozenset({"motor", "pump", "fan"})
PUMP_KINDS = frozenset({"pump"})
RUN_STOP_KINDS = frozenset({"motor", "pump", "fan", "conveyor"})
MOTION_KINDS = frozenset(
    {"motor", "pump", "fan", "conveyor", "valve", "cylinder", "lift"}
)
ACTUATOR_KINDS = frozenset(
    {
        "motor",
        "pump",
        "fan",
        "conveyor",
        "valve",
        "cylinder",
        "lift",
        "heater",
        "compressor",
        "actuator",
    }
)
TIMEOUT_KINDS = frozenset({"conveyor", "valve", "cylinder", "lift"})

DEVICE_ALIASES: dict[str, tuple[str, ...]] = {
    "motor": ("电机", "motors", "motor"),
    "pump": ("水泵", "泵", "pumps", "pump"),
    "fan": ("风机", "fans", "fan"),
    "conveyor": ("输送机", "输送带", "传送带", "conveyors", "conveyor"),
    "valve": (
        "电磁阀",
        "阀门",
        "阀",
        "solenoid valves",
        "solenoid valve",
        "valves",
        "valve",
    ),
    "cylinder": ("气缸", "cylinders", "cylinder"),
    "lift": ("升降机", "升降机构", "lifts", "lift"),
    "heater": ("加热器", "heaters", "heater"),
    "compressor": ("压缩机", "compressors", "compressor"),
    "actuator": ("执行器", "actuators", "actuator"),
}

_SENTENCE_SPLIT_RE = re.compile(r"(?:[。！？!?；;\r\n]+|(?<!\d)\.(?!\d))")
_SCOPE_SEPARATOR_RE = re.compile(
    r"(?P<hard>但是|然而|但|\b(?:but|however|while)\b)"
    r"|(?P<soft>[,，]+)",
    re.IGNORECASE,
)
_CHINESE_ORDINAL = r"(?:\d+|[一二三四五六七八九十百]+)\s*号"
_TAG_IDENTIFIER = r"(?:[A-Za-z]*\d[A-Za-z0-9_-]*|[A-Za-z]+[-_]\d[A-Za-z0-9_-]*)"
_PRIMARY_ROLE_IDENTIFIER = (
    r"(?:主|备用|辅|应急|左|右|main|backup|standby|auxiliary)"
)
_FUNCTION_ROLE_IDENTIFIER = r"(?:进水|排水|补水|供水|回水|循环|上料|下料)"
_ROLE_IDENTIFIER = rf"(?:{_PRIMARY_ROLE_IDENTIFIER}|{_FUNCTION_ROLE_IDENTIFIER})"
_COMPOUND_INSTANCE_IDENTIFIER = (
    rf"(?:(?:{_CHINESE_ORDINAL}|{_TAG_IDENTIFIER})"
    rf"(?:\s*{_FUNCTION_ROLE_IDENTIFIER})?"
    rf"|{_PRIMARY_ROLE_IDENTIFIER}(?:\s*{_FUNCTION_ROLE_IDENTIFIER})?)"
)
_INSTANCE_IDENTIFIER = rf"(?:{_CHINESE_ORDINAL}|{_TAG_IDENTIFIER}|{_ROLE_IDENTIFIER})"
_SUFFIX_IDENTIFIER = rf"(?:\d+|{_TAG_IDENTIFIER})"
_INSTANCE_LIST_SEPARATOR = (
    r"(?:、|和|与|及|或|/|[，,](?:\s*(?:and|or))?|\b(?:and|or)\b)"
)
_INSTANCE_IDENTIFIER_LIST = (
    rf"{_INSTANCE_IDENTIFIER}"
    rf"(?:\s*{_INSTANCE_LIST_SEPARATOR}\s*{_INSTANCE_IDENTIFIER})+"
)
_SUFFIX_IDENTIFIER_LIST = (
    rf"{_SUFFIX_IDENTIFIER}"
    rf"(?:\s*{_INSTANCE_LIST_SEPARATOR}\s*{_SUFFIX_IDENTIFIER})+"
)
_INSTANCE_IDENTIFIER_RE = re.compile(_INSTANCE_IDENTIFIER, re.IGNORECASE)
_SUFFIX_IDENTIFIER_RE = re.compile(_SUFFIX_IDENTIFIER, re.IGNORECASE)
_DEVICE_ALIAS_PATTERN = "|".join(
    re.escape(alias)
    for alias in sorted(
        {
            alias
            for aliases in DEVICE_ALIASES.values()
            for alias in aliases
        },
        key=len,
        reverse=True,
    )
)
_ENTITY_ABSENCE_BEFORE_RE = re.compile(
    r"(?:未(?:设置|配置|安装|使用)?|没有|无|不存在|不含|不包含|不使用|无需|"
    r"\b(?:no|without|missing)\b)\s*(?:任何|任一|备用|主|auxiliary|backup|main)?\s*$",
    re.IGNORECASE,
)
_LIST_ENTITY_ABSENCE_BEFORE_RE = re.compile(
    r"\b(?:no|without)\b[^.;。；]{0,64}(?:,|\b(?:or|and)\b)\s*"
    r"(?:(?:electric|auxiliary|backup|main|standby)\s+)?$",
    re.IGNORECASE,
)
_DEVICE_LIST_ITEM = (
    rf"(?:(?:{_INSTANCE_IDENTIFIER})?\s*(?:{_DEVICE_ALIAS_PATTERN}))"
)
_DEVICE_LIST_SEPARATOR = r"(?:、|，|,|/|和|与|及|或)"
_DEVICE_LIST_END = (
    r"(?=\s*(?:$|[。；;]|[，,]\s*(?:仅|只|但|而|同时|并)))"
)
_ABSENT_DEVICE_LIST_RE = re.compile(
    rf"(?:没有|无|不含|不包含)\s*"
    rf"(?P<items>{_DEVICE_LIST_ITEM}"
    rf"(?:\s*{_DEVICE_LIST_SEPARATOR}\s*{_DEVICE_LIST_ITEM})+)"
    rf"{_DEVICE_LIST_END}",
    re.IGNORECASE,
)
_UNCONTROLLED_DEVICE_LIST_RE = re.compile(
    rf"(?:不控制|不驱动|仅监测|只监测)\s*"
    rf"(?P<items>{_DEVICE_LIST_ITEM}"
    rf"(?:\s*{_DEVICE_LIST_SEPARATOR}\s*{_DEVICE_LIST_ITEM})+)"
    rf"{_DEVICE_LIST_END}",
    re.IGNORECASE,
)
_UNCONTROLLED_BEFORE_RE = re.compile(
    r"(?:不控制|不需要控制|无需控制|不驱动|仅监测|只监测|监测|监控|"
    r"(?:监测|监控)对象为|仅采集|只采集|采集|读取|"
    r"\b(?:do(?:es)?\s+not\s+control(?:\s+(?:the|a|an))?|"
    r"not\s+controlled|no\s+control\s+of(?:\s+(?:the|a|an))?|"
    r"monitor(?:ing)?\s+only|only\s+monitor(?:ing)?)\b)\s*$",
    re.IGNORECASE,
)
_ENTITY_ABSENCE_AFTER_RE = re.compile(
    r"^\s*(?:不存在|未安装|未设置|缺失|"
    r"\b(?:does\s+not\s+exist|is\s+absent|is\s+not\s+installed|is\s+missing)\b)",
    re.IGNORECASE,
)
_UNCONTROLLED_AFTER_RE = re.compile(
    r"^\s*(?:不受控制|不参与控制|不需要控制|无需控制|仅用于监测|只用于监测|"
    r"仅监测|只监测|进行监测|用于监测|状态监测|状态采集|"
    r"\b(?:is\s+not\s+controlled|is\s+monitor(?:ed|ing)\s+only|"
    r"monitor(?:ed|ing)?\s+only)\b)",
    re.IGNORECASE,
)
_PARENTHESIZED_UNCONTROLLED_AFTER_RE = re.compile(
    r"[(（]\s*(?:不参与控制|不受控制|不控制|不驱动|无需控制|不需要控制|"
    r"仅监测|只监测|仅用于监测|只用于监测|用于监测|"
    r"进行监测|状态监测|状态采集|"
    r"\b(?:not\s+controlled|monitor(?:ing)?\s+only|only\s+monitor(?:ing)?)"
    r")\s*[)）]",
    re.IGNORECASE,
)

_CAPABILITY_SUFFIX_RE = re.compile(
    r"^(?:的)?(?:"
    r"过载|保护|故障|报警|告警|反馈|急停|互锁|联锁|超时|计时|"
    r"启停|启动|停止|运行|安全|模式|防干转|低液位|到位|控制逻辑|信号|"
    r"overload|protection|fault|alarm|feedback|emergency|interlock|timeout|"
    r"start|stop|run|safe|mode|dry[- ]?run|low level|position"
    r")",
    re.IGNORECASE,
)
_GLOBAL_UNIVERSAL_RE = re.compile(
    r"(?:所有|全部|每个|各个|每台|各台)(?:重要|危险)?(?:输出|设备|执行器)"
    r"|\b(?:all|each|every|both)\s+(?:important\s+|hazardous\s+)?"
    r"(?:outputs?|devices?|actuators?)\b",
    re.IGNORECASE,
)
_SHARED_OWNER_GAP_RE = re.compile(
    r"^\s*(?:(?:(?:、|,|，|和|与|及|或|/|&|\+)|\b(?:and|or)\b)\s*)+$",
    re.IGNORECASE,
)
_TRAILING_OWNER_CONNECTOR_RE = re.compile(
    r"\s*(?:(?:、|,|，|和|与|及|或|而|/|&|\+)|\b(?:and|or)\b)\s*$",
    re.IGNORECASE,
)
_PARALLEL_MARKER_RE = re.compile(r"(?:分别|\brespectively\b)", re.IGNORECASE)
_PARALLEL_PREFIX_RE = re.compile(
    r"^\s*(?P<prefix>(?:均)?(?:配置|设置|安装|采用|使用|具备|提供)"
    r"|\b(?:has|have|uses?|configures?|includes?|provides?)\b)\s*",
    re.IGNORECASE,
)
_PARALLEL_ITEM_SEPARATOR_RE = re.compile(
    r"\s*(?:、|，|,|和|与|及|\band\b)\s*",
    re.IGNORECASE,
)


class DeviceState(str, Enum):
    CONTROLLED = "controlled"
    PRESENT_UNCONTROLLED = "present_uncontrolled"
    ABSENT = "absent"


@dataclass(frozen=True)
class DeviceInstance:
    key: str
    label: str
    kind: str


@dataclass(frozen=True)
class DeviceScope:
    device: DeviceInstance
    scenario_text: str
    plan_text: str


@dataclass(frozen=True)
class _DeviceMention:
    kind: str
    state: DeviceState
    instance_label: str | None = None


def _normalized_raw(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").casefold()


def _device_list_state(
    normalized_text: str,
    start: int,
    end: int,
) -> DeviceState | None:
    for pattern, state in (
        (_ABSENT_DEVICE_LIST_RE, DeviceState.ABSENT),
        (_UNCONTROLLED_DEVICE_LIST_RE, DeviceState.PRESENT_UNCONTROLLED),
    ):
        for match in pattern.finditer(normalized_text):
            if (
                match.start("items") <= start
                and match.end("items") >= end
            ):
                return state
    return None


def _compose_instance_label(
    alias: str,
    identifier: str,
    *,
    alias_first: bool,
) -> str:
    needs_space = bool(
        re.fullmatch(r"[a-z][a-z ]*", alias, re.IGNORECASE)
        and re.fullmatch(r"[a-z0-9#_-]+", identifier, re.IGNORECASE)
    )
    separator = " " if needs_space else ""
    if alias_first:
        return f"{alias}{separator}{identifier}"
    return f"{identifier}{separator}{alias}"


def _instance_patterns(kind: str) -> tuple[re.Pattern[str], ...]:
    aliases = sorted(DEVICE_ALIASES[kind], key=len, reverse=True)
    alias_pattern = "|".join(re.escape(alias) for alias in aliases)
    chinese_aliases = [
        alias
        for alias in aliases
        if re.search(r"[\u3400-\u9fff]", alias)
    ]
    chinese_alias_pattern = "|".join(
        re.escape(alias) for alias in chinese_aliases
    )
    patterns = [
        re.compile(
            rf"(?P<label>{_COMPOUND_INSTANCE_IDENTIFIER}"
            rf"\s*(?:{alias_pattern}))",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?P<label>{_INSTANCE_IDENTIFIER}\s*(?:{alias_pattern}))",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?P<label>(?:{alias_pattern})\s*#?\s*{_SUFFIX_IDENTIFIER})",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?P<label>{_FUNCTION_ROLE_IDENTIFIER}\s*"
            rf"(?:{alias_pattern})\s*#?\s*{_SUFFIX_IDENTIFIER})",
            re.IGNORECASE,
        ),
    ]
    if chinese_alias_pattern:
        patterns.extend(
            (
                re.compile(
                    rf"(?P<label>[A-Za-z]\s*"
                    rf"(?:{_FUNCTION_ROLE_IDENTIFIER})?\s*"
                    rf"(?:{chinese_alias_pattern}))",
                    re.IGNORECASE,
                ),
                re.compile(
                    rf"(?P<label>(?:{chinese_alias_pattern})\s*[A-Za-z])",
                    re.IGNORECASE,
                ),
            )
        )
    if kind == "valve":
        patterns.append(
            re.compile(
                rf"(?P<label>{_INSTANCE_IDENTIFIER}"
                r"\s*[\u3400-\u9fff]{0,4}阀(?:门)?)",
                re.IGNORECASE,
            )
        )
    return tuple(patterns)


_INSTANCE_PATTERNS = {
    kind: _instance_patterns(kind)
    for kind in DEVICE_ALIASES
}


def _mention_state(text: str, start: int, end: int) -> DeviceState:
    normalized = _normalized_raw(text)
    list_state = _device_list_state(normalized, start, end)
    if list_state is not None:
        return list_state
    before = normalized[max(0, start - 48):start]
    after = normalized[end:min(len(normalized), end + 40)].lstrip()
    if _UNCONTROLLED_BEFORE_RE.search(before):
        return DeviceState.PRESENT_UNCONTROLLED
    if _UNCONTROLLED_AFTER_RE.match(after):
        return DeviceState.PRESENT_UNCONTROLLED
    paren_match = _PARENTHESIZED_UNCONTROLLED_AFTER_RE.search(after)
    if paren_match and paren_match.start() < 30:
        gap = after[:paren_match.start()]
        if not re.search(r"\d", gap):
            return DeviceState.PRESENT_UNCONTROLLED
    absence_after = _ENTITY_ABSENCE_AFTER_RE.match(after)
    if absence_after:
        remaining = after[absence_after.end():].lstrip()
        if not _CAPABILITY_SUFFIX_RE.match(remaining):
            return DeviceState.ABSENT
    absent = (
        _ENTITY_ABSENCE_BEFORE_RE.search(before)
        or _LIST_ENTITY_ABSENCE_BEFORE_RE.search(before)
    )
    if absent and not _CAPABILITY_SUFFIX_RE.match(after):
        return DeviceState.ABSENT
    return DeviceState.CONTROLLED


def _explicit_instance_matches(
    text: str,
    kinds: Iterable[str],
) -> list[tuple[int, int, str, str, DeviceState]]:
    normalized = _normalized_raw(text)
    matches: list[tuple[int, int, str, str, DeviceState]] = []
    seen: set[tuple[int, int, str]] = set()
    for kind in kinds:
        shared_state_ranges: list[tuple[int, int, DeviceState]] = []
        aliases = sorted(DEVICE_ALIASES[kind], key=len, reverse=True)
        alias_pattern = "|".join(re.escape(alias) for alias in aliases)
        suffix_shared_pattern = re.compile(
            rf"(?P<identifiers>{_INSTANCE_IDENTIFIER_LIST})"
            rf"\s*(?P<alias>{alias_pattern})",
            re.IGNORECASE,
        )
        prefix_shared_pattern = re.compile(
            rf"(?P<alias>{alias_pattern})\s*"
            rf"(?P<identifiers>{_SUFFIX_IDENTIFIER_LIST})",
            re.IGNORECASE,
        )
        for pattern, alias_first, identifier_pattern in (
            (suffix_shared_pattern, False, _INSTANCE_IDENTIFIER_RE),
            (prefix_shared_pattern, True, _SUFFIX_IDENTIFIER_RE),
        ):
            for match in pattern.finditer(normalized):
                state = _mention_state(text, match.start(), match.end())
                shared_state_ranges.append(
                    (match.start(), match.end(), state)
                )
                alias = unicodedata.normalize(
                    "NFKC",
                    text[match.start("alias"):match.end("alias")],
                ).strip()
                identifier_offset = match.start("identifiers")
                for identifier_match in identifier_pattern.finditer(
                    match.group("identifiers")
                ):
                    identifier_start = (
                        identifier_offset + identifier_match.start()
                    )
                    identifier_end = identifier_offset + identifier_match.end()
                    identifier = unicodedata.normalize(
                        "NFKC",
                        text[identifier_start:identifier_end],
                    ).strip()
                    label = _compose_instance_label(
                        alias,
                        identifier,
                        alias_first=alias_first,
                    )
                    matches.append(
                        (
                            identifier_offset + identifier_match.start(),
                            identifier_offset + identifier_match.end(),
                            label,
                            kind,
                            state,
                        )
                    )
        for pattern in _INSTANCE_PATTERNS[kind]:
            for match in pattern.finditer(normalized):
                start, end = match.span("label")
                identity = (start, end, kind)
                if identity in seen:
                    continue
                seen.add(identity)
                label = unicodedata.normalize("NFKC", text[start:end]).strip()
                shared_state = next(
                    (
                        state
                        for range_start, range_end, state in shared_state_ranges
                        if range_start <= start and range_end >= end
                    ),
                    None,
                )
                matches.append(
                    (
                        start,
                        end,
                        label,
                        kind,
                        shared_state
                        if shared_state is not None
                        else _mention_state(text, start, end),
                    )
                )
    longest_first = sorted(
        matches,
        key=lambda item: (-(item[1] - item[0]), item[0]),
    )
    non_overlapping: list[tuple[int, int, str, str, DeviceState]] = []
    for candidate in longest_first:
        if any(
            existing[3] == candidate[3]
            and existing[0] <= candidate[0]
            and existing[1] >= candidate[1]
            for existing in non_overlapping
        ):
            continue
        non_overlapping.append(candidate)
    return sorted(
        non_overlapping,
        key=lambda item: (item[0], -(item[1] - item[0])),
    )


def _alias_matches(text: str, alias: str) -> Iterable[re.Match[str]]:
    normalized = _normalized_raw(text)
    escaped = re.escape(_normalized_raw(alias))
    if re.fullmatch(r"[a-z0-9][a-z0-9 -]*", _normalized_raw(alias)):
        pattern = re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])")
    else:
        pattern = re.compile(escaped)
    return pattern.finditer(normalized)


def _mentions(text: str, kind: str) -> list[_DeviceMention]:
    explicit_matches = _explicit_instance_matches(text, (kind,))
    candidates: list[tuple[int, int, _DeviceMention]] = []
    for alias in sorted(DEVICE_ALIASES[kind], key=len, reverse=True):
        for match in _alias_matches(text, alias):
            span = match.span()
            owner = next(
                (
                    explicit
                    for explicit in explicit_matches
                    if explicit[0] <= span[0] and explicit[1] >= span[1]
                ),
                None,
            )
            candidates.append(
                (
                    span[0],
                    span[1],
                    _DeviceMention(
                        kind=kind,
                        state=owner[4] if owner else _mention_state(text, *span),
                        instance_label=owner[2] if owner else None,
                    ),
                )
            )
    selected: list[tuple[int, int, _DeviceMention]] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (-(item[1] - item[0]), item[0]),
    ):
        if any(
            existing[0] <= candidate[0]
            and existing[1] >= candidate[1]
            for existing in selected
        ):
            continue
        selected.append(candidate)
    return [
        mention
        for _, _, mention in sorted(selected, key=lambda item: item[0])
    ]


def _strong_output_texts(context: ValidationContext) -> tuple[str, ...]:
    texts = [context.output_devices]
    for point in context.io_points:
        if canonical_signal_type(point.signal_type) not in {"DO", "AO"}:
            continue
        texts.extend(
            part
            for part in (
                point.device,
                point.signal_name,
                point.description,
            )
            if part
        )
    return tuple(text for text in texts if text)


def _scenario_texts(context: ValidationContext) -> tuple[str, ...]:
    if context.source == "optimize":
        return tuple(
            text
            for text in (context.scenario_text,)
            if text
        )
    has_structured_request_fields = any(
        (
            context.control_object,
            context.input_devices,
            context.output_devices,
            context.control_requirements,
        )
    )
    if has_structured_request_fields:
        semantic_text = " ".join(
            text
            for text in (
                context.control_object,
                context.control_requirements,
            )
            if text
        )
        return (semantic_text,) if semantic_text else ()
    return tuple(
        text
        for text in (context.scenario_text,)
        if text
    )


def has_controlled_device(
    context: ValidationContext,
    kinds: Iterable[str],
) -> bool:
    for kind in kinds:
        scenario_mentions = [
            mention
            for text in _scenario_texts(context)
            for mention in _mentions(text, kind)
        ]
        generic_exclusion = any(
            mention.instance_label is None
            and mention.state
            in {DeviceState.ABSENT, DeviceState.PRESENT_UNCONTROLLED}
            for mention in scenario_mentions
        )
        if generic_exclusion:
            continue
        strong_positive = any(
            mention.state == DeviceState.CONTROLLED
            for text in _strong_output_texts(context)
            for mention in _mentions(text, kind)
        )
        scenario_positive = any(
            mention.state == DeviceState.CONTROLLED
            for mention in scenario_mentions
        )
        if strong_positive or scenario_positive:
            return True
    return False


def controlled_device_instances(
    context: ValidationContext,
    kinds: Iterable[str],
) -> tuple[DeviceInstance, ...]:
    requested_kinds = tuple(kinds)
    source_texts = _scenario_texts(context) + _strong_output_texts(context) + ((context.scenario_text,) if context.scenario_text else ())
    states_by_key: dict[str, list[DeviceState]] = {}
    instances_by_key: dict[str, DeviceInstance] = {}
    order: list[str] = []
    for text in source_texts:
        for _, _, label, kind, state in _explicit_instance_matches(
            text,
            requested_kinds,
        ):
            key = _instance_key(label, kind)
            if key not in instances_by_key:
                instances_by_key[key] = DeviceInstance(
                    key=key,
                    label=label,
                    kind=kind,
                )
                states_by_key[key] = []
                order.append(key)
            states_by_key[key].append(state)

    controlled: list[DeviceInstance] = []
    for key in order:
        instance = instances_by_key[key]
        states = states_by_key[key]
        if not has_controlled_device(context, (instance.kind,)):
            continue
        if any(
            state in {DeviceState.ABSENT, DeviceState.PRESENT_UNCONTROLLED}
            for state in states
        ):
            continue
        if DeviceState.CONTROLLED in states:
            controlled.append(instance)
    return tuple(controlled)


_CHINESE_DIGIT_MAP = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
    "零": 0,
}


def _chinese_numeral_value(text: str) -> int:
    """Convert a Chinese numeral string to an integer (e.g. ‘十二’ → 12, ‘一百二十’ → 120)."""
    if not text:
        return 0
    result = 0
    current = 0
    for ch in text:
        if ch in _CHINESE_DIGIT_MAP:
            current = _CHINESE_DIGIT_MAP[ch]
        elif ch == "十":
            current = (current or 1) * 10
            result += current
            current = 0
        elif ch == "百":
            current = (current or 1) * 100
            result += current
            current = 0
    return result + current

def _instance_key(label: str, kind: str) -> str:
    compact = normalize_name(label)
    for alias in sorted(DEVICE_ALIASES[kind], key=len, reverse=True):
        normalized_alias = normalize_name(alias)
        if normalized_alias and normalized_alias in compact:
            compact = compact.replace(normalized_alias, "", 1)
            break
    compact = compact.lstrip("#")
    compact = re.sub(
        r"([一二三四五六七八九十百]+)号",
        lambda match: str(_chinese_numeral_value(match.group(1))),
        compact,
    )
    compact = re.sub(r"(\d+)号", r"\1", compact)
    role_suffix = re.fullmatch(
        r"(?P<identifier>(?:[a-z]*\d[a-z0-9]*|\d+))"
        r"(?P<role>进水|排水|补水|供水|回水|循环|上料|下料)",
        compact,
    )
    if role_suffix:
        compact = (
            f"{role_suffix.group('role')}"
            f"{role_suffix.group('identifier')}"
        )
    return f"{kind}:{compact or normalize_name(label)}"


def _universal_kinds(clause: str, kinds: Iterable[str]) -> set[str]:
    normalized = normalize_text(clause)
    compact = normalized.replace(" ", "")
    matched: set[str] = set()
    for kind in kinds:
        for alias in DEVICE_ALIASES[kind]:
            alias_normalized = normalize_text(alias)
            alias_compact = alias_normalized.replace(" ", "")
            if any(
                marker + alias_compact in compact
                for marker in ("所有", "全部", "每台", "每个", "各台", "各个")
            ):
                matched.add(kind)
                break
            if re.search(
                rf"\b(?:all|each|every|both)\s+"
                rf"(?:{re.escape(alias_normalized)}s?)\b",
                normalized,
            ):
                matched.add(kind)
                break
    return matched


def _owner_groups(
    clause: str,
    owner_matches: list[tuple[int, int, str]],
) -> list[list[tuple[int, int, str]]]:
    if not owner_matches:
        return []
    groups = [[owner_matches[0]]]
    for owner_match in owner_matches[1:]:
        previous = groups[-1][-1]
        gap = clause[previous[1]:owner_match[0]]
        if _SHARED_OWNER_GAP_RE.fullmatch(gap):
            groups[-1].append(owner_match)
        else:
            groups.append([owner_match])
    return groups


def _parallel_group_assignments(
    segment: str,
    owner_group: list[tuple[int, int, str]],
) -> dict[str, str] | None:
    marker = _PARALLEL_MARKER_RE.search(segment)
    if marker is None:
        return None
    remainder = segment[marker.end():].strip()
    prefix_match = _PARALLEL_PREFIX_RE.match(remainder)
    if prefix_match is None:
        return {}
    prefix = prefix_match.group("prefix").strip()
    item_text = remainder[prefix_match.end():].strip()
    items = [
        item.strip()
        for item in _PARALLEL_ITEM_SEPARATOR_RE.split(item_text)
        if item.strip()
    ]
    if len(items) != len(owner_group):
        return {}
    return {
        owner[2]: f"{prefix} {item}".strip()
        for owner, item in zip(owner_group, items, strict=True)
    }


def _scoped_texts(
    text: str,
    instances: tuple[DeviceInstance, ...],
    *,
    allow_unique_owner_fallback: bool = False,
) -> dict[str, str]:
    instance_keys = {instance.key for instance in instances}
    instance_kinds = {instance.kind for instance in instances}
    unique_owner_key = (
        instances[0].key
        if allow_unique_owner_fallback and len(instances) == 1
        else None
    )
    if unique_owner_key is not None:
        text_owner_keys = {
            _instance_key(label, kind)
            for _, _, label, kind, _ in _explicit_instance_matches(
                text,
                DEVICE_ALIASES,
            )
        }
        if any(key != unique_owner_key for key in text_owner_keys):
            unique_owner_key = None
    sentences_by_key: dict[str, list[str]] = {
        instance.key: []
        for instance in instances
    }
    for sentence in _SENTENCE_SPLIT_RE.split(text or ""):
        if not sentence.strip():
            continue
        current_owner_keys: tuple[str, ...] = (
            (unique_owner_key,)
            if unique_owner_key is not None
            else ()
        )
        clauses_by_key: dict[str, list[str]] = {
            instance.key: []
            for instance in instances
        }
        start = 0
        preceding_hard_boundary = False
        scoped_units: list[tuple[str, bool]] = []
        for separator in _SCOPE_SEPARATOR_RE.finditer(sentence):
            clause = sentence[start:separator.start()]
            if clause.strip():
                scoped_units.append((clause, preceding_hard_boundary))
            preceding_hard_boundary = separator.lastgroup == "hard"
            start = separator.end()
        clause = sentence[start:]
        if clause.strip():
            scoped_units.append((clause, preceding_hard_boundary))

        for clause, hard_boundary in scoped_units:
            if not clause.strip():
                continue
            if hard_boundary:
                current_owner_keys = (
                    (unique_owner_key,)
                    if unique_owner_key is not None
                    else ()
                )
            normalized_clause = _normalized_raw(clause)
            explicit_matches = _explicit_instance_matches(
                clause,
                DEVICE_ALIASES,
            )
            owner_matches: list[tuple[int, int, str]] = []
            seen_owner_matches: set[tuple[int, int, str]] = set()
            for match_start, match_end, label, kind, _ in explicit_matches:
                key = _instance_key(label, kind)
                identity = (match_start, match_end, key)
                if identity in seen_owner_matches:
                    continue
                seen_owner_matches.add(identity)
                owner_matches.append((match_start, match_end, key))
            explicit_owner_keys = tuple(
                key
                for key in dict.fromkeys(
                    key
                    for _, _, key in owner_matches
                )
                if key in instance_keys
            )
            universal_kinds = _universal_kinds(
                clause,
                instance_kinds,
            )
            if _GLOBAL_UNIVERSAL_RE.search(normalized_clause):
                universal_owner_keys = tuple(instance.key for instance in instances)
            else:
                universal_owner_keys = tuple(
                    instance.key
                    for instance in instances
                    if instance.kind in universal_kinds
                )
            if owner_matches:
                owner_groups = _owner_groups(clause, owner_matches)
                current_owner_keys = tuple(
                    owner_key
                    for owner_key in dict.fromkeys(
                        owner[2] for owner in owner_groups[-1]
                    )
                    if owner_key in instance_keys
                )
                for index, owner_group in enumerate(owner_groups):
                    segment_start = (
                        0 if index == 0 else owner_group[0][0]
                    )
                    segment_end = (
                        owner_groups[index + 1][0][0]
                        if index + 1 < len(owner_groups)
                        else len(clause)
                    )
                    segment = _TRAILING_OWNER_CONNECTOR_RE.sub(
                        "",
                        clause[segment_start:segment_end],
                    ).strip()
                    if not segment:
                        continue
                    parallel_assignments = _parallel_group_assignments(
                        segment,
                        owner_group,
                    )
                    for _, _, owner_key in owner_group:
                        if owner_key not in instance_keys:
                            continue
                        if parallel_assignments is None:
                            assigned_segment = segment
                        else:
                            assigned_segment = parallel_assignments.get(
                                owner_key,
                                "",
                            )
                        if assigned_segment:
                            clauses_by_key[owner_key].append(assigned_segment)
                continue
            if universal_owner_keys:
                current_owner_keys = universal_owner_keys
            for key in current_owner_keys:
                clauses_by_key[key].append(clause.strip())
        for key, clauses in clauses_by_key.items():
            if clauses:
                sentences_by_key[key].append("，".join(clauses))
    return {
        key: "。".join(sentences)
        for key, sentences in sentences_by_key.items()
    }


def multi_device_scopes(
    context: ValidationContext,
    kinds: Iterable[str],
) -> tuple[DeviceScope, ...]:
    requested_kinds = tuple(kinds)
    source_texts = _scenario_texts(context) + _strong_output_texts(context)
    discovered_keys = {
        _instance_key(label, kind)
        for text in source_texts
        for _, _, label, kind, _ in _explicit_instance_matches(
            text,
            requested_kinds,
        )
    }
    instances = controlled_device_instances(context, requested_kinds)
    if not instances or not discovered_keys:
        return ()
    allow_unique_owner_fallback = len(discovered_keys) == 1
    scoped_scenarios = _scoped_texts(
        context.scenario_text,
        instances,
        allow_unique_owner_fallback=allow_unique_owner_fallback,
    )
    scoped_plans = _scoped_texts(
        context.plan_text,
        instances,
        allow_unique_owner_fallback=allow_unique_owner_fallback,
    )
    return tuple(
        DeviceScope(
            device=instance,
            scenario_text=scoped_scenarios.get(instance.key, ""),
            plan_text=scoped_plans.get(instance.key, ""),
        )
        for instance in instances
    )
