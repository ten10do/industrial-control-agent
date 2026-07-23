from .base import ValidationRule
from .engine import RuleEngine, _log_validation_event_safely, _unavailable_report
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


def build_default_engine() -> RuleEngine:
    return RuleEngine(build_default_rules())


def validate_context(
    context: ValidationContext,
    engine: RuleEngine | None = None,
) -> ValidationReport:
    try:
        return (engine or build_default_engine()).validate(context)
    except Exception as exc:
        _log_validation_event_safely(
            request_id=context.request_id,
            rule_id="VALIDATION_SETUP",
            category="engine",
            status="error",
            severity=Severity.CRITICAL.value,
            error_type=type(exc).__name__,
        )
        return _unavailable_report(context)


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
