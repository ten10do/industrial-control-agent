import hashlib
import math
import os
import secrets
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from sqlalchemy.engine import Engine

if __package__:
    from .database_schema import model_api_daily_usage
    from .errors import (
        APIAccessDeniedError,
        APICapacityExceededError,
        APIDailyBudgetExceededError,
        APIRateLimitExceededError,
    )
else:
    from database_schema import model_api_daily_usage
    from errors import (
        APIAccessDeniedError,
        APICapacityExceededError,
        APIDailyBudgetExceededError,
        APIRateLimitExceededError,
    )


DEFAULT_MAX_CONCURRENCY = 2
DEFAULT_GLOBAL_REQUESTS = 12
DEFAULT_CLIENT_REQUESTS = 4
DEFAULT_WINDOW_SECONDS = 60.0
DEFAULT_DAILY_REQUESTS = 200
DAILY_WINDOW_SECONDS = 86400.0
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
    daily_requests: int = DEFAULT_DAILY_REQUESTS
    auth_required: bool = False
    access_token: str | None = None
    redis_url: str | None = None
    redis_key_prefix: str = "industrial-control-agent"

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
            daily_requests=_positive_int(
                values,
                "MODEL_API_DAILY_REQUESTS",
                DEFAULT_DAILY_REQUESTS,
            ),
            auth_required=_boolean(
                values,
                "MODEL_API_AUTH_REQUIRED",
                False,
            ),
            access_token=access_token,
            redis_url=values.get("MODEL_API_REDIS_URL", "").strip() or None,
            redis_key_prefix=values.get(
                "MODEL_API_REDIS_KEY_PREFIX",
                "industrial-control-agent",
            ).strip()
            or "industrial-control-agent",
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
        self._daily_requests: deque[float] = deque()
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
            self._prune(self._daily_requests, now, DAILY_WINDOW_SECONDS)
            if len(self._daily_requests) >= self.settings.daily_requests:
                raise APIDailyBudgetExceededError(
                    self._retry_after(self._daily_requests, now, DAILY_WINDOW_SECONDS),
                )
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
            self._daily_requests.append(now)
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

    def _prune(
        self,
        timestamps: deque[float],
        now: float,
        window_seconds: float | None = None,
    ) -> None:
        cutoff = now - (window_seconds or self.settings.window_seconds)
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()

    def _retry_after(
        self,
        timestamps: deque[float],
        now: float,
        window_seconds: float | None = None,
    ) -> int:
        remaining = timestamps[0] + (window_seconds or self.settings.window_seconds) - now
        return max(1, math.ceil(remaining))

    def _release(self) -> None:
        with self._lock:
            if self._active_requests > 0:
                self._active_requests -= 1


class DatabaseModelAPITrafficGuard:
    """Local burst protection with a shared, atomic daily database budget."""

    def __init__(
        self,
        settings: TrafficGuardSettings,
        engine: Engine,
        *,
        utcnow: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self._engine = engine
        self._utcnow = utcnow or (lambda: datetime.now(UTC))
        self._local_guard = ModelAPITrafficGuard(
            replace(settings, daily_requests=2_147_483_647),
        )

    @property
    def active_requests(self) -> int:
        return self._local_guard.active_requests

    def ping(self) -> None:
        with self._engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1").scalar_one()

    def acquire(
        self,
        client_id: str,
        access_token: str | None,
    ) -> TrafficGuardLease:
        local_lease = self._local_guard.acquire(client_id, access_token)
        try:
            self._consume_daily_request()
        except Exception:
            local_lease.release()
            raise
        return local_lease

    def _consume_daily_request(self) -> None:
        now = self._utcnow()
        if now.tzinfo is None:
            raise ValueError("The database quota clock must be timezone-aware")
        now = now.astimezone(UTC)
        bucket_date = now.date().isoformat()
        values = {
            "bucket_date": bucket_date,
            "request_count": 1,
            "updated_at": now.isoformat(),
        }
        if self._engine.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        elif self._engine.dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        else:
            raise RuntimeError("Database model quota requires PostgreSQL or SQLite")

        statement = (
            insert(model_api_daily_usage)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[model_api_daily_usage.c.bucket_date],
                set_={
                    "request_count": model_api_daily_usage.c.request_count + 1,
                    "updated_at": values["updated_at"],
                },
                where=(
                    model_api_daily_usage.c.request_count
                    < self.settings.daily_requests
                ),
            )
            .returning(model_api_daily_usage.c.request_count)
        )
        with self._engine.begin() as connection:
            request_count = connection.execute(statement).scalar_one_or_none()
        if request_count is None:
            tomorrow = datetime.combine(
                now.date() + timedelta(days=1),
                datetime.min.time(),
                tzinfo=UTC,
            )
            raise APIDailyBudgetExceededError(
                max(1, math.ceil((tomorrow - now).total_seconds())),
            )


