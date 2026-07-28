import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
_logger: logging.Logger | None = None


def setup_logging(level: str | None = None) -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    _logger = logging.getLogger("industrial_control_agent")
    _logger.setLevel((level or os.getenv("LOG_LEVEL", "INFO")).upper())
    if not _logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                '{"timestamp":"%(asctime)s","logger":"%(name)s","level":"%(levelname)s","message":%(message)s}',
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
        _logger.addHandler(handler)
    return _logger


def set_request_id(request_id: str) -> None:
    request_id_var.set(request_id)


def get_request_id() -> str | None:
    return request_id_var.get()


def _log_event(payload: dict) -> None:
    logger = _logger or setup_logging()
    logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


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
    _log_event({
        "request_id": request_id or get_request_id(),
        "workflow_name": workflow_name,
        "step_name": step_name,
        "status": status,
        "duration_ms": round(duration_ms, 2),
        "retry_count": retry_count,
        "error_type": error_type,
    })


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
    _log_event({
        "request_id": request_id or get_request_id(),
        "rule_id": rule_id,
        "category": category,
        "status": status,
        "severity": severity,
        "duration_ms": round(duration_ms, 2),
        "error_type": error_type,
    })


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
