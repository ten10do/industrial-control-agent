import pytest

from backend.tests.validation_fixtures import SCENARIOS, ScenarioCase
from backend.validation import build_default_engine


def evaluate_scenarios() -> tuple[dict[str, object], ...]:
    summaries: list[dict[str, object]] = []
    for case in SCENARIOS:
        report = build_default_engine().validate(case.context)
        actual_ids = tuple(result.rule_id for result in report.issues)
        summaries.append(
            {
                "name": case.name,
                "risk_score": report.risk_score,
                "risk_level": report.risk_level.value,
                "issue_ids": actual_ids,
                "matches_expected": (
                    report.risk_score == case.expected_score
                    and report.risk_level == case.expected_level
                    and actual_ids == case.expected_issue_ids
                ),
            }
        )
    return tuple(summaries)


@pytest.mark.parametrize("case", SCENARIOS, ids=lambda case: case.name)
def test_fixed_manual_scenario_is_deterministic_and_matches_expected(
    case: ScenarioCase,
) -> None:
    engine = build_default_engine()

    first = engine.validate(case.context)
    second = engine.validate(case.context)
    actual_ids = tuple(result.rule_id for result in first.issues)

    assert first == second
    assert first.risk_score == case.expected_score
    assert first.risk_level == case.expected_level
    assert actual_ids == case.expected_issue_ids
    assert first.total_rules == 14
    assert first.validation_status.value == "complete"
