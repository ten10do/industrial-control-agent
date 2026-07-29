import threading

import pytest
from fastapi.testclient import TestClient

import backend.main as main_module
import backend.traffic_guard as traffic_guard_module
from backend.errors import (
    APIAccessDeniedError,
    APICapacityExceededError,
    APIDailyBudgetExceededError,
    APIRateLimitExceededError,
    LLMTimeoutError,
)
from backend.llm_client import FakeLLMClient, LLMClientError
from backend.main import app, get_model_api_guard
from backend.traffic_guard import (
    ModelAPITrafficGuard,
    RedisModelAPITrafficGuard,
    TrafficGuardSettings,
)


GENERATE_PAYLOAD = {
    "control_object": "Water tank",
    "input_devices": "Start button, stop button, level sensor",
    "output_devices": "Pump and alarm lamp",
    "control_requirements": "Start and stop the pump from the level signal.",
    "model_provider": "DeepSeek",
}
OPTIMIZE_PAYLOAD = {
    "original_report": "# Original plan\n\nControl the pump from level signals.",
    "optimize_requirement": "Add safety notes.",
    "model_provider": "DeepSeek",
}


def build_guard(
    *,
    max_concurrency: int = 2,
    global_requests: int = 20,
    client_requests: int = 10,
    daily_requests: int = 200,
    window_seconds: float = 60,
    access_token: str | None = None,
    clock=None,
) -> ModelAPITrafficGuard:
    return ModelAPITrafficGuard(
        TrafficGuardSettings(
            max_concurrency=max_concurrency,
            global_requests=global_requests,
            client_requests=client_requests,
            daily_requests=daily_requests,
            window_seconds=window_seconds,
            auth_required=access_token is not None,
            access_token=access_token,
        ),
        clock=clock,
    )


class CountingClientFactory:
    def __init__(self, client=None) -> None:
        self.calls = 0
        self.client = client or FakeLLMClient()

    def __call__(self):
        self.calls += 1
        return self.client


class CountingFakeLLMClient(FakeLLMClient):
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, prompt: str, system_prompt: str | None = None, request_id: str | None = None) -> str:
        self.calls += 1
        return super().chat(prompt, system_prompt, request_id)


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    yield
    app.dependency_overrides.clear()


def test_guard_enforces_access_token_without_consuming_capacity() -> None:
    guard = build_guard(access_token="test-access-token")

    with pytest.raises(APIAccessDeniedError):
        guard.acquire("client-1", None)
    with pytest.raises(APIAccessDeniedError):
        guard.acquire("client-1", "wrong-token")

    lease = guard.acquire("client-1", "test-access-token")
    assert guard.active_requests == 1
    lease.release()
    assert guard.active_requests == 0


def test_guard_enforces_client_rate_limit_and_recovers_after_window() -> None:
    now = [100.0]
    guard = build_guard(
        global_requests=10,
        client_requests=1,
        window_seconds=30,
        clock=lambda: now[0],
    )

    guard.acquire("client-1", None).release()
    with pytest.raises(APIRateLimitExceededError) as error:
        guard.acquire("client-1", None)

    assert error.value.retry_after == 30
    now[0] += 30
    guard.acquire("client-1", None).release()


def test_guard_enforces_global_rate_limit_across_clients() -> None:
    guard = build_guard(global_requests=1, client_requests=10)

    guard.acquire("client-1", None).release()

    with pytest.raises(APIRateLimitExceededError):
        guard.acquire("client-2", None)


def test_guard_keeps_client_rate_buckets_independent() -> None:
    guard = build_guard(global_requests=10, client_requests=1)

    guard.acquire("client-1", None).release()
    with pytest.raises(APIRateLimitExceededError):
        guard.acquire("client-1", None)

    guard.acquire("client-2", None).release()


def test_auth_required_configuration_fails_closed_without_token() -> None:
    with pytest.raises(ValueError, match="MODEL_API_ACCESS_TOKEN"):
        TrafficGuardSettings(auth_required=True)


def test_access_token_configuration_requires_explicit_auth_mode() -> None:
    with pytest.raises(ValueError, match="MODEL_API_AUTH_REQUIRED"):
        TrafficGuardSettings(access_token="test-access-token")


