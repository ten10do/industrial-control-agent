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
