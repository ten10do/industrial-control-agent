import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

PROJECT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
DEFAULT_FRONTEND_ORIGIN = "http://localhost:5173"
DEFAULT_PLAN_STORAGE_PATH = Path(__file__).resolve().parent / "data" / "plans.db"


@dataclass(frozen=True)
class AppSettings:
    environment: str
    frontend_origin: str
    log_level: int
    plan_storage_path: Path
    database_url: str = field(repr=False)
    database_auto_migrate: bool
    database_pool_size: int
    database_max_overflow: int
    database_sslmode: str
    database_connect_timeout_seconds: int
    audit_signing_keys: dict[str, str] = field(repr=False)
    audit_active_key_id: str | None
    audit_sink_required: bool
    audit_sink_url: str
    audit_sink_token: str = field(repr=False)
    audit_outbox_max_pending: int
    audit_worker_max_staleness_seconds: int
    model_job_worker_required: bool
    model_job_worker_max_staleness_seconds: int
    model_job_queue_max_pending: int
    model_job_lease_seconds: int
    model_job_max_attempts: int

    @property
    def allowed_origins(self) -> list[str]:
        origins = [DEFAULT_FRONTEND_ORIGIN]
        if self.frontend_origin and self.frontend_origin not in origins:
            origins.append(self.frontend_origin)
        return origins

    @classmethod
    def from_env(cls) -> "AppSettings":
        environment = os.getenv("APP_ENV", "production").strip().lower()
        frontend_origin = os.getenv("FRONTEND_ORIGIN", "").strip().rstrip("/")
        raw_log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
        log_level = logging.getLevelNamesMapping().get(raw_log_level)
        if not isinstance(log_level, int):
            raise ValueError("LOG_LEVEL must be a valid Python logging level")
        plan_storage_path = Path(
            os.getenv("PLAN_STORAGE_PATH", str(DEFAULT_PLAN_STORAGE_PATH)),
        ).expanduser()
        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            database_url = f"sqlite+pysqlite:///{plan_storage_path.resolve().as_posix()}"
        if database_url.startswith("postgres://"):
            database_url = f"postgresql+psycopg://{database_url.removeprefix('postgres://')}"
        elif database_url.startswith("postgresql://"):
            database_url = (
                f"postgresql+psycopg://{database_url.removeprefix('postgresql://')}"
            )
        database_scheme = urlparse(database_url).scheme
        if database_scheme not in {"sqlite", "sqlite+pysqlite", "postgresql+psycopg"}:
            raise ValueError("DATABASE_URL must use SQLite or PostgreSQL with psycopg")
        if environment == "production" and database_scheme != "postgresql+psycopg":
            raise ValueError("Production requires a PostgreSQL DATABASE_URL")

        raw_auto_migrate = os.getenv(
            "DATABASE_AUTO_MIGRATE",
            "false" if environment == "production" else "true",
        )
        database_auto_migrate = _parse_bool(raw_auto_migrate, "DATABASE_AUTO_MIGRATE")
        if environment == "production" and database_auto_migrate:
            raise ValueError("DATABASE_AUTO_MIGRATE must be false in production")
        database_pool_size = _parse_positive_int(
            os.getenv("DATABASE_POOL_SIZE", "5"),
            "DATABASE_POOL_SIZE",
            maximum=100,
        )
        database_max_overflow = _parse_nonnegative_int(
            os.getenv("DATABASE_MAX_OVERFLOW", "10"),
            "DATABASE_MAX_OVERFLOW",
            maximum=200,
        )
        database_sslmode = os.getenv(
            "DATABASE_SSLMODE",
            "require" if environment == "production" else "prefer",
        ).strip().lower()
        allowed_sslmodes = {
            "disable",
            "allow",
            "prefer",
            "require",
            "verify-ca",
            "verify-full",
        }
        if database_sslmode not in allowed_sslmodes:
            raise ValueError("DATABASE_SSLMODE is invalid")
        if (
            environment == "production"
            and database_sslmode not in {"require", "verify-ca", "verify-full"}
        ):
            raise ValueError("Production PostgreSQL must require TLS")

        raw_signing_keys = os.getenv("AUDIT_SIGNING_KEYS_JSON", "").strip()
        try:
            parsed_signing_keys = json.loads(raw_signing_keys) if raw_signing_keys else {}
        except json.JSONDecodeError as exc:
            raise ValueError("AUDIT_SIGNING_KEYS_JSON must be valid JSON") from exc
        if not isinstance(parsed_signing_keys, dict) or not all(
            isinstance(key_id, str) and isinstance(secret, str)
            for key_id, secret in parsed_signing_keys.items()
        ):
            raise ValueError("AUDIT_SIGNING_KEYS_JSON must be a string-to-string object")
        audit_signing_keys = dict(parsed_signing_keys)
        for key_id, secret in audit_signing_keys.items():
            if not key_id.strip() or len(secret.encode("utf-8")) < 32:
                raise ValueError("Every audit signing key must have an ID and at least 32 bytes")
        audit_active_key_id = os.getenv("AUDIT_ACTIVE_KEY_ID", "").strip() or None
        if audit_active_key_id and audit_active_key_id not in audit_signing_keys:
            raise ValueError("AUDIT_ACTIVE_KEY_ID must exist in AUDIT_SIGNING_KEYS_JSON")
        if environment == "production" and not audit_active_key_id:
            raise ValueError("Production requires an active audit signing key")

        audit_sink_required = _parse_bool(
            os.getenv(
                "AUDIT_SINK_REQUIRED",
                "true" if environment == "production" else "false",
            ),
            "AUDIT_SINK_REQUIRED",
        )
        audit_sink_url = os.getenv("AUDIT_SINK_URL", "").strip()
        if audit_sink_required and urlparse(audit_sink_url).scheme != "https":
            raise ValueError("AUDIT_SINK_URL must use HTTPS when the sink is required")

        return cls(
            environment=environment,
            frontend_origin=frontend_origin,
            log_level=log_level,
            plan_storage_path=plan_storage_path,
            database_url=database_url,
            database_auto_migrate=database_auto_migrate,
            database_pool_size=database_pool_size,
            database_max_overflow=database_max_overflow,
            database_sslmode=database_sslmode,
            database_connect_timeout_seconds=_parse_positive_int(
                os.getenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "5"),
                "DATABASE_CONNECT_TIMEOUT_SECONDS",
                maximum=30,
            ),
            audit_signing_keys=audit_signing_keys,
            audit_active_key_id=audit_active_key_id,
            audit_sink_required=audit_sink_required,
            audit_sink_url=audit_sink_url,
            audit_sink_token=os.getenv("AUDIT_SINK_TOKEN", ""),
            audit_outbox_max_pending=_parse_positive_int(
                os.getenv("AUDIT_OUTBOX_MAX_PENDING", "10000"),
                "AUDIT_OUTBOX_MAX_PENDING",
                maximum=1_000_000,
            ),
            audit_worker_max_staleness_seconds=_parse_positive_int(
                os.getenv("AUDIT_WORKER_MAX_STALENESS_SECONDS", "30"),
                "AUDIT_WORKER_MAX_STALENESS_SECONDS",
                maximum=3600,
            ),
            model_job_worker_required=_parse_bool(
                os.getenv(
                    "MODEL_JOB_WORKER_REQUIRED",
                    "true" if environment == "production" else "false",
                ),
                "MODEL_JOB_WORKER_REQUIRED",
            ),
            model_job_worker_max_staleness_seconds=_parse_positive_int(
                os.getenv("MODEL_JOB_WORKER_MAX_STALENESS_SECONDS", "30"),
                "MODEL_JOB_WORKER_MAX_STALENESS_SECONDS",
                maximum=3600,
            ),
            model_job_queue_max_pending=_parse_positive_int(
                os.getenv("MODEL_JOB_QUEUE_MAX_PENDING", "1000"),
                "MODEL_JOB_QUEUE_MAX_PENDING",
                maximum=1_000_000,
            ),
            model_job_lease_seconds=_parse_positive_int(
                os.getenv("MODEL_JOB_LEASE_SECONDS", "180"),
                "MODEL_JOB_LEASE_SECONDS",
                maximum=3600,
            ),
            model_job_max_attempts=_parse_positive_int(
                os.getenv("MODEL_JOB_MAX_ATTEMPTS", "3"),
                "MODEL_JOB_MAX_ATTEMPTS",
                maximum=20,
            ),
        )


def load_app_settings(env_file: Path = PROJECT_ENV_FILE) -> AppSettings:
    load_dotenv(env_file)
    return AppSettings.from_env()


def _parse_bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _parse_positive_int(value: str, name: str, *, maximum: int) -> int:
    parsed = _parse_nonnegative_int(value, name, maximum=maximum)
    if parsed == 0:
        raise ValueError(f"{name} must be greater than zero")
    return parsed


def _parse_nonnegative_int(value: str, name: str, *, maximum: int) -> int:
    try:
        parsed = int(value.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < 0 or parsed > maximum:
        raise ValueError(f"{name} must be between 0 and {maximum}")
    return parsed
