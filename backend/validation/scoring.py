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
