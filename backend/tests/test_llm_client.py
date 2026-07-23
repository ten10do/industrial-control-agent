import httpx
import pytest
from openai import APIConnectionError, APIError, APITimeoutError

from backend.errors import LLMResponseFormatError, LLMTimeoutError
from backend.llm_client import DeepSeekLLMClient, LLMClientError


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


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.deepseek.com/chat/completions")


def test_llm_timeout_reaches_max_retries_without_real_wait() -> None:
    client = _Client([APITimeoutError(_request()), APITimeoutError(_request()), APITimeoutError(_request())])
    llm = DeepSeekLLMClient(client=client, max_retries=2, backoff_seconds=0, sleep_fn=lambda _: None)

    with pytest.raises(LLMTimeoutError):
        llm.chat("prompt", request_id="timeout-1")

    assert client.completions.calls == 3


def test_transient_error_triggers_retry() -> None:
    client = _Client([APIConnectionError(request=_request()), '{"ok": true}'])
    llm = DeepSeekLLMClient(client=client, max_retries=2, backoff_seconds=0, sleep_fn=lambda _: None)

    assert llm.chat("prompt", request_id="retry-1") == '{"ok": true}'
    assert client.completions.calls == 2


def test_non_transient_error_does_not_retry() -> None:
    error = APIError("bad request", _request(), body=None)
    error.status_code = 400
    client = _Client([error, '{"ok": true}'])
    llm = DeepSeekLLMClient(client=client, max_retries=2, backoff_seconds=0, sleep_fn=lambda _: None)

    with pytest.raises(LLMClientError):
        llm.chat("prompt", request_id="non-transient-1")

    assert client.completions.calls == 1


def test_empty_llm_content_is_format_error() -> None:
    client = _Client([""])
    llm = DeepSeekLLMClient(client=client, max_retries=2, backoff_seconds=0, sleep_fn=lambda _: None)

    with pytest.raises(LLMResponseFormatError):
        llm.chat("prompt", request_id="empty-1")
