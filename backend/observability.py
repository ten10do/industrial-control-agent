import json
import logging
import time
from contextvars import ContextVar
from contextlib import contextmanager
from typing import Iterator


request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
logger = logging.getLogger("industrial_control_agent")


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
