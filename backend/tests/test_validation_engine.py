import json
import logging

import pytest

import backend.validation as validation_module
import backend.validation.engine as validation_engine_module
from backend.observability import logger
from backend.validation import (
    RiskLevel,
    RuleEngine,
    RuleStatus,
    Severity,
    ValidationRule,
    ValidationStatus,
    validate_context,
)
from backend.tests.validation_fixtures import validation_context


class FixedRule(ValidationRule):
    def __init__(
        self,
        rule_id: str,
        *,
        status: RuleStatus = RuleStatus.PASSED,
        category: str = "test",
        severity: Severity = Severity.INFO,
    ) -> None:
        self.rule_id = rule_id
        self.name = f"Rule {rule_id}"
        self.category = category
        self.default_severity = severity
        self.status = status

    def validate(self, context):
        if self.status == RuleStatus.NOT_APPLICABLE:
            return self.not_applicable("Not applicable to the fixed test context.")
        return self.result(
            status=self.status,
            message=f"{self.rule_id} completed.",
            evidence=f"source={context.source}",
            recommendation="Use the fixed test recommendation.",
        )


class ExplodingRule(FixedRule):
    def validate(self, context):
        raise RuntimeError("private-stack-path")


def test_rule_registration_succeeds_and_category_query_is_stable() -> None:
    engine = RuleEngine()
    first = FixedRule("FIRST", category="io")
    second = FixedRule("SECOND", category="safety")

    engine.register(first)
    engine.register(second)

    assert engine.rules == (first, second)
    assert engine.get_rules("io") == (first,)
    assert engine.get_rules("missing") == ()


def test_duplicate_rule_id_registration_fails() -> None:
    engine = RuleEngine([FixedRule("DUPLICATE")])

    with pytest.raises(ValueError, match="Duplicate validation rule id"):
        engine.register(FixedRule("DUPLICATE"))


def test_rules_execute_in_registration_order() -> None:
    engine = RuleEngine(
        [
            FixedRule("RULE_C"),
            FixedRule("RULE_A"),
            FixedRule("RULE_B"),
        ]
    )

    report = engine.validate(validation_context())

    assert [result.rule_id for result in report.rule_results] == [
        "RULE_C",
        "RULE_A",
        "RULE_B",
    ]


def test_not_applicable_rule_is_counted_without_risk() -> None:
    engine = RuleEngine(
        [FixedRule("NOT_FOR_CONTEXT", status=RuleStatus.NOT_APPLICABLE, severity=Severity.CRITICAL)]
    )

    report = engine.validate(validation_context())

    assert report.not_applicable_rules == 1
    assert report.warning_rules == 0
    assert report.failed_rules == 0
    assert report.risk_score == 0
    assert report.rule_results[0].status == RuleStatus.NOT_APPLICABLE


def test_single_rule_exception_returns_sanitized_partial_report_and_continues() -> None:
    engine = RuleEngine(
        [
            ExplodingRule("BROKEN", severity=Severity.HIGH),
            FixedRule("AFTER_BROKEN"),
        ]
    )

    report = engine.validate(validation_context())
    serialized = report.model_dump_json()

    assert report.validation_status == ValidationStatus.PARTIAL
    assert [result.rule_id for result in report.rule_results] == ["BROKEN", "AFTER_BROKEN"]
    assert report.rule_results[0].status == RuleStatus.WARNING
    assert report.rule_results[1].status == RuleStatus.PASSED
    assert "private-stack-path" not in serialized
    assert "Traceback" not in serialized


