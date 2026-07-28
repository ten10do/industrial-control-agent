from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RuleStatus(str, Enum):
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"
    ERROR = "error"


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskLevel(str, Enum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ValidationStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    INSUFFICIENT_DATA = "insufficient_data"


class ValidationIOPoint(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, frozen=True)

    address: str = ""
    signal_name: str = ""
    signal_type: str = ""
    device: str = ""
    description: str = ""


class ValidationContext(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, frozen=True)

    source: Literal["generate", "optimize", "validate"]
    request_id: str | None = None
    scenario_text: str = ""
    plan_text: str = ""
    io_points: tuple[ValidationIOPoint, ...] = ()
    structured_io_available: bool = False
    control_object: str = ""
    input_devices: str = ""
    output_devices: str = ""
    control_requirements: str = ""
    requirement_analysis: str = ""
    control_logic: str = ""
    safety_design: str = ""
    ladder_idea: str = ""
    report_text: str = ""
    change_summary: str = ""


class RuleResult(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, frozen=True)

    rule_id: str
    rule_name: str
    category: str
    severity: Severity
    status: RuleStatus
    message: str
    evidence: str = ""
    recommendation: str
    related_items: list[str] = Field(default_factory=list)


class ValidationReport(BaseModel):
    request_id: str | None = None
    validation_status: ValidationStatus
    risk_level: RiskLevel
    risk_score: int = Field(ge=0)
    total_rules: int = Field(ge=0)
    passed_rules: int = Field(ge=0)
    warning_rules: int = Field(ge=0)
    failed_rules: int = Field(ge=0)
    not_applicable_rules: int = Field(ge=0)
    error_rules: int = Field(ge=0, default=0)
    applicable_rules: int = Field(ge=0, default=0)
    coverage_ratio: float = Field(ge=0.0, le=1.0, default=0.0)
    critical_count: int = Field(ge=0)
    high_count: int = Field(ge=0)
    medium_count: int = Field(ge=0)
    low_count: int = Field(ge=0)
    issues: list[RuleResult] = Field(default_factory=list)
    rule_results: list[RuleResult] = Field(default_factory=list)