@pytest.mark.parametrize("window_seconds", ["nan", "inf", "-inf"])
def test_non_finite_rate_window_configuration_is_rejected(
    window_seconds: str,
) -> None:
    with pytest.raises(ValueError, match="MODEL_API_RATE_WINDOW_SECONDS"):
        TrafficGuardSettings.from_env(
            {"MODEL_API_RATE_WINDOW_SECONDS": window_seconds},
        )


def test_guard_rejects_excess_concurrency_and_releases_lease_once() -> None:
    guard = build_guard(max_concurrency=1)
    first_lease = guard.acquire("client-1", None)

    with pytest.raises(APICapacityExceededError):
        guard.acquire("client-2", None)

    first_lease.release()
    first_lease.release()
    assert guard.active_requests == 0
    guard.acquire("client-2", None).release()


def test_capacity_rejections_do_not_consume_model_call_rate() -> None:
    guard = build_guard(
        max_concurrency=1,
        global_requests=2,
        client_requests=2,
    )
    first_lease = guard.acquire("client-1", None)

    with pytest.raises(APICapacityExceededError):
        guard.acquire("client-1", None)
    with pytest.raises(APICapacityExceededError):
        guard.acquire("client-1", None)
    first_lease.release()

    guard.acquire("client-1", None).release()
    with pytest.raises(APIRateLimitExceededError):
        guard.acquire("client-1", None)


def test_current_client_bucket_remains_tracked_after_lru_eviction(
    monkeypatch,
) -> None:
    monkeypatch.setattr(traffic_guard_module, "MAX_TRACKED_CLIENTS", 2)
    guard = build_guard(global_requests=10, client_requests=1)

    guard.acquire("client-1", None).release()
    guard.acquire("client-2", None).release()
    guard.acquire("client-3", None).release()

    with pytest.raises(APIRateLimitExceededError):
        guard.acquire("client-3", None)


def test_capacity_rejections_do_not_evict_accepted_client_buckets(
    monkeypatch,
) -> None:
    monkeypatch.setattr(traffic_guard_module, "MAX_TRACKED_CLIENTS", 2)
    guard = build_guard(
        max_concurrency=1,
        global_requests=10,
        client_requests=1,
    )
    guard.acquire("keeper", None).release()
    victim_lease = guard.acquire("victim", None)

    with pytest.raises(APICapacityExceededError):
        guard.acquire("noise-1", None)
    with pytest.raises(APICapacityExceededError):
        guard.acquire("noise-2", None)
    victim_lease.release()

    with pytest.raises(APIRateLimitExceededError):
        guard.acquire("victim", None)


def test_concurrent_clock_reads_keep_rate_timestamps_ordered() -> None:
    first_clock_read = threading.Event()
    second_clock_read = threading.Event()
    calls = 0
    calls_lock = threading.Lock()

    def coordinated_clock() -> float:
        nonlocal calls
        with calls_lock:
            calls += 1
            call_number = calls
        if call_number == 1:
            first_clock_read.set()
            second_clock_read.wait(timeout=0.1)
            return 100.0
        if call_number == 2:
            second_clock_read.set()
            return 105.0
        return 111.0

    guard = build_guard(
        global_requests=2,
        client_requests=2,
        window_seconds=10,
        clock=coordinated_clock,
    )
    failures = []

    def acquire(client_id: str) -> None:
        try:
            guard.acquire(client_id, None).release()
        except Exception as exc:
            failures.append(exc)

    first = threading.Thread(target=acquire, args=("client-1",))
    second = threading.Thread(target=acquire, args=("client-2",))
    first.start()
    assert first_clock_read.wait(timeout=1)
    second.start()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not failures
    guard.acquire("client-3", None).release()