def test_report_summary_counts_and_risk_are_correct() -> None:
    engine = RuleEngine(
        [
            FixedRule("PASS", status=RuleStatus.PASSED, severity=Severity.LOW),
            FixedRule("WARN", status=RuleStatus.WARNING, severity=Severity.CRITICAL),
            FixedRule("FAIL", status=RuleStatus.FAILED, severity=Severity.HIGH),
            FixedRule("NA", status=RuleStatus.NOT_APPLICABLE, severity=Severity.MEDIUM),
        ]
    )

    report = engine.validate(validation_context(request_id="summary-1"))

    assert report.request_id == "summary-1"
    assert report.validation_status == ValidationStatus.COMPLETE
    assert report.total_rules == 4
    assert report.passed_rules == 1
    assert report.warning_rules == 1
    assert report.failed_rules == 1
    assert report.not_applicable_rules == 1
    assert report.critical_count == 1
    assert report.high_count == 1
    assert report.medium_count == 0
    assert report.low_count == 0
    assert report.risk_score == 45
    assert report.risk_level == RiskLevel.CRITICAL
    assert [result.rule_id for result in report.issues] == ["WARN", "FAIL"]


def test_rule_execution_log_has_required_fields_without_plan_text(caplog) -> None:
    caplog.set_level(logging.INFO, logger="industrial_control_agent")
    original_propagate = logger.propagate
    logger.propagate = False
    logger.addHandler(caplog.handler)
    context = validation_context(
        request_id="log-check-1",
        scenario_text="sensitive scenario body",
        plan_text="sensitive full plan body",
    )

    try:
        RuleEngine([FixedRule("LOG_RULE", category="io", severity=Severity.MEDIUM)]).validate(context)
    finally:
        logger.removeHandler(caplog.handler)
        logger.propagate = original_propagate

    payloads = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "industrial_control_agent" and '"rule_id":"LOG_RULE"' in record.message
    ]
    assert len(payloads) == 1
    assert set(payloads[0]) == {
        "request_id",
        "rule_id",
        "category",
        "status",
        "severity",
        "duration_ms",
        "error_type",
    }
    assert payloads[0]["request_id"] == "log-check-1"
    assert payloads[0]["status"] == "passed"
    assert "sensitive scenario body" not in payloads[0].values()
    assert "sensitive full plan body" not in payloads[0].values()


def assert_unavailable_report(report, *, request_id: str) -> None:
    assert report.request_id == request_id
    assert report.validation_status == ValidationStatus.UNAVAILABLE
    assert report.risk_level == RiskLevel.UNKNOWN
    assert report.risk_score == 0
    assert report.total_rules == 0
    assert report.passed_rules == 0
    assert report.warning_rules == 0
    assert report.failed_rules == 0
    assert report.not_applicable_rules == 0
    assert report.critical_count == 0
    assert report.high_count == 0
    assert report.medium_count == 0
    assert report.low_count == 0
    assert report.issues == []
    assert report.rule_results == []


def test_report_build_failure_returns_standalone_unavailable_report(monkeypatch) -> None:
    engine = RuleEngine([FixedRule("REPORT_BUILD")])

    def fail_report_build(*args, **kwargs):
        raise RuntimeError("report-builder-failed")

    monkeypatch.setattr(engine, "_build_report", fail_report_build)

    report = engine.validate(validation_context(request_id="engine-unavailable-1"))

    assert_unavailable_report(report, request_id="engine-unavailable-1")


def test_validation_logging_failure_does_not_change_successful_report(monkeypatch) -> None:
    def fail_logging(**kwargs):
        raise RuntimeError("logging-failed")

    monkeypatch.setattr(validation_engine_module, "log_validation_event", fail_logging)

    report = RuleEngine([FixedRule("LOGGING_FAILURE")]).validate(
        validation_context(request_id="logging-failure-1")
    )

    assert report.validation_status == ValidationStatus.COMPLETE
    assert report.rule_results[0].status == RuleStatus.PASSED


def test_validate_context_setup_and_logging_failures_return_unavailable(monkeypatch) -> None:
    def fail_setup():
        raise RuntimeError("setup-failed")

    def fail_logging(**kwargs):
        raise RuntimeError("logging-failed")

    monkeypatch.setattr(validation_module, "build_default_engine", fail_setup)
    monkeypatch.setattr(validation_engine_module, "log_validation_event", fail_logging)

    report = validate_context(validation_context(request_id="setup-unavailable-1"))

    assert_unavailable_report(report, request_id="setup-unavailable-1")
