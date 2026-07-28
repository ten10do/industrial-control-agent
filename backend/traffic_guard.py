import math
import os
import secrets
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass

if __package__:
    from .errors import (
        APIAccessDeniedError,
        APICapacityExceededError,
        APIRateLimitExceededError,
    )
else:
    from errors import (
        APIAccessDeniedError,
        APICapacityExceededError,
        APIRateLimitExceededError,
    )


DEFAULT_MAX_CONCURRENCY = 2
DEFAULT_GLOBAL_REQUESTS = 12
DEFAULT_CLIENT_REQUESTS = 4
DEFAULT_WINDOW_SECONDS = 60.0
MAX_TRACKED_CLIENTS = 4096


def _positive_int(environ: Mapping[str, str], name: str, default: int) -> int:
    raw_value = environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_float(environ: Mapping[str, str], name: str, default: float) -> float:
    raw_value = environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return value


def _boolean(environ: Mapping[str, str], name: str, default: bool) -> bool:
    raw_value = environ.get(name, "").strip().lower()
    if not raw_value:
        return default
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


@dataclass(frozen=True)
class TrafficGuardSettings:
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY
    global_requests: int = DEFAULT_GLOBAL_REQUESTS
    client_requests: int = DEFAULT_CLIENT_REQUESTS
    window_seconds: float = DEFAULT_WINDOW_SECONDS
    auth_required: bool = False
    access_token: str | None = None

    def __post_init__(self) -> None:
        if self.auth_required and not self.access_token:
            raise ValueError(
                "MODEL_API_ACCESS_TOKEN is required when "
                "MODEL_API_AUTH_REQUIRED is enabled",
            )
        if self.access_token and not self.auth_required:
            raise ValueError(
                "MODEL_API_AUTH_REQUIRED must be enabled when "
                "MODEL_API_ACCESS_TOKEN is configured",
            )

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "TrafficGuardSettings":
        values = environ if environ is not None else os.environ
        access_token = values.get("MODEL_API_ACCESS_TOKEN", "").strip() or None
        return cls(
            max_concurrency=_positive_int(
                values,
                "MODEL_API_MAX_CONCURRENCY",
                DEFAULT_MAX_CONCURRENCY,
            ),
            global_requests=_positive_int(
                values,
                "MODEL_API_GLOBAL_REQUESTS",
                DEFAULT_GLOBAL_REQUESTS,
            ),
            client_requests=_positive_int(
                values,
                "MODEL_API_CLIENT_REQUESTS",
                DEFAULT_CLIENT_REQUESTS,
            ),
            window_seconds=_positive_float(
                values,
                "MODEL_API_RATE_WINDOW_SECONDS",
                DEFAULT_WINDOW_SECONDS,
            ),
            auth_required=_boolean(
                values,
                "MODEL_API_AUTH_REQUIRED",
                False,
            ),
            access_token=access_token,
        )


class TrafficGuardLease:
    def __init__(self, release_fn: Callable[[], None]) -> None:
        self._release_fn = release_fn
        self._released = False
        self._lock = threading.Lock()

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        self._release_fn()


class ModelAPITrafficGuard:
    """Process-local rate and concurrency protection for paid model routes."""

    def __init__(
        self,
        settings: TrafficGuardSettings,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.settings = settings
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._global_requests: deque[float] = deque()
        self._client_requests: OrderedDict[str, deque[float]] = OrderedDict()
        self._active_requests = 0

    @property
    def active_requests(self) -> int:
        with self._lock:
            return self._active_requests

    def acquire(
        self,
        client_id: str,
        access_token: str | None,
    ) -> TrafficGuardLease:
        self._authorize(access_token)
        normalized_client_id = client_id.strip() or "unknown"

        with self._lock:
            now = self._clock()
            self._prune(self._global_requests, now)
            if len(self._global_requests) >= self.settings.global_requests:
                raise APIRateLimitExceededError(
                    self._retry_after(self._global_requests, now),
                )

            client_requests = self._client_requests.get(normalized_client_id)
            if client_requests is None:
                client_requests = deque()
            self._prune(client_requests, now)

            if len(client_requests) >= self.settings.client_requests:
                raise APIRateLimitExceededError(
                    self._retry_after(client_requests, now),
                )
            if self._active_requests >= self.settings.max_concurrency:
                raise APICapacityExceededError()

            if normalized_client_id not in self._client_requests:
                while len(self._client_requests) >= MAX_TRACKED_CLIENTS:
                    self._client_requests.popitem(last=False)
                self._client_requests[normalized_client_id] = client_requests
            self._client_requests.move_to_end(normalized_client_id)
            self._global_requests.append(now)
            client_requests.append(now)
            self._active_requests += 1

        return TrafficGuardLease(self._release)

    def _authorize(self, access_token: str | None) -> None:
        if not self.settings.auth_required:
            return
        required_token = self.settings.access_token
        assert required_token is not None
        if access_token is None or not secrets.compare_digest(
            access_token.encode("utf-8"),
            required_token.encode("utf-8"),
        ):
            raise APIAccessDeniedError()

    def _prune(self, timestamps: deque[float], now: float) -> None:
        cutoff = now - self.settings.window_seconds
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()

    def _retry_after(self, timestamps: deque[float], now: float) -> int:
        remaining = timestamps[0] + self.settings.window_seconds - now
        return max(1, math.ceil(remaining))

    def _release(self) -> None:
        with self._lock:
            if self._active_requests > 0:
                self._active_requests -= 1
