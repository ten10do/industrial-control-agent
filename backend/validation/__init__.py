from .base import ValidationRule
from .engine import RuleEngine
from .models import (
    RiskLevel,
    RuleResult,
    RuleStatus,
    Severity,
    ValidationContext,
    ValidationIOPoint,
    ValidationReport,
    ValidationStatus,
)
from .rules import build_default_rules
from .scoring import SEVERITY_WEIGHTS, risk_level_for_score, score_rule_results

try:
    from ..observability import log_validation_event
except ImportError:
    from observability import log_validation_event


def build_default_engine() -> RuleEngine:
    return RuleEngine(build_default_rules())


def validate_context(
    context: ValidationContext,
    engine: RuleEngine | None = None,
) -> ValidationReport:
    try:
        return (engine or build_default_engine()).validate(context)
    except Exception as exc:
        log_validation_event(
            request_id=context.request_id,
            rule_id="VALIDATION_SETUP",
            category="engine",
            status="error",
            severity=Severity.CRITICAL.value,
            error_type=type(exc).__name__,
        )
        return ValidationReport(
            request_id=context.request_id,
            validation_status=ValidationStatus.UNAVAILABLE,
            risk_level=RiskLevel.LOW,
            risk_score=0,
            total_rules=0,
            passed_rules=0,
            warning_rules=0,
            failed_rules=0,
            not_applicable_rules=0,
            critical_count=0,
            high_count=0,
            medium_count=0,
            low_count=0,
            issues=[],
            rule_results=[],
        )


__all__ = [
    "RiskLevel",
    "RuleEngine",
    "RuleResult",
    "RuleStatus",
    "SEVERITY_WEIGHTS",
    "Severity",
    "ValidationContext",
    "ValidationIOPoint",
    "ValidationReport",
    "ValidationRule",
    "ValidationStatus",
    "build_default_engine",
    "risk_level_for_score",
    "score_rule_results",
    "validate_context",
]
