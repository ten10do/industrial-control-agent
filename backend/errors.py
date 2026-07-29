class AppError(RuntimeError):
    """Base sanitized application error safe for API responses."""

    code = "APPLICATION_ERROR"
    message = "Request failed"
    status_code = 502

    def __init__(
        self,
        message: str | None = None,
        *,
        detail: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.detail = detail
        self.headers = headers or {}
        super().__init__(message or self.message)


class SkillExecutionError(AppError):
    code = "SKILL_EXECUTION_ERROR"
    message = "Workflow step failed"


class LLMTimeoutError(AppError):
    code = "LLM_TIMEOUT"
    message = "Model response timed out. Please try again later."
    status_code = 504


class LLMResponseFormatError(AppError):
    code = "LLM_RESPONSE_FORMAT_ERROR"
    message = "Model response format is invalid. Please try again later."


class WorkflowExecutionError(AppError):
    code = "WORKFLOW_EXECUTION_ERROR"
    message = "Workflow execution failed"


class APIAccessDeniedError(AppError):
    code = "API_ACCESS_DENIED"
    message = "A valid API access token is required."
    status_code = 401

    def __init__(self) -> None:
        super().__init__(headers={"WWW-Authenticate": "Bearer"})


class APIRateLimitExceededError(AppError):
    code = "API_RATE_LIMIT_EXCEEDED"
    message = "Too many model requests. Please retry later."
    status_code = 429

    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(1, retry_after)
        super().__init__(headers={"Retry-After": str(self.retry_after)})


class APICapacityExceededError(AppError):
    code = "API_CAPACITY_EXCEEDED"
    message = "Model request capacity is temporarily full. Please retry later."
    status_code = 503

    def __init__(self, retry_after: int = 1) -> None:
        self.retry_after = max(1, retry_after)
        super().__init__(headers={"Retry-After": str(self.retry_after)})


class APIDailyBudgetExceededError(AppError):
    code = "API_DAILY_BUDGET_EXCEEDED"
    message = "The daily model request budget has been exhausted."
    status_code = 429

    def __init__(self, retry_after: int) -> None:
        self.retry_after = max(1, retry_after)
        super().__init__(headers={"Retry-After": str(self.retry_after)})


class PlanNotFoundError(AppError):
    code = "PLAN_NOT_FOUND"
    message = "The requested plan does not exist."
    status_code = 404


class ModelJobNotFoundError(AppError):
    code = "MODEL_JOB_NOT_FOUND"
    message = "The requested model job does not exist."
    status_code = 404


class ModelJobQueueFullError(AppError):
    code = "MODEL_JOB_QUEUE_FULL"
    message = "The model job queue is temporarily full. Please retry later."
    status_code = 503

    def __init__(self, retry_after: int = 5) -> None:
        self.retry_after = max(1, retry_after)
        super().__init__(headers={"Retry-After": str(self.retry_after)})


class PlanVersionConflictError(AppError):
    code = "PLAN_VERSION_CONFLICT"
    message = "The supplied report does not match the persisted plan version."
    status_code = 409


class PlanConcurrentUpdateError(AppError):
    code = "PLAN_CONCURRENT_UPDATE"
    message = "The plan changed concurrently. Reload it before retrying."
    status_code = 409


class IdempotencyConflictError(AppError):
    code = "IDEMPOTENCY_CONFLICT"
    message = "The idempotency key was already used for a different request."
    status_code = 409


class IdempotencyInProgressError(AppError):
    code = "IDEMPOTENCY_IN_PROGRESS"
    message = "An identical request is already being processed."
    status_code = 409

    def __init__(self, retry_after: int = 2) -> None:
        super().__init__(headers={"Retry-After": str(max(1, retry_after))})


class PlanReviewRequiredError(AppError):
    code = "PLAN_REVIEW_REQUIRED"
    message = "This plan must be approved before export."
    status_code = 403


class AuthenticationRequiredError(AppError):
    code = "AUTHENTICATION_REQUIRED"
    message = "A valid user access token is required."
    status_code = 401

    def __init__(self) -> None:
        super().__init__(headers={"WWW-Authenticate": "Bearer"})


class AuthorizationDeniedError(AppError):
    code = "AUTHORIZATION_DENIED"
    message = "Your account is not allowed to perform this action."
    status_code = 403


class SelfReviewDeniedError(AppError):
    code = "SELF_REVIEW_DENIED"
    message = "Plan creators cannot approve or reject their own plans."
    status_code = 403