def test_access_rejection_does_not_construct_or_call_llm_client(
    monkeypatch,
) -> None:
    guard = build_guard(access_token="test-access-token")
    llm_client = CountingFakeLLMClient()
    factory = CountingClientFactory(llm_client)
    app.dependency_overrides[get_model_api_guard] = lambda: guard
    monkeypatch.setattr(main_module, "DeepSeekLLMClient", factory)

    with TestClient(app) as client:
        response = client.post(
            "/generate",
            headers={"X-Request-ID": "guard-auth-missing"},
            json=GENERATE_PAYLOAD,
        )
        rejected = client.post(
            "/generate",
            headers={
                "Authorization": "Bearer wrong-token",
                "X-Request-ID": "guard-auth-invalid",
            },
            json=GENERATE_PAYLOAD,
        )
        accepted = client.post(
            "/generate",
            headers={"Authorization": "Bearer test-access-token"},
            json=GENERATE_PAYLOAD,
        )

    assert response.status_code == 401
    assert response.json()["code"] == "API_ACCESS_DENIED"
    assert response.json()["request_id"] == "guard-auth-missing"
    assert response.headers["x-request-id"] == "guard-auth-missing"
    assert response.headers["www-authenticate"] == "Bearer"
    assert rejected.status_code == 401
    assert rejected.json()["request_id"] == "guard-auth-invalid"
    assert rejected.headers["x-request-id"] == "guard-auth-invalid"
    assert "wrong-token" not in rejected.text
    assert "test-access-token" not in rejected.text
    assert accepted.status_code == 200
    assert factory.calls == 1
    assert llm_client.calls == 1
    assert guard.active_requests == 0


def test_non_ascii_bearer_is_rejected_without_constructing_llm(
    monkeypatch,
) -> None:
    guard = build_guard(access_token="test-access-token")
    llm_client = CountingFakeLLMClient()
    factory = CountingClientFactory(llm_client)
    app.dependency_overrides[get_model_api_guard] = lambda: guard
    monkeypatch.setattr(main_module, "DeepSeekLLMClient", factory)

    with TestClient(app) as client:
        response = client.post(
            "/generate",
            headers=[
                (b"authorization", b"Bearer \xff"),
                (b"x-request-id", b"guard-non-ascii"),
            ],
            json=GENERATE_PAYLOAD,
        )

    assert response.status_code == 401
    assert response.json()["code"] == "API_ACCESS_DENIED"
    assert response.json()["request_id"] == "guard-non-ascii"
    assert factory.calls == 0
    assert llm_client.calls == 0


def test_invalid_body_does_not_construct_llm_or_consume_quota(
    monkeypatch,
) -> None:
    guard = build_guard(global_requests=1, client_requests=1)
    llm_client = CountingFakeLLMClient()
    factory = CountingClientFactory(llm_client)
    app.dependency_overrides[get_model_api_guard] = lambda: guard
    monkeypatch.setattr(main_module, "DeepSeekLLMClient", factory)

    with TestClient(app) as client:
        invalid = client.post("/generate", json={"control_object": ""})
        valid = client.post("/generate", json=GENERATE_PAYLOAD)

    assert invalid.status_code == 422
    assert valid.status_code == 200
    assert factory.calls == 1
    assert llm_client.calls == 1
    assert guard.active_requests == 0


def test_generate_and_optimize_share_global_rate_limit(monkeypatch) -> None:
    guard = build_guard(global_requests=1, client_requests=10)
    llm_client = CountingFakeLLMClient()
    factory = CountingClientFactory(llm_client)
    app.dependency_overrides[get_model_api_guard] = lambda: guard
    monkeypatch.setattr(main_module, "DeepSeekLLMClient", factory)

    with TestClient(app) as client:
        first = client.post("/generate", json=GENERATE_PAYLOAD)
        second = client.post(
            "/optimize",
            headers={
                "Origin": "http://localhost:5173",
                "X-Request-ID": "guard-rate-limit",
            },
            json=OPTIMIZE_PAYLOAD,
        )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["code"] == "API_RATE_LIMIT_EXCEEDED"
    assert second.json()["request_id"] == "guard-rate-limit"
    assert second.headers["x-request-id"] == "guard-rate-limit"
    assert second.headers["retry-after"]
    assert "Retry-After" in second.headers["access-control-expose-headers"]
    assert factory.calls == 1
    assert llm_client.calls == 1


