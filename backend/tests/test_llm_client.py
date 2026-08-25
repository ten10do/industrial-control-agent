import threading
import time
from datetime import UTC, datetime
from email.utils import format_datetime

import httpx
import pytest
from openai import APIConnectionError, APIError, APITimeoutError, RateLimitError

import backend.llm_client as llm_client_module
from backend.errors import LLMResponseFormatError, LLMTimeoutError
from backend.llm_client import LLMClientError, OpenRouterLLMClient


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str) -> None:
        self.message = _Message(content)


class _Response:
    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    def create(self, **_: object) -> _Response:
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return _Response(str(outcome))


class _Chat:
    def __init__(self, completions: _Completions) -> None:
        self.completions = completions


class _Client:
    def __init__(self, outcomes: list[object]) -> None:
        self.completions = _Completions(outcomes)
        self.chat = _Chat(self.completions)
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.advance(seconds)


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")


def _rate_limit_error(retry_after: str, header: str = "Retry-After") -> RateLimitError:
    response = httpx.Response(
        429,
        request=_request(),
        headers={header: retry_after},
    )
    return RateLimitError("rate limited", response=response, body=None)


def test_production_openai_client_disables_sdk_retries(monkeypatch) -> None:
    captured: dict[str, object] = {}
    client = _Client(['{"ok": true}'])

    def build_client(**kwargs: object) -> _Client:
        captured.update(kwargs)
        return client

    monkeypatch.setattr(llm_client_module, "OpenAI", build_client)

    llm = OpenRouterLLMClient(api_key="placeholder")

    assert captured["base_url"] == "https://openrouter.ai/api/v1"
    assert captured["default_headers"] == {
        "HTTP-Referer": "https://industrial-control-agent.netlify.app",
        "X-OpenRouter-Title": "Industrial Control Agent",
    }
    assert captured["max_retries"] == 0
    assert captured["timeout"] == 60
    assert llm.model == "stealth/ox-alpha"
    assert llm.total_timeout == 90


def test_ox_alpha_request_bounds_output_and_reasoning() -> None:
    captured: dict[str, object] = {}

    class _CapturingCompletions:
        def create(self, **kwargs: object) -> _Response:
            captured.update(kwargs)
            return _Response('{"ok": true}')

    client = _Client([])
    client.chat = _Chat(_CapturingCompletions())
    llm = OpenRouterLLMClient(client=client)

    assert llm.chat("prompt") == '{"ok": true}'
    assert captured["max_tokens"] == 8192
    assert captured["extra_body"] == {
        "reasoning": {"effort": "low", "exclude": True},
        "plugins": [{"id": "response-healing"}],
    }


def test_hard_attempt_timeout_closes_a_trickling_client() -> None:
    release = threading.Event()

    class _BlockingCompletions:
        def create(self, **_: object) -> _Response:
            release.wait(timeout=1)
            return _Response('{"ok": true}')

    class _BlockingClient(_Client):
        def __init__(self) -> None:
            super().__init__([])
            self.chat = _Chat(_BlockingCompletions())

        def close(self) -> None:
            super().close()
            release.set()

    client = _BlockingClient()
    llm = OpenRouterLLMClient(
        client=client,
        timeout=0.02,
        total_timeout=0.02,
        max_retries=0,
    )
    started = time.monotonic()

    with pytest.raises(LLMTimeoutError):
        llm.chat("prompt", request_id="hard-timeout-1")

    assert time.monotonic() - started < 0.5
    assert client.closed is True


def test_llm_timeout_reaches_max_retries_without_real_wait() -> None:
    client = _Client([APITimeoutError(_request()), APITimeoutError(_request()), APITimeoutError(_request())])
    llm = OpenRouterLLMClient(client=client, max_retries=2, backoff_seconds=0, sleep_fn=lambda _: None)

    with pytest.raises(LLMTimeoutError):
        llm.chat("prompt", request_id="timeout-1")

    assert client.completions.calls == 3


