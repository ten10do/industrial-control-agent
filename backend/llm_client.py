import json
import os
import random
import time
from collections.abc import Callable
from typing import Any, Optional, Protocol

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    OpenAIError,
    RateLimitError,
)

if __package__:
    from .errors import LLMResponseFormatError, LLMTimeoutError
    from .observability import get_request_id, log_workflow_event
else:
    from errors import LLMResponseFormatError, LLMTimeoutError
    from observability import get_request_id, log_workflow_event


def _jittered_backoff(base_seconds: float, attempt: int, max_jitter: float = 0.5) -> float:
    """Exponential backoff with uniform jitter to avoid thundering herd."""
    raw = base_seconds * (2 ** attempt)
    return raw + random.uniform(0, max_jitter * raw)


class LLMClient(Protocol):
    def chat(self, prompt: str, system_prompt: Optional[str] = None, request_id: Optional[str] = None) -> str: ...


class LLMClientError(RuntimeError):
    """Sanitized model-service error suitable for the API layer."""


class CircuitBreaker:
    """Prevents retry amplification when the model service is consistently failing."""

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 30.0) -> None:
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._failures = 0
        self._last_failure_time = 0.0

    def record_failure(self) -> None:
        self._failures += 1
        self._last_failure_time = time.monotonic()

    def record_success(self) -> None:
        self._failures = 0

    def is_open(self) -> bool:
        if self._failures < self._threshold:
            return False
        if time.monotonic() - self._last_failure_time >= self._cooldown:
            self._failures = 0
            return False
        return True


class DeepSeekLLMClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        temperature: float = 0.2,
        timeout: float = 90.0,
        max_retries: int = 1,
        backoff_seconds: float = 1.0,
        circuit_breaker: CircuitBreaker | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        client: Any | None = None,
    ) -> None:
        resolved_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not resolved_key and client is None:
            raise LLMClientError("Model service is not configured")

        self.model = model
        self.temperature = temperature
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.sleep_fn = sleep_fn
        self.client = client or OpenAI(api_key=resolved_key, base_url=base_url, timeout=timeout)

    def chat(self, prompt: str, system_prompt: Optional[str] = None, request_id: Optional[str] = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        retry_count = 0
        response = None
        for attempt in range(self.max_retries + 1):
            try:
                if self.circuit_breaker.is_open():
                    raise LLMClientError("Model service is temporarily unavailable")
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                )
                self.circuit_breaker.record_success()
                break
            except AuthenticationError as exc:
                self.circuit_breaker.record_failure()
                raise LLMClientError("Model service authentication failed") from exc
            except APITimeoutError as exc:
                self.circuit_breaker.record_failure()
                if attempt >= self.max_retries:
                    self._log_retry("error", retry_count, "APITimeoutError", request_id)
                    raise LLMTimeoutError() from exc
                retry_count += 1
                self._log_retry("retry", retry_count, "APITimeoutError", request_id)
                self.sleep_fn(_jittered_backoff(self.backoff_seconds, attempt))
            except (APIConnectionError, RateLimitError) as exc:
                self.circuit_breaker.record_failure()
                if attempt >= self.max_retries:
                    self._log_retry("error", retry_count, type(exc).__name__, request_id)
                    raise LLMClientError("Model service call failed") from exc
                retry_count += 1
                self._log_retry("retry", retry_count, type(exc).__name__, request_id)
                self.sleep_fn(_jittered_backoff(self.backoff_seconds, attempt))
            except APIError as exc:
                status_code = getattr(exc, "status_code", None)
                if status_code is not None and status_code < 500:
                    self.circuit_breaker.record_failure()
                    raise LLMClientError("Model service call failed") from exc
                self.circuit_breaker.record_failure()
                if attempt >= self.max_retries:
                    self._log_retry("error", retry_count, "APIError", request_id)
                    raise LLMClientError("Model service call failed") from exc
                retry_count += 1
                self._log_retry("retry", retry_count, "APIError", request_id)
                self.sleep_fn(_jittered_backoff(self.backoff_seconds, attempt))
            except OpenAIError as exc:
                self.circuit_breaker.record_failure()
                raise LLMClientError("Model service call failed") from exc
            except Exception as exc:
                self.circuit_breaker.record_failure()
                raise LLMClientError("Model service call failed") from exc

        content = response.choices[0].message.content if response else ""
        self.circuit_breaker.record_success()
        if not content or not content.strip():
            raise LLMResponseFormatError()
        return content

    def _log_retry(self, status: str, retry_count: int, error_type: str, request_id: Optional[str]) -> None:
        log_workflow_event(
            request_id=request_id or get_request_id(),
            workflow_name="llm_client",
            step_name="chat_completion",
            status=status,
            retry_count=retry_count,
            error_type=error_type,
        )


class FakeLLMClient:
    """Deterministic local client used by tests; it never performs network I/O."""

    def chat(self, prompt: str, system_prompt: Optional[str] = None, request_id: Optional[str] = None) -> str:
        if "TASK:OPTIMIZE_CONTROL_PLAN" in prompt:
            return json.dumps(
                {
                    "optimized_report": "# Optimized control plan\n\nFault protection and commissioning checks were added.",
                    "change_summary": "Added sensor fault protection, alarm logic, and commissioning checks.",
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "requirement_analysis": "The system controls actuators from input signals and covers normal and abnormal states.",
                "io_table": [
                    {
                        "address": "I0.0",
                        "signal_name": "Start signal",
                        "signal_type": "DI",
                        "device": "Start button",
                        "description": "Requests system startup",
                    },
                    {
                        "address": "Q0.0",
                        "signal_name": "Run output",
                        "signal_type": "DO",
                        "device": "Actuator",
                        "description": "Drives the primary actuator",
                    },
                ],
                "control_logic": "Set the run output when start and safety conditions are satisfied; reset when stop conditions are active.",
                "safety_design": "Stop outputs and keep alarm state active on emergency stop, fault, or abnormal signals.",
                "ladder_idea": "Divide ladder networks into input processing, start-stop latch, safety interlock, output, and alarm logic.",
                "report_markdown": "# Industrial control plan\n\n## Control description\n\nThe system executes according to the control requirements.",
            },
            ensure_ascii=False,
        )
