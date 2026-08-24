import json
import logging
import os
import sys
import time
from contextvars import ContextVar
from contextlib import contextmanager
from typing import Iterator


request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
logger = logging.getLogger("industrial_control_agent")


def configure_logging(level: int = logging.INFO) -> None:
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.propagate = False


def setup_logging(level: str | int | None = None) -> logging.Logger:
    """Backward-compatible logging setup used by scripts and deployments."""
    resolved_level: int
    if isinstance(level, int):
        resolved_level = level
    else:
        level_name = (level or os.getenv("LOG_LEVEL", "INFO")).strip().upper()
        candidate = logging.getLevelNamesMapping().get(level_name)
        resolved_level = candidate if isinstance(candidate, int) else logging.INFO
    configure_logging(resolved_level)
    return logger


def set_request_id(request_id: str) -> None:
    request_id_var.set(request_id)


def get_request_id() -> str | None:
    return request_id_var.get()


def log_workflow_event(
    *,
    workflow_name: str,
    step_name: str,
    status: str,
    duration_ms: float = 0.0,
    retry_count: int = 0,
    error_type: str | None = None,
    request_id: str | None = None,
) -> None:
    payload = {
        "request_id": request_id or get_request_id(),
        "workflow_name": workflow_name,
        "step_name": step_name,
        "status": status,
        "duration_ms": round(duration_ms, 2),
        "retry_count": retry_count,
        "error_type": error_type,
    }
    logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def log_validation_event(
    *,
    rule_id: str,
    category: str,
    status: str,
    severity: str,
    duration_ms: float = 0.0,
    error_type: str | None = None,
    request_id: str | None = None,
) -> None:
    payload = {
        "request_id": request_id or get_request_id(),
        "rule_id": rule_id,
        "category": category,
        "status": status,
        "severity": severity,
        "duration_ms": round(duration_ms, 2),
        "error_type": error_type,
    }
    logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


@contextmanager
def workflow_step(
    workflow_name: str,
    step_name: str,
    *,
    request_id: str | None = None,
    retry_count: int = 0,
) -> Iterator[None]:
    started_at = time.perf_counter()
    try:
        yield
    except Exception as exc:
        duration_ms = (time.perf_counter() - started_at) * 1000
        log_workflow_event(
            workflow_name=workflow_name,
            step_name=step_name,
            status="error",
            duration_ms=duration_ms,
            retry_count=retry_count,
            error_type=type(exc).__name__,
            request_id=request_id,
        )
        raise
    else:
        duration_ms = (time.perf_counter() - started_at) * 1000
        log_workflow_event(
            workflow_name=workflow_name,
            step_name=step_name,
            status="success",
            duration_ms=duration_ms,
            retry_count=retry_count,
            request_id=request_id,
        )
