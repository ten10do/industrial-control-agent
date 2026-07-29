import json
import signal
import socket
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass

if __package__:
    from .plan_repository import OutboxRecord, PlanRepository
    from .settings import AppSettings, load_app_settings
else:
    from plan_repository import OutboxRecord, PlanRepository
    from settings import AppSettings, load_app_settings


@dataclass(frozen=True)
class DispatchResult:
    published: int
    failed: int


class AuditOutboxDispatcher:
    def __init__(
        self,
        repository: PlanRepository,
        settings: AppSettings,
        *,
        worker_id: str | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid.uuid4()}"

    def run_once(self, *, batch_size: int = 50) -> DispatchResult:
        if not self.settings.audit_sink_url:
            return DispatchResult(published=0, failed=0)
        self.repository.record_worker_heartbeat(worker_id=self.worker_id)
        self.repository.purge_operational_records()
        records = self.repository.claim_outbox_events(
            worker_id=self.worker_id,
            limit=batch_size,
            lock_seconds=max(60, batch_size * 12),
        )
        published = 0
        failed = 0
        for record in records:
            self.repository.record_worker_heartbeat(worker_id=self.worker_id)
            try:
                self._deliver(record)
                if self.repository.mark_outbox_published(
                    record.id,
                    worker_id=self.worker_id,
                ):
                    published += 1
            except Exception as exc:
                failed += 1
                retry_after = min(3600, 2 ** min(record.attempts, 11))
                self.repository.mark_outbox_failed(
                    record.id,
                    worker_id=self.worker_id,
                    error=f"{type(exc).__name__}: {exc}",
                    retry_after_seconds=retry_after,
                )
        return DispatchResult(published=published, failed=failed)

    def _deliver(self, record: OutboxRecord) -> None:
        body = json.dumps(
            record.payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": record.audit_event_id,
            "X-Audit-Event-ID": record.audit_event_id,
            "X-Audit-Event-Hash": str(record.payload["event_hash"]),
        }
        if self.settings.audit_sink_token:
            headers["Authorization"] = f"Bearer {self.settings.audit_sink_token}"
        request = urllib.request.Request(
            self.settings.audit_sink_url,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.status < 200 or response.status >= 300:
                    raise RuntimeError(f"Audit sink returned HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Audit sink returned HTTP {exc.code}") from exc


def build_repository(settings: AppSettings) -> PlanRepository:
    repository = PlanRepository(
        settings.database_url,
        auto_migrate=settings.database_auto_migrate,
        audit_signing_keys=settings.audit_signing_keys,
        audit_active_key_id=settings.audit_active_key_id,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        sslmode=settings.database_sslmode,
        connect_timeout_seconds=settings.database_connect_timeout_seconds,
    )
    repository.initialize()
    return repository


def main() -> None:
    settings = load_app_settings()
    if settings.audit_sink_required and not settings.audit_sink_url:
        raise RuntimeError("AUDIT_SINK_URL is required")
    repository = build_repository(settings)
    dispatcher = AuditOutboxDispatcher(repository, settings)
    running = True

    def stop(*_: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        while running:
            result = dispatcher.run_once()
            if result.published == 0 and result.failed == 0:
                time.sleep(2)
    finally:
        repository.close()


if __name__ == "__main__":
    main()