REDIS_ACQUIRE_SCRIPT = """
redis.call('ZREMRANGEBYSCORE', KEYS[4], 0, ARGV[8])
local active = tonumber(redis.call('ZCARD', KEYS[4]) or '0')
if active >= tonumber(ARGV[3]) then return {3, 1} end
local daily = tonumber(redis.call('GET', KEYS[3]) or '0')
if daily >= tonumber(ARGV[4]) then return {4, redis.call('TTL', KEYS[3])} end
local global_count = tonumber(redis.call('GET', KEYS[1]) or '0')
if global_count >= tonumber(ARGV[1]) then return {1, redis.call('TTL', KEYS[1])} end
local client_count = tonumber(redis.call('GET', KEYS[2]) or '0')
if client_count >= tonumber(ARGV[2]) then return {2, redis.call('TTL', KEYS[2])} end
redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ARGV[5])
redis.call('INCR', KEYS[2])
redis.call('EXPIRE', KEYS[2], ARGV[5])
redis.call('INCR', KEYS[3])
redis.call('EXPIRE', KEYS[3], ARGV[6])
redis.call('ZADD', KEYS[4], ARGV[8] + (ARGV[7] * 1000), ARGV[9])
redis.call('EXPIRE', KEYS[4], ARGV[7] + 1)
return {0, 0}
"""

REDIS_RELEASE_SCRIPT = """
return redis.call('ZREM', KEYS[1], ARGV[1])
"""


class RedisModelAPITrafficGuard:
    """Cross-process quotas backed by atomic Redis scripts."""

    def __init__(self, settings: TrafficGuardSettings, redis_client=None) -> None:
        self.settings = settings
        if redis_client is None:
            if not settings.redis_url:
                raise ValueError("MODEL_API_REDIS_URL is required for Redis traffic control")
            from redis import Redis

            redis_client = Redis.from_url(
                settings.redis_url,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
        self._redis = redis_client
        self._active_key = f"{settings.redis_key_prefix}:active"

    def ping(self) -> None:
        self._redis.ping()

    def acquire(self, client_id: str, access_token: str | None) -> TrafficGuardLease:
        self._authorize(access_token)
        now = time.time()
        window_seconds = max(1, math.ceil(self.settings.window_seconds))
        window_bucket = int(now // window_seconds)
        daily_bucket = int(now // int(DAILY_WINDOW_SECONDS))
        client_digest = hashlib.sha256(
            (client_id.strip() or "unknown").encode("utf-8"),
        ).hexdigest()[:24]
        prefix = self.settings.redis_key_prefix
        keys = (
            f"{prefix}:window:{window_bucket}:global",
            f"{prefix}:window:{window_bucket}:client:{client_digest}",
            f"{prefix}:day:{daily_bucket}",
            self._active_key,
        )
        daily_ttl = max(1, math.ceil(((daily_bucket + 1) * DAILY_WINDOW_SECONDS) - now))
        lease_ttl = 120
        lease_id = secrets.token_hex(16)
        result = self._redis.eval(
            REDIS_ACQUIRE_SCRIPT,
            len(keys),
            *keys,
            self.settings.global_requests,
            self.settings.client_requests,
            self.settings.max_concurrency,
            self.settings.daily_requests,
            window_seconds + 1,
            daily_ttl,
            lease_ttl,
            math.floor(now * 1000),
            lease_id,
        )
        code = int(result[0])
        retry_after = max(1, int(result[1] or 1))
        if code in {1, 2}:
            raise APIRateLimitExceededError(retry_after)
        if code == 3:
            raise APICapacityExceededError()
        if code == 4:
            raise APIDailyBudgetExceededError(retry_after)
        return TrafficGuardLease(lambda: self._release(lease_id))

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

    def _release(self, lease_id: str) -> None:
        self._redis.eval(REDIS_RELEASE_SCRIPT, 1, self._active_key, lease_id)

    def close(self) -> None:
        close = getattr(self._redis, "close", None)
        if callable(close):
            close()
