from abc import ABC, abstractmethod
from collections.abc import Sequence

from .models import RuleResult, RuleStatus, Severity, ValidationContext


class ValidationRule(ABC):
    rule_id: str
    name: str
    category: str
    default_severity: Severity

    @abstractmethod
    def validate(self, context: ValidationContext) -> RuleResult:
        """Evaluate one deterministic rule."""

    def result(
        self,
        *,
        status: RuleStatus,
        message: str,
        evidence: str | Sequence[str] = "",
        recommendation: str,
        related_items: Sequence[str] = (),
        severity: Severity | None = None,
    ) -> RuleResult:
        evidence_text = evidence if isinstance(evidence, str) else "；".join(evidence)
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            category=self.category,
            severity=severity or self.default_severity,
            status=status,
            message=message,
            evidence=evidence_text,
            recommendation=recommendation,
            related_items=list(related_items),
        )

    def passed(self, message: str, evidence: str | Sequence[str] = "") -> RuleResult:
        return self.result(
            status=RuleStatus.PASSED,
            message=message,
            evidence=evidence,
            recommendation="无需修改。",
        )

    def not_applicable(self, message: str) -> RuleResult:
        return self.result(
            status=RuleStatus.NOT_APPLICABLE,
            message=message,
            recommendation="当前场景无需应用此规则。",
        )