def test_concurrency_rejection_does_not_call_llm_and_lease_is_released(
    monkeypatch,
) -> None:
    guard = build_guard(max_concurrency=1)
    started = threading.Event()
    release = threading.Event()

    class BlockingFakeLLMClient(CountingFakeLLMClient):
        def chat(
            self,
            prompt: str,
            system_prompt: str | None = None,
            request_id: str | None = None,
        ) -> str:
            self.calls += 1
            started.set()
            release.wait(timeout=5)
            return FakeLLMClient().chat(prompt, system_prompt, request_id)

    llm_client = BlockingFakeLLMClient()
    factory = CountingClientFactory(llm_client)
    app.dependency_overrides[get_model_api_guard] = lambda: guard
    monkeypatch.setattr(main_module, "DeepSeekLLMClient", factory)
    first_responses = []

    with TestClient(app) as client:
        first_thread = threading.Thread(
            target=lambda: first_responses.append(
                client.post("/generate", json=GENERATE_PAYLOAD),
            ),
        )
        first_thread.start()
        assert started.wait(timeout=2)

        second = client.post(
            "/optimize",
            headers={"X-Request-ID": "guard-capacity-limit"},
            json=OPTIMIZE_PAYLOAD,
        )
        release.set()
        first_thread.join(timeout=5)

    assert second.status_code == 503
    assert second.json()["code"] == "API_CAPACITY_EXCEEDED"
    assert second.json()["request_id"] == "guard-capacity-limit"
    assert second.headers["x-request-id"] == "guard-capacity-limit"
    assert factory.calls == 1
    assert llm_client.calls == 1
    assert first_responses[0].status_code == 200
    assert guard.active_requests == 0


def test_workflow_failure_releases_capacity_for_next_request(monkeypatch) -> None:
    guard = build_guard(max_concurrency=1)

    class FailOnceFakeLLMClient(CountingFakeLLMClient):
        def chat(
            self,
            prompt: str,
            system_prompt: str | None = None,
            request_id: str | None = None,
        ) -> str:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("synthetic workflow failure")
            return FakeLLMClient().chat(prompt, system_prompt, request_id)

    llm_client = FailOnceFakeLLMClient()
    factory = CountingClientFactory(llm_client)
    app.dependency_overrides[get_model_api_guard] = lambda: guard
    monkeypatch.setattr(main_module, "DeepSeekLLMClient", factory)

    with TestClient(app) as client:
        failed = client.post("/generate", json=GENERATE_PAYLOAD)
        recovered = client.post("/generate", json=GENERATE_PAYLOAD)

    assert failed.status_code == 502
    assert recovered.status_code == 200
    assert factory.calls == 2
    assert llm_client.calls == 2
    assert guard.active_requests == 0


def test_llm_factory_failure_releases_capacity_for_next_request(
    monkeypatch,
) -> None:
    guard = build_guard(max_concurrency=1)
    llm_client = CountingFakeLLMClient()

    class FailOnceFactory:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self):
            self.calls += 1
            if self.calls == 1:
                raise LLMClientError("synthetic factory failure")
            return llm_client

    factory = FailOnceFactory()
    app.dependency_overrides[get_model_api_guard] = lambda: guard
    monkeypatch.setattr(main_module, "DeepSeekLLMClient", factory)

    with TestClient(app) as client:
        failed = client.post("/generate", json=GENERATE_PAYLOAD)
        recovered = client.post("/generate", json=GENERATE_PAYLOAD)

    assert failed.status_code == 502
    assert recovered.status_code == 200
    assert factory.calls == 2
    assert llm_client.calls == 1
    assert guard.active_requests == 0


def test_client_close_failure_does_not_replace_successful_response(
    monkeypatch,
) -> None:
    guard = build_guard(max_concurrency=1)

    class CloseTrackingFakeLLMClient(CountingFakeLLMClient):
        def __init__(self) -> None:
            super().__init__()
            self.close_calls = 0
            self.fail_close = True

        def close(self) -> None:
            self.close_calls += 1
            if self.fail_close:
                raise RuntimeError("synthetic close failure")

    llm_client = CloseTrackingFakeLLMClient()
    factory = CountingClientFactory(llm_client)
    app.dependency_overrides[get_model_api_guard] = lambda: guard
    monkeypatch.setattr(main_module, "DeepSeekLLMClient", factory)

    with TestClient(app) as client:
        first = client.post("/generate", json=GENERATE_PAYLOAD)
        llm_client.fail_close = False
        second = client.post("/generate", json=GENERATE_PAYLOAD)

    assert first.status_code == 200
    assert second.status_code == 200
    assert factory.calls == 2
    assert llm_client.calls == 2
    assert llm_client.close_calls == 2
    assert guard.active_requests == 0


