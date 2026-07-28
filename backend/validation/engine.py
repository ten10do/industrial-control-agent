import time
from collections.abc import Iterable

try:
    from ..observability import log_validation_event
except ImportError:
    from observability import log_validation_event

from .base import ValidationRule
from .models import (
    RiskLevel,
    RuleResult,
    RuleStatus,
    Severity,
    ValidationContext,
    ValidationReport,
    ValidationStatus,
)
from .scoring import SCORING_STATUSES, risk_level_floor, risk_level_for_score, score_rule_results


def _log_validation_event_safely(**event) -> None:
    try:
        log_validation_event(**event)
    except Exception:
        pass


def _unavailable_report(context: ValidationContext) -> ValidationReport:
    return ValidationReport(
        request_id=context.request_id,
        validation_status=ValidationStatus.UNAVAILABLE,
        risk_level=RiskLevel.UNKNOWN,
        risk_score=0,
        total_rules=0,
        passed_rules=0,
        warning_rules=0,
        failed_rules=0,
        not_applicable_rules=0,
        error_rules=0,
        applicable_rules=0,
        coverage_ratio=0.0,
        critical_count=0,
        high_count=0,
        medium_count=0,
        low_count=0,
        issues=[],
        rule_results=[],
    )


class RuleEngine:
    def __init__(self, rules: Iterable[ValidationRule] = ()) -> None:
        self._rules: list[ValidationRule] = []
        self._rule_ids: set[str] = set()
        for rule in rules:
            self.register(rule)

    @property
    def rules(self) -> tuple[ValidationRule, ...]:
        return tuple(self._rules)

    def register(self, rule: ValidationRule) -> None:
        if rule.rule_id in self._rule_ids:
            raise ValueError(f"Duplicate validation rule id: {rule.rule_id}")
        self._rule_ids.add(rule.rule_id)
        self._rules.append(rule)

    def get_rules(self, category: str | None = None) -> tuple[ValidationRule, ...]:
        if category is None:
            return self.rules
        return tuple(rule for rule in self._rules if rule.category == category)

    def validate(self, context: ValidationContext) -> ValidationReport:
        try:
            return self._validate(context)
        except Exception as exc:
            _log_validation_event_safely(
                request_id=context.request_id,
                rule_id="VALIDATION_ENGINE",
                category="engine",
                status="error",
                severity=Severity.CRITICAL.value,
                error_type=type(exc).__name__,
            )
            return self._unavailable_report(context)

    def _validate(self, context: ValidationContext) -> ValidationReport:
        results: list[RuleResult] = []
        has_rule_error = False
        for rule in self._rules:
            started_at = time.perf_counter()
            error_type: str | None = None
            try:
                result = rule.validate(context)
                if result.rule_id != rule.rule_id:
                    raise ValueError("Rule returned a mismatched rule id")
            except Exception as exc:
                has_rule_error = True
                error_type = type(exc).__name__
                result = self._rule_error_result(rule)
            duration_ms = (time.perf_counter() - started_at) * 1000
            _log_validation_event_safely(
                request_id=context.request_id,
                rule_id=rule.rule_id,
                category=rule.category,
                status="error" if error_type else result.status.value,
                severity=result.severity.value,
                duration_ms=duration_ms,
                error_type=error_type,
            )
            results.append(result)

        status = ValidationStatus.PARTIAL if has_rule_error else ValidationStatus.COMPLETE
        return self._build_report(context, results, status)

    @staticmethod
    def _rule_error_result(rule: ValidationRule) -> RuleResult:
        return rule.result(
            status=RuleStatus.WARNING,
            message="该规则本次未能完成校验。",
            evidence="规则执行异常，详细内部信息已隐藏。",
            recommendation="请人工复核此项控制设计后再投入工程使用。",
        )

    def _unavailable_report(self, context: ValidationContext) -> ValidationReport:
        return _unavailable_report(context)

    @staticmethod
    @staticmethod

    def _build_report(

        context: ValidationContext,

        results: list[RuleResult],

        validation_status: ValidationStatus,

    ) -> ValidationReport:

        risk_score = score_rule_results(results)

        issues = [result for result in results if result.status in SCORING_STATUSES]



        def count_status(status: RuleStatus) -> int:

            return sum(result.status == status for result in results)



        def count_severity(severity: Severity) -> int:

            return sum(result.severity == severity for result in issues)



        applicable_rules = sum(

            1 for r in results if r.status != RuleStatus.NOT_APPLICABLE

        )

        coverage_ratio = applicable_rules / len(results) if results else 0.0

        error_rules = count_status(RuleStatus.ERROR)



        if applicable_rules == 0 and not error_rules:

            validation_status = ValidationStatus.INSUFFICIENT_DATA

            risk_level = RiskLevel.UNKNOWN

        else:

            risk_level = risk_level_floor(risk_score, issues)



        return ValidationReport(

            request_id=context.request_id,

            validation_status=validation_status,

            risk_level=risk_level,

            risk_score=risk_score,

            total_rules=len(results),

            passed_rules=count_status(RuleStatus.PASSED),

            warning_rules=count_status(RuleStatus.WARNING),

            failed_rules=count_status(RuleStatus.FAILED),

            not_applicable_rules=count_status(RuleStatus.NOT_APPLICABLE),

            error_rules=error_rules,

            applicable_rules=applicable_rules,

            coverage_ratio=coverage_ratio,

            critical_count=count_severity(Severity.CRITICAL),

            high_count=count_severity(Severity.HIGH),

            medium_count=count_severity(Severity.MEDIUM),

            low_count=count_severity(Severity.LOW),

            issues=issues,

            rule_results=results,

        )

