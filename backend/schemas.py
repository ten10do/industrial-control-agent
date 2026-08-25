from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

if __package__:
    from .validation.models import ValidationReport
else:
    from validation.models import ValidationReport


class RequestModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class GenerateRequest(RequestModel):
    control_object: str = Field(min_length=1, max_length=4000)
    input_devices: str = Field(min_length=1, max_length=6000)
    output_devices: str = Field(min_length=1, max_length=6000)
    control_requirements: str = Field(min_length=1, max_length=10000)
    model_provider: Literal["Ox Alpha"] = "Ox Alpha"


class IOPoint(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    address: str = Field(default="", max_length=100)
    signal_name: str = Field(default="", max_length=200)
    signal_type: str = Field(default="", max_length=100)
    device: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=1000)


class SafetyGate(BaseModel):
    status: Literal["advisory", "review_required"]
    review_required: bool
    export_allowed: bool
    reasons: list[str] = Field(default_factory=list, max_length=10)


class GenerateResponse(BaseModel):
    requirement_analysis: str = Field(min_length=1, max_length=20000)
    io_table: list[IOPoint] = Field(max_length=256)
    control_logic: str = Field(min_length=1, max_length=40000)
    safety_design: str = Field(min_length=1, max_length=40000)
    ladder_idea: str = Field(min_length=1, max_length=40000)
    report_markdown: str = Field(min_length=1, max_length=100000)
    safety_notice: str = Field(min_length=1, max_length=1000)
    validation_report: Optional[ValidationReport] = None
    safety_gate: Optional[SafetyGate] = None
    plan_id: Optional[str] = None
    parent_plan_id: Optional[str] = None
    content_hash: Optional[str] = None
    created_at: Optional[str] = None


class OptimizeRequest(RequestModel):
    original_report: str = Field(min_length=1, max_length=50000)
    optimize_requirement: str = Field(min_length=1, max_length=10000)
    model_provider: Literal["Ox Alpha"] = "Ox Alpha"
    plan_id: Optional[str] = Field(default=None, min_length=1, max_length=100)


class OptimizeResponse(BaseModel):
    optimized_report: str = Field(min_length=1, max_length=120000)
    change_summary: str = Field(min_length=1, max_length=20000)
    safety_notice: str = Field(min_length=1, max_length=1000)
    validation_report: Optional[ValidationReport] = None
    safety_gate: Optional[SafetyGate] = None
    plan_id: Optional[str] = None
    parent_plan_id: Optional[str] = None
    content_hash: Optional[str] = None
    created_at: Optional[str] = None


class LatestReviewResponse(BaseModel):
    review_id: str
    decision: Literal["approved", "rejected"]
    reviewer_sub: Optional[str] = None
    reviewer: str
    comment: str
    reviewed_at: str


class PlanResponse(BaseModel):
    plan_id: str
    parent_plan_id: Optional[str] = None
    source: str
    content_hash: str
    report_markdown: str
    response: dict
    review_required: bool
    export_allowed: bool
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None
    latest_review: Optional[LatestReviewResponse] = None
    created_at: str


class PlanSummaryResponse(BaseModel):
    plan_id: str
    parent_plan_id: Optional[str] = None
    source: str
    content_hash: str
    review_required: bool
    export_allowed: bool
    created_by: Optional[str] = None
    created_by_name: Optional[str] = None
    latest_decision: Optional[Literal["approved", "rejected"]] = None
    created_at: str


class PlanListResponse(BaseModel):
    plans: list[PlanSummaryResponse]


class ReviewRequest(RequestModel):
    decision: Literal["approved", "rejected"]
    comment: str = Field(default="", max_length=2000)


class ReviewResponse(BaseModel):
    review_id: str
    plan_id: str
    decision: Literal["approved", "rejected"]
    reviewer_sub: Optional[str] = None
    reviewer: str
    comment: str
    content_hash: str
    reviewed_at: str
    export_allowed: bool


class CurrentUserResponse(BaseModel):
    subject: str
    display_name: str
    roles: list[Literal["designer", "reviewer", "admin"]]


class AuditEventResponse(BaseModel):
    event_id: str
    actor_sub: str
    actor_name: str
    action: str
    resource_type: str
    resource_id: str
    plan_hash: Optional[str] = None
    request_id: Optional[str] = None
    details: dict
    previous_hash: str
    event_hash: str
    signature_algorithm: Literal["sha256", "hmac-sha256"]
    signing_key_id: Optional[str] = None
    created_at: str


class AuditLogResponse(BaseModel):
    chain_valid: bool
    events: list[AuditEventResponse]


class ModelJobResponse(BaseModel):
    job_id: str
    operation: Literal["generate", "optimize"]
    status: Literal[
        "queued",
        "running",
        "cancel_requested",
        "cancelled",
        "succeeded",
        "failed",
    ]
    progress: int = Field(ge=0, le=100)
    attempts: int = Field(ge=0)
    max_attempts: int = Field(gt=0)
    result: Optional[dict] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    plan_id: Optional[str] = None
    parent_plan_id: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    updated_at: str


class ModelJobListResponse(BaseModel):
    jobs: list[ModelJobResponse]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, Literal["ok", "error"]]


class ErrorResponse(BaseModel):
    code: str = "APPLICATION_ERROR"
    message: str
    detail: Optional[str] = None
    request_id: Optional[str] = None

class ValidateRequest(RequestModel):
    plan_text: str = Field(min_length=1, max_length=100000)
    control_object: str = Field(default="", max_length=4000)
    input_devices: str = Field(default="", max_length=6000)
    output_devices: str = Field(default="", max_length=6000)
    control_requirements: str = Field(default="", max_length=10000)
    scenario_text: str = Field(default="", max_length=20000)


class ValidateResponse(BaseModel):
    validation_report: ValidationReport