def test_client_close_failure_does_not_replace_workflow_error(
    monkeypatch,
) -> None:
    guard = build_guard(max_concurrency=1)

    class TimeoutAndCloseFailingClient:
        def __init__(self) -> None:
            self.close_calls = 0

        def chat(
            self,
            prompt: str,
            system_prompt: str | None = None,
            request_id: str | None = None,
        ) -> str:
            raise LLMTimeoutError()

        def close(self) -> None:
            self.close_calls += 1
            raise RuntimeError("synthetic close failure")

    llm_client = TimeoutAndCloseFailingClient()
    factory = CountingClientFactory(llm_client)
    app.dependency_overrides[get_model_api_guard] = lambda: guard
    monkeypatch.setattr(main_module, "DeepSeekLLMClient", factory)

    with TestClient(app) as client:
        response = client.post("/generate", json=GENERATE_PAYLOAD)

    assert response.status_code == 504
    assert response.json()["code"] == "LLM_TIMEOUT"
    assert llm_client.close_calls == 1
    assert guard.active_requests == 0


def test_health_and_examples_are_not_guarded(monkeypatch) -> None:
    guard = build_guard(access_token="test-access-token")
    factory = CountingClientFactory()
    app.dependency_overrides[get_model_api_guard] = lambda: guard
    monkeypatch.setattr(main_module, "DeepSeekLLMClient", factory)

    with TestClient(app) as client:
        health = client.get("/health")
        examples = client.get("/examples")
        preflight = client.options(
            "/generate",
            headers={
                "Access-Control-Request-Headers": "authorization,content-type",
                "Access-Control-Request-Method": "POST",
                "Origin": "http://localhost:5173",
            },
        )

    assert health.status_code == 200
    assert examples.status_code == 200
    assert preflight.status_code == 200
    assert factory.calls == 0


def test_process_guard_enforces_rolling_daily_budget() -> None:
    guard = build_guard(
        global_requests=10,
        client_requests=10,
        daily_requests=1,
    )
    guard.acquire("client-1", None).release()

    with pytest.raises(APIDailyBudgetExceededError):
        guard.acquire("client-1", None)


class FakeRedis:
    def __init__(self, acquire_result=(0, 0)) -> None:
        self.acquire_result = acquire_result
        self.calls = []
        self.pinged = False
        self.closed = False

    def ping(self) -> None:
        self.pinged = True

    def eval(self, script, key_count, *values):
        self.calls.append((script, key_count, values))
        if key_count == 4:
            return self.acquire_result
        return 1

    def close(self) -> None:
        self.closed = True


def test_redis_guard_uses_atomic_shared_quota_and_releases_lease() -> None:
    redis_client = FakeRedis()
    settings = TrafficGuardSettings(
        max_concurrency=2,
        global_requests=12,
        client_requests=4,
        daily_requests=100,
        redis_url="redis://unused",
    )
    guard = RedisModelAPITrafficGuard(settings, redis_client=redis_client)

    guard.ping()
    lease = guard.acquire("sensitive-client-address", None)
    lease.release()
    guard.close()

    assert redis_client.pinged is True
    assert redis_client.closed is True
    assert len(redis_client.calls) == 2
    acquire_values = redis_client.calls[0][2]
    assert all("sensitive-client-address" not in str(value) for value in acquire_values)


@pytest.mark.parametrize(
    ("result", "error_type"),
    [
        ((1, 15), APIRateLimitExceededError),
        ((2, 15), APIRateLimitExceededError),
        ((3, 1), APICapacityExceededError),
        ((4, 3600), APIDailyBudgetExceededError),
    ],
)
def test_redis_guard_maps_shared_quota_rejections(result, error_type) -> None:
    guard = RedisModelAPITrafficGuard(
        TrafficGuardSettings(redis_url="redis://unused"),
        redis_client=FakeRedis(result),
    )

    with pytest.raises(error_type):
        guard.acquire("client-1", None)
