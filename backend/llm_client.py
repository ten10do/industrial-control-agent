import json
import math
import os
import random
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC
from email.utils import parsedate_to_datetime
from queue import Empty, Queue
from typing import Any, Protocol

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


class LLMClient(Protocol):
    def chat(self, prompt: str, system_prompt: str | None = None, request_id: str | None = None) -> str: ...


class LLMClientError(RuntimeError):
    """Sanitized model-service error suitable for the API layer."""


class CircuitBreaker:
    """Stop model calls briefly after repeated upstream failures."""

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
        clock_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._clock_fn = clock_fn
        self._failures = 0
        self._last_failure_time = 0.0
        self._lock = threading.Lock()

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            self._last_failure_time = self._clock_fn()

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0

    def is_open(self) -> bool:
        with self._lock:
            if self._failures < self._threshold:
                return False
            if self._clock_fn() - self._last_failure_time >= self._cooldown:
                self._failures = 0
                return False
            return True


DEFAULT_ATTEMPT_TIMEOUT_SECONDS = 60.0
DEFAULT_TOTAL_TIMEOUT_SECONDS = 90.0
DEFAULT_MAX_OUTPUT_TOKENS = 8192
RETRY_JITTER_RATIO = 0.25
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL_ID = "stealth/ox-alpha"
OPENROUTER_APP_URL = "https://industrial-control-agent.netlify.app"
OPENROUTER_APP_TITLE = "Industrial Control Agent"


class OpenRouterLLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = OPENROUTER_BASE_URL,
        model: str = OPENROUTER_MODEL_ID,
        temperature: float = 0.2,
        timeout: float = DEFAULT_ATTEMPT_TIMEOUT_SECONDS,
        total_timeout: float = DEFAULT_TOTAL_TIMEOUT_SECONDS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        reasoning_effort: str = "low",
        max_retries: int = 2,
        backoff_seconds: float = 0.25,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock_fn: Callable[[], float] = time.monotonic,
        wall_clock_fn: Callable[[], float] = time.time,
        random_fn: Callable[[], float] = random.random,
        circuit_breaker: CircuitBreaker | None = None,
        client: Any | None = None,
    ) -> None:
        resolved_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not resolved_key and client is None:
            raise LLMClientError("Model service is not configured")

        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.total_timeout = total_timeout
        self.max_output_tokens = max_output_tokens
        self.reasoning_effort = reasoning_effort
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.sleep_fn = sleep_fn
        self.clock_fn = clock_fn
        self.wall_clock_fn = wall_clock_fn
        self.random_fn = random_fn
        self.circuit_breaker = circuit_breaker or CircuitBreaker(clock_fn=clock_fn)
        self.client = client or OpenAI(
            api_key=resolved_key,
            base_url=base_url,
            default_headers={
                "HTTP-Referer": OPENROUTER_APP_URL,
                "X-OpenRouter-Title": OPENROUTER_APP_TITLE,
            },
            timeout=timeout,
            max_retries=0,
        )

    def chat(self, prompt: str, system_prompt: str | None = None, request_id: str | None = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        retry_count = 0
        response = None
        deadline = self.clock_fn() + self.total_timeout
        for attempt in range(self.max_retries + 1):
            if self.circuit_breaker.is_open():
                raise LLMClientError("Model service is temporarily unavailable")
            attempt_timeout = self._attempt_timeout(deadline)
            try:
                response = self._create_completion(messages, attempt_timeout)
            except LLMTimeoutError:
                self.circuit_breaker.record_failure()
                self._log_retry("error", retry_count, "DeadlineExceeded", request_id)
                raise
            except AuthenticationError as exc:
                self.circuit_breaker.record_failure()
                self._raise_if_deadline_exceeded(deadline, retry_count, request_id)
                raise LLMClientError("Model service authentication failed") from exc
            except APITimeoutError as exc:
                self.circuit_breaker.record_failure()
                self._raise_if_deadline_exceeded(deadline, retry_count, request_id)
                if attempt >= self.max_retries:
                    self._log_retry("error", retry_count, "APITimeoutError", request_id)
                    raise LLMTimeoutError() from exc
                retry_count += 1
                self._log_retry("retry", retry_count, "APITimeoutError", request_id)
                self._sleep_before_retry(attempt, exc, deadline)
            except (APIConnectionError, RateLimitError) as exc:
                self.circuit_breaker.record_failure()
                self._raise_if_deadline_exceeded(deadline, retry_count, request_id)
                if attempt >= self.max_retries:
                    self._log_retry("error", retry_count, type(exc).__name__, request_id)
                    raise LLMClientError("Model service call failed") from exc
                retry_count += 1
                self._log_retry("retry", retry_count, type(exc).__name__, request_id)
                self._sleep_before_retry(attempt, exc, deadline)
            except APIError as exc:
                self.circuit_breaker.record_failure()
                self._raise_if_deadline_exceeded(deadline, retry_count, request_id)
                status_code = getattr(exc, "status_code", None)
                if status_code is not None and status_code < 500 and status_code not in {408, 409, 429}:
                    raise LLMClientError("Model service call failed") from exc
                if attempt >= self.max_retries:
                    self._log_retry("error", retry_count, "APIError", request_id)
                    raise LLMClientError("Model service call failed") from exc
                retry_count += 1
                self._log_retry("retry", retry_count, "APIError", request_id)
                self._sleep_before_retry(attempt, exc, deadline)
            except OpenAIError as exc:
                self.circuit_breaker.record_failure()
                self._raise_if_deadline_exceeded(deadline, retry_count, request_id)
                raise LLMClientError("Model service call failed") from exc
            except Exception as exc:
                self.circuit_breaker.record_failure()
                self._raise_if_deadline_exceeded(deadline, retry_count, request_id)
                raise LLMClientError("Model service call failed") from exc
            else:
                self._raise_if_deadline_exceeded(deadline, retry_count, request_id)
                break

        content = response.choices[0].message.content if response else ""
        if not content or not content.strip():
            self.circuit_breaker.record_failure()
            raise LLMResponseFormatError()
        self.circuit_breaker.record_success()
        return content

    def _create_completion(
        self,
        messages: list[dict[str, str]],
        attempt_timeout: float,
    ) -> Any:
        result_queue: Queue[tuple[bool, Any]] = Queue(maxsize=1)

        def invoke() -> None:
            try:
                result = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_output_tokens,
                    response_format={"type": "json_object"},
                    timeout=attempt_timeout,
                    extra_body={
                        "reasoning": {
                            "effort": self.reasoning_effort,
                            "exclude": True,
                        },
                        "plugins": [{"id": "response-healing"}],
                    },
                )
            except Exception as exc:
                result_queue.put((False, exc))
            else:
                result_queue.put((True, result))

        threading.Thread(target=invoke, daemon=True).start()
        try:
            succeeded, result = result_queue.get(timeout=attempt_timeout)
        except Empty as exc:
            with suppress(Exception):
                self.close()
            raise LLMTimeoutError() from exc
        if succeeded:
            return result
        raise result

    def _log_retry(self, status: str, retry_count: int, error_type: str, request_id: str | None) -> None:
        log_workflow_event(
            request_id=request_id or get_request_id(),
            workflow_name="llm_client",
            step_name="chat_completion",
            status=status,
            retry_count=retry_count,
            error_type=error_type,
        )

    def _raise_if_deadline_exceeded(
        self,
        deadline: float,
        retry_count: int,
        request_id: str | None,
    ) -> None:
        if self.clock_fn() >= deadline:
            self._log_retry("error", retry_count, "DeadlineExceeded", request_id)
            raise LLMTimeoutError()

    def _attempt_timeout(self, deadline: float) -> float:
        remaining = deadline - self.clock_fn()
        if remaining <= 0:
            raise LLMTimeoutError()
        return min(self.timeout, remaining)

    def _sleep_before_retry(self, attempt: int, error: Exception, deadline: float) -> None:
        base_delay = self.backoff_seconds * (2**attempt)
        jitter = base_delay * RETRY_JITTER_RATIO * self.random_fn()
        delay = max(base_delay + jitter, self._retry_after_seconds(error))
        remaining = deadline - self.clock_fn()
        if remaining <= 0 or delay >= remaining:
            raise LLMTimeoutError()
        if delay > 0:
            self.sleep_fn(delay)

    def _retry_after_seconds(self, error: Exception) -> float:
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", None)
        if headers is None:
            return 0.0

        raw_milliseconds = headers.get("retry-after-ms")
        try:
            milliseconds = float(raw_milliseconds)
        except (TypeError, ValueError):
            milliseconds = 0.0
        if math.isfinite(milliseconds) and milliseconds > 0:
            return milliseconds / 1000

        raw_value = headers.get("Retry-After")
        try:
            seconds = float(raw_value)
        except (TypeError, ValueError):
            seconds = 0.0
        if math.isfinite(seconds) and seconds > 0:
            return seconds

        try:
            retry_at = parsedate_to_datetime(raw_value)
        except (TypeError, ValueError, OverflowError):
            return 0.0
        try:
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            seconds = retry_at.timestamp() - self.wall_clock_fn()
        except (OSError, OverflowError, ValueError):
            return 0.0
        return seconds if math.isfinite(seconds) and seconds > 0 else 0.0

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            close()


class FakeLLMClient:
    """Deterministic local client used by tests; it never performs network I/O."""

    def chat(self, prompt: str, system_prompt: str | None = None, request_id: str | None = None) -> str:
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
