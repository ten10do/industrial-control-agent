import pytest

from backend.validation import (
    RiskLevel,
    RuleResult,
    RuleStatus,
    Severity,
    risk_level_for_score,
    score_rule_results,
)


def result(
    rule_id: str,
    severity: Severity,
    status: RuleStatus = RuleStatus.FAILED,
) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        rule_name=rule_id,
        category="test",
        severity=severity,
        status=status,
        message="Fixed scoring result.",
        evidence="Fixed evidence.",
        recommendation="Fixed recommendation.",
    )


@pytest.mark.parametrize(
    ("severity", "expected_score"),
    [
        (Severity.CRITICAL, 30),
        (Severity.HIGH, 15),
        (Severity.MEDIUM, 8),
        (Severity.LOW, 3),
        (Severity.INFO, 0),
    ],
)
def test_severity_weights_are_deterministic(
    severity: Severity,
    expected_score: int,
) -> None:
    assert score_rule_results([result("WEIGHT", severity)]) == expected_score


def test_passed_result_does_not_score() -> None:
    assert score_rule_results(
        [result("PASSED", Severity.CRITICAL, RuleStatus.PASSED)]
    ) == 0


def test_not_applicable_result_does_not_score() -> None:
    assert score_rule_results(
        [result("NA", Severity.CRITICAL, RuleStatus.NOT_APPLICABLE)]
    ) == 0


def test_duplicate_rule_id_is_scored_once_using_highest_weight() -> None:
    results = [
        result("DUPLICATE", Severity.LOW, RuleStatus.WARNING),
        result("DUPLICATE", Severity.CRITICAL, RuleStatus.FAILED),
        result("DUPLICATE", Severity.HIGH, RuleStatus.FAILED),
    ]

    assert score_rule_results(results) == 30


@pytest.mark.parametrize(
    ("score", "expected_level"),
    [
        (0, RiskLevel.LOW),
        (9, RiskLevel.LOW),
        (10, RiskLevel.MEDIUM),
        (24, RiskLevel.MEDIUM),
        (25, RiskLevel.HIGH),
        (49, RiskLevel.HIGH),
        (50, RiskLevel.CRITICAL),
    ],
)
def test_risk_level_boundaries(score: int, expected_level: RiskLevel) -> None:
    assert risk_level_for_score(score) == expected_level


def test_negative_risk_score_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        risk_level_for_score(-1)
