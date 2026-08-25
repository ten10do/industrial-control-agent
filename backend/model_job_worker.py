import signal
import socket
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass

if __package__:
    from .agent_core import generate_control_plan, optimize_control_plan
    from .errors import AppError
    from .llm_client import LLMClient, LLMClientError, OpenRouterLLMClient
    from .outbox_worker import build_repository
    from .plan_repository import ModelJobRecord, PlanRepository
    from .schemas import GenerateRequest, OptimizeRequest, SafetyGate
    from .settings import AppSettings, load_app_settings
    from .traffic_guard import (
        DatabaseModelAPITrafficGuard,
        ModelAPITrafficGuard,
        RedisModelAPITrafficGuard,
        TrafficGuardSettings,
    )
else:
    from agent_core import generate_control_plan, optimize_control_plan
    from errors import AppError
    from llm_client import LLMClient, LLMClientError, OpenRouterLLMClient
    from outbox_worker import build_repository
    from plan_repository import ModelJobRecord, PlanRepository
    from schemas import GenerateRequest, OptimizeRequest, SafetyGate
    from settings import AppSettings, load_app_settings
    from traffic_guard import (
        DatabaseModelAPITrafficGuard,
        ModelAPITrafficGuard,
        RedisModelAPITrafficGuard,
        TrafficGuardSettings,
    )


@dataclass(frozen=True)
class ModelJobRunResult:
    claimed: bool
    status: str | None
    job_id: str | None


class ModelJobRunner:
    def __init__(
        self,
        repository: PlanRepository,
        settings: AppSettings,
        guard: (
            DatabaseModelAPITrafficGuard
            | ModelAPITrafficGuard
            | RedisModelAPITrafficGuard
        ),
        *,
        client_provider: Callable[[], LLMClient] = OpenRouterLLMClient,
        worker_id: str | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.guard = guard
        self.client_provider = client_provider
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid.uuid4()}"

    def run_once(self) -> ModelJobRunResult:
        self.repository.record_service_heartbeat(
            service_name="model-job",
            instance_id=self.worker_id,
        )
        job = self.repository.claim_model_job(
            worker_id=self.worker_id,
            lease_seconds=self.settings.model_job_lease_seconds,
        )
        if job is None:
            return ModelJobRunResult(claimed=False, status=None, job_id=None)

        stop_heartbeat = threading.Event()
        heartbeat = threading.Thread(
            target=self._maintain_lease,
            args=(job, stop_heartbeat),
            daemon=True,
        )
        heartbeat.start()
        try:
            if self.repository.model_job_cancel_requested(
                job_id=job.id,
                fencing_token=job.fencing_token,
            ):
                current = self.repository.fail_model_job(
                    job_id=job.id,
                    worker_id=self.worker_id,
                    fencing_token=job.fencing_token,
                    error_code="MODEL_JOB_CANCELLED",
                    error_message="Model job was cancelled.",
                    retryable=False,
                )
            else:
                current = self._execute(job)
            return ModelJobRunResult(
                claimed=True,
                status=current.status if current else None,
                job_id=job.id,
            )
        except Exception as exc:
            retryable, retry_after = self._retry_policy(exc)
            code = exc.code if isinstance(exc, AppError) else type(exc).__name__
            message = str(exc) if isinstance(exc, (AppError, LLMClientError)) else "Model job execution failed."
            current = self.repository.fail_model_job(
                job_id=job.id,
                worker_id=self.worker_id,
                fencing_token=job.fencing_token,
                error_code=code,
                error_message=message,
                retryable=retryable,
                retry_after_seconds=retry_after,
            )
            return ModelJobRunResult(
                claimed=True,
                status=current.status if current else None,
                job_id=job.id,
            )
        finally:
            stop_heartbeat.set()
            heartbeat.join(timeout=2)

    def _execute(self, job: ModelJobRecord) -> ModelJobRecord | None:
        token = self.guard.settings.access_token
        lease = self.guard.acquire(job.actor_sub, token)
        client: LLMClient | None = None
        try:
            client = self.client_provider()
            if job.operation == "generate":
                result = generate_control_plan(
                    GenerateRequest.model_validate(job.payload),
                    client,
                    request_id=job.request_id or job.id,
                )
                report_markdown = result.report_markdown
            else:
                result = optimize_control_plan(
                    OptimizeRequest.model_validate(job.payload),
                    client,
                    request_id=job.request_id or job.id,
                )
                if job.parent_plan_id:
                    parent = self.repository.get_plan(job.parent_plan_id)
                    if (
                        parent
                        and parent.review_required
                        and not (
                            result.safety_gate
                            and result.safety_gate.review_required
                        )
                    ):
                        result = result.model_copy(
                            update={
                                "safety_gate": SafetyGate(
                                    status="review_required",
                                    review_required=True,
                                    export_allowed=False,
                                    reasons=[
                                        "派生方案内容已变更，必须作为新版本重新完成安全审批。",
                                    ],
                                ),
                            },
                        )
                report_markdown = result.optimized_report
            return self.repository.complete_model_job(
                job_id=job.id,
                worker_id=self.worker_id,
                fencing_token=job.fencing_token,
                report_markdown=report_markdown,
                response=result.model_dump(mode="json"),
                review_required=bool(
                    result.safety_gate and result.safety_gate.review_required
                ),
            )
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                with suppress(Exception):
                    close()
            lease.release()

    def _maintain_lease(
        self,
        job: ModelJobRecord,
        stop: threading.Event,
    ) -> None:
        interval = max(1.0, min(15.0, self.settings.model_job_lease_seconds / 3))
        while not stop.wait(interval):
            self.repository.record_service_heartbeat(
                service_name="model-job",
                instance_id=self.worker_id,
            )
            if not self.repository.heartbeat_model_job(
                job_id=job.id,
                worker_id=self.worker_id,
                fencing_token=job.fencing_token,
                lease_seconds=self.settings.model_job_lease_seconds,
            ):
                return

    @staticmethod
    def _retry_policy(exc: Exception) -> tuple[bool, int]:
        retry_after = int(getattr(exc, "retry_after", 2))
        if isinstance(exc, LLMClientError):
            return True, retry_after
        if isinstance(exc, AppError):
            return exc.status_code in {429, 502, 503, 504}, retry_after
        return False, retry_after


def build_guard(
    repository: PlanRepository,
) -> (
    DatabaseModelAPITrafficGuard
    | ModelAPITrafficGuard
    | RedisModelAPITrafficGuard
):
    guard_settings = TrafficGuardSettings.from_env()
    guard = (
        RedisModelAPITrafficGuard(guard_settings)
        if guard_settings.redis_url
        else DatabaseModelAPITrafficGuard(guard_settings, repository.engine)
    )
    if isinstance(guard, (DatabaseModelAPITrafficGuard, RedisModelAPITrafficGuard)):
        guard.ping()
    return guard


def main() -> None:
    settings = load_app_settings()
    repository = build_repository(settings)
    guard = build_guard(repository)
    runner = ModelJobRunner(repository, settings, guard)
    running = True

    def stop(*_: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while running:
            result = runner.run_once()
            if not result.claimed:
                time.sleep(2)
    finally:
        repository.close()
        close = getattr(guard, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    main()