def test_transient_error_triggers_retry() -> None:
    client = _Client([APIConnectionError(request=_request()), '{"ok": true}'])
    llm = OpenRouterLLMClient(client=client, max_retries=2, backoff_seconds=0, sleep_fn=lambda _: None)

    assert llm.chat("prompt", request_id="retry-1") == '{"ok": true}'
    assert client.completions.calls == 2


def test_total_deadline_caps_attempt_timeout_and_stops_extra_calls() -> None:
    clock = _Clock()

    class _TimedCompletions:
        def __init__(self) -> None:
            self.calls = 0
            self.timeouts: list[float] = []

        def create(self, **kwargs: object) -> _Response:
            timeout = float(kwargs["timeout"])
            self.calls += 1
            self.timeouts.append(timeout)
            clock.advance(timeout)
            raise APITimeoutError(_request())

    completions = _TimedCompletions()
    client = _Client([])
    client.completions = completions
    client.chat = _Chat(completions)
    llm = OpenRouterLLMClient(
        client=client,
        timeout=60,
        total_timeout=90,
        max_retries=2,
        backoff_seconds=0,
        sleep_fn=clock.sleep,
        clock_fn=clock,
    )

    with pytest.raises(LLMTimeoutError):
        llm.chat("prompt", request_id="deadline-1")

    assert completions.calls == 2
    assert completions.timeouts == pytest.approx([60, 30])
    assert clock.now == pytest.approx(90)


def test_successful_response_after_total_deadline_is_rejected() -> None:
    clock = _Clock()

    class _LateCompletions:
        def __init__(self) -> None:
            self.calls = 0

        def create(self, **_: object) -> _Response:
            self.calls += 1
            clock.advance(91)
            return _Response('{"ok": true}')

    completions = _LateCompletions()
    client = _Client([])
    client.completions = completions
    client.chat = _Chat(completions)
    llm = OpenRouterLLMClient(
        client=client,
        total_timeout=90,
        clock_fn=clock,
    )

    with pytest.raises(LLMTimeoutError):
        llm.chat("prompt", request_id="late-success-1")

    assert completions.calls == 1


@pytest.mark.parametrize("error_kind", ["connection", "rate_limit", "server_error"])
def test_error_after_total_deadline_is_reported_as_timeout(error_kind: str) -> None:
    clock = _Clock()
    if error_kind == "connection":
        error = APIConnectionError(request=_request())
    elif error_kind == "rate_limit":
        error = _rate_limit_error("1")
    else:
        error = APIError("server error", _request(), body=None)
        error.status_code = 500

    class _LateErrorCompletions:
        def __init__(self) -> None:
            self.calls = 0

        def create(self, **_: object) -> _Response:
            self.calls += 1
            clock.advance(91)
            raise error

    completions = _LateErrorCompletions()
    client = _Client([])
    client.completions = completions
    client.chat = _Chat(completions)
    llm = OpenRouterLLMClient(
        client=client,
        total_timeout=90,
        max_retries=0,
        clock_fn=clock,
    )

    with pytest.raises(LLMTimeoutError):
        llm.chat("prompt", request_id=f"late-{error_kind}-1")

    assert completions.calls == 1


def test_rate_limit_retry_honors_retry_after() -> None:
    clock = _Clock()
    client = _Client([_rate_limit_error("7"), '{"ok": true}'])
    llm = OpenRouterLLMClient(
        client=client,
        max_retries=1,
        backoff_seconds=0.25,
        sleep_fn=clock.sleep,
        clock_fn=clock,
        random_fn=lambda: 0,
    )

    assert llm.chat("prompt", request_id="retry-after-1") == '{"ok": true}'
    assert client.completions.calls == 2
    assert clock.sleeps == [7]


