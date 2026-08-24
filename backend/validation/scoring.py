from collections.abc import Iterable

from .models import RiskLevel, RuleResult, RuleStatus, Severity


SEVERITY_WEIGHTS: dict[Severity, int] = {
    Severity.CRITICAL: 30,
    Severity.HIGH: 15,
    Severity.MEDIUM: 8,
    Severity.LOW: 3,
    Severity.INFO: 0,
}
SCORING_STATUSES = {RuleStatus.WARNING, RuleStatus.FAILED}


def score_rule_results(results: Iterable[RuleResult]) -> int:
    scores_by_rule_id: dict[str, int] = {}
    for result in results:
        if result.status in SCORING_STATUSES:
            weight = SEVERITY_WEIGHTS[result.severity]
            scores_by_rule_id[result.rule_id] = max(scores_by_rule_id.get(result.rule_id, 0), weight)
    return sum(scores_by_rule_id.values())


def risk_level_for_score(score: int) -> RiskLevel:
    if score < 0:
        raise ValueError("Risk score cannot be negative")
    if score < 10:
        return RiskLevel.LOW
    if score < 25:
        return RiskLevel.MEDIUM
    if score < 50:
        return RiskLevel.HIGH
    return RiskLevel.CRITICAL

def risk_level_floor(score: int, results: "Iterable[RuleResult]") -> RiskLevel:  # noqa: F821
    """Ensure risk level is not lower than the highest real severity found."""
    level = risk_level_for_score(score)
    max_severity = Severity.INFO
    for r in results:
        if r.status in SCORING_STATUSES and _severity_order(r.severity) > _severity_order(max_severity):
            max_severity = r.severity
    severity_floor = _severity_to_risk_level(max_severity)
    if _risk_order(severity_floor) > _risk_order(level):
        return severity_floor
    return level


_SEVERITY_ORDER = {Severity.INFO: 0, Severity.LOW: 1, Severity.MEDIUM: 2, Severity.HIGH: 3, Severity.CRITICAL: 4}


def _severity_order(s: Severity) -> int:
    return _SEVERITY_ORDER.get(s, 0)


_RISK_ORDER = {RiskLevel.UNKNOWN: 0, RiskLevel.LOW: 1, RiskLevel.MEDIUM: 2, RiskLevel.HIGH: 3, RiskLevel.CRITICAL: 4}


def _risk_order(r: RiskLevel) -> int:
    return _RISK_ORDER.get(r, 0)


def _severity_to_risk_level(s: Severity) -> RiskLevel:
    if s == Severity.CRITICAL:
        return RiskLevel.CRITICAL
    if s == Severity.HIGH:
        return RiskLevel.HIGH
    if s == Severity.MEDIUM:
        return RiskLevel.MEDIUM
    if s == Severity.LOW:
        return RiskLevel.LOW
    return RiskLevel.UNKNOWN