def test_rate_limit_retry_honors_http_date_retry_after() -> None:
    clock = _Clock()
    wall_clock = 1_000.0
    retry_at = format_datetime(
        datetime.fromtimestamp(wall_clock + 7, tz=UTC),
        usegmt=True,
    )
    client = _Client([_rate_limit_error(retry_at), '{"ok": true}'])
    llm = OpenRouterLLMClient(
        client=client,
        max_retries=1,
        sleep_fn=clock.sleep,
        clock_fn=clock,
        wall_clock_fn=lambda: wall_clock,
        random_fn=lambda: 0,
    )

    assert llm.chat("prompt", request_id="retry-after-date-1") == '{"ok": true}'
    assert clock.sleeps == [7]


def test_rate_limit_retry_honors_retry_after_milliseconds() -> None:
    clock = _Clock()
    client = _Client(
        [_rate_limit_error("1500", header="retry-after-ms"), '{"ok": true}'],
    )
    llm = OpenRouterLLMClient(
        client=client,
        max_retries=1,
        sleep_fn=clock.sleep,
        clock_fn=clock,
        random_fn=lambda: 0,
    )

    assert llm.chat("prompt", request_id="retry-after-ms-1") == '{"ok": true}'
    assert clock.sleeps == [1.5]


@pytest.mark.parametrize("retry_after", ["invalid", "-1", "NaN"])
def test_invalid_retry_after_uses_exponential_backoff(retry_after: str) -> None:
    clock = _Clock()
    client = _Client([_rate_limit_error(retry_after), '{"ok": true}'])
    llm = OpenRouterLLMClient(
        client=client,
        max_retries=1,
        backoff_seconds=0.25,
        sleep_fn=clock.sleep,
        clock_fn=clock,
        random_fn=lambda: 0,
    )

    assert llm.chat("prompt", request_id="invalid-retry-after-1") == '{"ok": true}'
    assert clock.sleeps == [0.25]


def test_retry_after_beyond_deadline_stops_without_waiting_or_retrying() -> None:
    clock = _Clock()
    client = _Client([_rate_limit_error("120"), '{"ok": true}'])
    llm = OpenRouterLLMClient(
        client=client,
        total_timeout=90,
        max_retries=1,
        sleep_fn=clock.sleep,
        clock_fn=clock,
        random_fn=lambda: 0,
    )

    with pytest.raises(LLMTimeoutError):
        llm.chat("prompt", request_id="retry-after-deadline-1")

    assert client.completions.calls == 1
    assert clock.sleeps == []


@pytest.mark.parametrize("status_code", [408, 409, 500])
def test_sdk_retryable_api_statuses_remain_retryable(status_code: int) -> None:
    error = APIError("retryable", _request(), body=None)
    error.status_code = status_code
    client = _Client([error, '{"ok": true}'])
    llm = OpenRouterLLMClient(
        client=client,
        max_retries=1,
        backoff_seconds=0,
        sleep_fn=lambda _: None,
    )

    assert llm.chat("prompt", request_id=f"retryable-{status_code}") == '{"ok": true}'
    assert client.completions.calls == 2


def test_non_transient_error_does_not_retry() -> None:
    error = APIError("bad request", _request(), body=None)
    error.status_code = 400
    client = _Client([error, '{"ok": true}'])
    llm = OpenRouterLLMClient(client=client, max_retries=2, backoff_seconds=0, sleep_fn=lambda _: None)

    with pytest.raises(LLMClientError):
        llm.chat("prompt", request_id="non-transient-1")

    assert client.completions.calls == 1


def test_empty_llm_content_is_format_error() -> None:
    client = _Client([""])
    llm = OpenRouterLLMClient(client=client, max_retries=2, backoff_seconds=0, sleep_fn=lambda _: None)

    with pytest.raises(LLMResponseFormatError):
        llm.chat("prompt", request_id="empty-1")


def test_llm_client_closes_underlying_http_client() -> None:
    client = _Client(['{"ok": true}'])
    llm = OpenRouterLLMClient(client=client)

    llm.close()

    assert client.closed is True
