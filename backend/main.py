import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

if __package__:
    from .agent_core import generate_control_plan, optimize_control_plan
    from .auth import AuthPrincipal, AuthSettings, TokenVerifier
    from .errors import (
        AppError,
        AuthorizationDeniedError,
        IdempotencyConflictError,
        ModelJobNotFoundError,
        PlanNotFoundError,
        PlanReviewRequiredError,
        PlanVersionConflictError,
        SelfReviewDeniedError,
        SkillExecutionError,
    )
    from .llm_client import (
        OPENROUTER_MODEL_ID,
        LLMClient,
        LLMClientError,
        OpenRouterLLMClient,
    )
    from .observability import configure_logging, get_request_id, log_workflow_event, set_request_id
    from .plan_repository import (
        AuditRecord,
        ModelJobRecord,
        PlanRecord,
        PlanRepository,
        content_hash,
        request_fingerprint,
    )
    from .schemas import (
        AuditEventResponse,
        AuditLogResponse,
        CurrentUserResponse,
        ErrorResponse,
        GenerateRequest,
        GenerateResponse,
        ModelJobListResponse,
        ModelJobResponse,
        OptimizeRequest,
        OptimizeResponse,
        PlanListResponse,
        PlanResponse,
        PlanSummaryResponse,
        ReadinessResponse,
        ReviewRequest,
        ReviewResponse,
        SafetyGate,
        ValidateRequest,
        ValidateResponse,
    )
    from .settings import load_app_settings
    from .traffic_guard import (
        ModelAPITrafficGuard,
        RedisModelAPITrafficGuard,
        TrafficGuardLease,
        TrafficGuardSettings,
    )
    from .validation import ValidationContext, build_default_engine
else:
    from agent_core import generate_control_plan, optimize_control_plan
    from auth import AuthPrincipal, AuthSettings, TokenVerifier
    from errors import (
        AppError,
        AuthorizationDeniedError,
        IdempotencyConflictError,
        ModelJobNotFoundError,
        PlanNotFoundError,
        PlanReviewRequiredError,
        PlanVersionConflictError,
        SelfReviewDeniedError,
        SkillExecutionError,
    )
    from llm_client import (
        OPENROUTER_MODEL_ID,
        LLMClient,
        LLMClientError,
        OpenRouterLLMClient,
    )
    from observability import configure_logging, get_request_id, log_workflow_event, set_request_id
    from plan_repository import (
        AuditRecord,
        ModelJobRecord,
        PlanRecord,
        PlanRepository,
        content_hash,
        request_fingerprint,
    )
    from schemas import (
        AuditEventResponse,
        AuditLogResponse,
        CurrentUserResponse,
        ErrorResponse,
        GenerateRequest,
        GenerateResponse,
        ModelJobListResponse,
        ModelJobResponse,
        OptimizeRequest,
        OptimizeResponse,
        PlanListResponse,
        PlanResponse,
        PlanSummaryResponse,
        ReadinessResponse,
        ReviewRequest,
        ReviewResponse,
        SafetyGate,
        ValidateRequest,
        ValidateResponse,
    )
    from settings import load_app_settings
    from traffic_guard import (
        ModelAPITrafficGuard,
        RedisModelAPITrafficGuard,
        TrafficGuardLease,
        TrafficGuardSettings,
    )
    from validation import ValidationContext, build_default_engine


bearer_scheme = HTTPBearer(auto_error=False)
settings = load_app_settings()
auth_settings = AuthSettings.from_env()


class APIServiceError(RuntimeError):
    def __init__(self, message: str, detail: str | None = None, status_code: int = 502) -> None:
        self.message = message
        self.detail = detail
        self.status_code = status_code
        super().__init__(message)


def _error_payload(code: str, message: str, detail: str | None = None) -> dict[str, str | None]:
    return ErrorResponse(
        code=code,
        message=message,
        detail=detail,
        request_id=get_request_id(),
    ).model_dump()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level)
    plan_repository = PlanRepository(
        settings.database_url,
        auto_migrate=settings.database_auto_migrate,
        audit_signing_keys=settings.audit_signing_keys,
        audit_active_key_id=settings.audit_active_key_id,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        sslmode=settings.database_sslmode,
        connect_timeout_seconds=settings.database_connect_timeout_seconds,
    )
    plan_repository.initialize()
    guard_settings = TrafficGuardSettings.from_env()
    if auth_settings.mode != "disabled" and guard_settings.auth_required:
        raise ValueError(
            "MODEL_API_AUTH_REQUIRED cannot be combined with OIDC user authentication",
        )
    guard = (
        RedisModelAPITrafficGuard(guard_settings)
        if guard_settings.redis_url
        else ModelAPITrafficGuard(guard_settings)
    )
    if isinstance(guard, RedisModelAPITrafficGuard):
        guard.ping()
    application.state.model_api_guard = guard
    application.state.plan_repository = plan_repository
    application.state.token_verifier = TokenVerifier(auth_settings)
    try:
        yield
    finally:
        plan_repository.close()
        close = getattr(guard, "close", None)
        if callable(close):
            close()


def get_model_api_guard(
    request: Request,
) -> ModelAPITrafficGuard | RedisModelAPITrafficGuard:
    return request.app.state.model_api_guard


def get_plan_repository(request: Request) -> PlanRepository:
    return request.app.state.plan_repository


def get_token_verifier(request: Request) -> TokenVerifier:
    return request.app.state.token_verifier


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    verifier: TokenVerifier = Depends(get_token_verifier),
) -> AuthPrincipal:
    token = credentials.credentials if credentials is not None else None
    return verifier.verify(token)


def require_roles(*allowed_roles: str):
    allowed = frozenset(allowed_roles)

    def dependency(
        principal: AuthPrincipal = Depends(get_current_principal),
    ) -> AuthPrincipal:
        if not principal.has_any_role(allowed):
            raise AuthorizationDeniedError()
        return principal

    return dependency


def get_llm_client() -> Callable[[], OpenRouterLLMClient]:
    return OpenRouterLLMClient


def _release_idempotency_safely(
    repository: PlanRepository,
    *,
    actor_sub: str,
    operation: str,
    idempotency_key: str | None,
    request_hash: str,
) -> None:
    try:
        repository.release_idempotency(
            actor_sub=actor_sub,
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
    except Exception as exc:
        try:
            log_workflow_event(
                request_id=get_request_id(),
                workflow_name="idempotency",
                step_name="release",
                status="error",
                error_type=type(exc).__name__,
            )
        except Exception:
            pass


@contextmanager
def guarded_llm_client(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
    guard: ModelAPITrafficGuard | RedisModelAPITrafficGuard,
    client_provider: LLMClient | Callable[[], LLMClient],
) -> Iterator[LLMClient]:
    access_token = (
        credentials.credentials
        if auth_settings.mode == "disabled" and credentials is not None
        else None
    )
    client_id = request.client.host if request.client is not None else "unknown"
    lease: TrafficGuardLease = guard.acquire(client_id, access_token)
    client: LLMClient | None = None
    try:
        client = client_provider() if callable(client_provider) else client_provider
        yield client
    finally:
        try:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        except Exception as exc:
            try:
                log_workflow_event(
                    request_id=get_request_id(),
                    workflow_name="llm_client",
                    step_name="close",
                    status="error",
                    error_type=type(exc).__name__,
                )
            except Exception:
                pass
        finally:
            lease.release()


app = FastAPI(
    title="基于大模型的工业控制方案设计 Agent 系统 API",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "Idempotency-Key",
        "X-Request-ID",
    ],
    expose_headers=["Location", "Retry-After", "WWW-Authenticate", "X-Request-ID"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    set_request_id(request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    headers = {
        **exc.headers,
        "X-Request-ID": get_request_id() or "",
    }
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(exc.code, exc.message, exc.detail),
        headers=headers,
    )


@app.exception_handler(APIServiceError)
async def api_service_error_handler(_: Request, exc: APIServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload("API_SERVICE_ERROR", exc.message, exc.detail),
        headers={"X-Request-ID": get_request_id() or ""},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, __: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_error_payload(
            "VALIDATION_ERROR",
            "Request validation failed",
            "Check required fields and field lengths.",
        ),
        headers={"X-Request-ID": get_request_id() or ""},
    )

@app.get("/health")
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "version": app.version,
        "provider": "OpenRouter",
        "model": OPENROUTER_MODEL_ID,
        "model_configured": bool(os.getenv("OPENROUTER_API_KEY", "").strip()),
    }


@app.post(
    "/validate",
    response_model=ValidateResponse,
    responses={422: {"model": ErrorResponse}},
)
def validate_plan(request: ValidateRequest) -> ValidateResponse:
    """Validate an existing control plan without calling the model."""
    scenario = request.scenario_text or " ".join(
        text
        for text in (
            request.control_object,
            request.input_devices,
            request.output_devices,
            request.control_requirements,
        )
        if text
    )
    context = ValidationContext(
        source="validate",
        request_id=get_request_id(),
        scenario_text=scenario,
        plan_text=request.plan_text,
        structured_io_available=False,
        control_object=request.control_object,
        input_devices=request.input_devices,
        output_devices=request.output_devices,
        control_requirements=request.control_requirements,
        report_text=request.plan_text,
    )
    report = build_default_engine().validate(context)
    return ValidateResponse(validation_report=report)


@app.get(
    "/auth/me",
    response_model=CurrentUserResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def current_user(
    principal: AuthPrincipal = Depends(
        require_roles("designer", "reviewer", "admin"),
    ),
) -> CurrentUserResponse:
    return CurrentUserResponse(
        subject=principal.subject,
        display_name=principal.display_name,
        roles=sorted(principal.roles),
    )


@app.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse}},
)
def ready(request: Request):
    checks = {
        "model_configuration": "ok" if os.getenv("OPENROUTER_API_KEY", "").strip() else "error",
        "traffic_guard": "ok" if hasattr(request.app.state, "model_api_guard") else "error",
        "validation_engine": "ok",
        "plan_storage": "ok",
        "database_schema": "ok",
        "audit_chain": "ok",
        "audit_outbox": "ok",
        "audit_delivery": "ok",
        "model_job_queue": "ok",
        "model_job_worker": "ok",
        "identity_configuration": "ok",
    }
    try:
        build_default_engine()
    except Exception:
        checks["validation_engine"] = "error"
    try:
        repository = get_plan_repository(request)
        repository.health_check()
    except Exception:
        checks["plan_storage"] = "error"
        checks["database_schema"] = "error"
        checks["audit_chain"] = "error"
        checks["audit_outbox"] = "error"
        checks["audit_delivery"] = "error"
        checks["model_job_queue"] = "error"
        checks["model_job_worker"] = "error"
    else:
        if not repository.verify_audit_chain_head():
            checks["audit_chain"] = "error"
        if repository.pending_outbox_count() > settings.audit_outbox_max_pending:
            checks["audit_outbox"] = "error"
        if settings.audit_sink_required and not repository.audit_worker_is_healthy(
            max_staleness_seconds=settings.audit_worker_max_staleness_seconds,
        ):
            checks["audit_delivery"] = "error"
        if repository.pending_model_job_count() > settings.model_job_queue_max_pending:
            checks["model_job_queue"] = "error"
        if settings.model_job_worker_required and not repository.service_is_healthy(
            service_name="model-job",
            max_staleness_seconds=settings.model_job_worker_max_staleness_seconds,
        ):
            checks["model_job_worker"] = "error"
    status = "ready" if all(value == "ok" for value in checks.values()) else "not_ready"
    return JSONResponse(
        status_code=200 if status == "ready" else 503,
        content={"status": status, "checks": checks},
    )


@app.get("/examples")
def examples() -> dict[str, list[dict[str, str]]]:
    return {
        "examples": [
            {
                "name": "水塔水位控制系统",
                "control_object": "水塔及补水泵",
                "input_devices": "高液位传感器、低液位传感器、启动按钮、停止按钮",
                "output_devices": "补水泵、运行指示灯、故障报警灯",
                "control_requirements": "低液位启动补水泵，高液位停止补水泵，传感器异常时报警。",
            },
            {
                "name": "自动门控制系统",
                "control_object": "自动平移门",
                "input_devices": "人体检测传感器、开门限位、关门限位、防夹传感器",
                "output_devices": "开门电机、关门电机、状态指示灯、报警器",
                "control_requirements": "检测到人员后开门，延时后关门，防夹信号有效时立即停止关门并重新开门。",
            },
            {
                "name": "电机正反转控制系统",
                "control_object": "三相异步电机",
                "input_devices": "正转按钮、反转按钮、停止按钮、急停按钮、热继电器",
                "output_devices": "正转接触器、反转接触器、运行指示灯、故障报警灯",
                "control_requirements": "实现电机正反转控制和电气互锁，切换方向前必须停止，急停或过载时立即停机。",
            },
            {
                "name": "传送带分拣控制系统",
                "control_object": "传送带及分拣机构",
                "input_devices": "启动按钮、停止按钮、物料检测传感器、分类传感器、急停按钮",
                "output_devices": "传送带电机、分拣气缸、运行指示灯、报警灯",
                "control_requirements": "检测物料后运行传送带，根据分类信号驱动分拣气缸，急停或堵料时停止系统并报警。",
            },
        ]
    }


@app.post(
    "/jobs/generate",
    response_model=ModelJobResponse,
    status_code=202,
    responses={
        401: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def enqueue_generate_job(
    request: GenerateRequest,
    http_response: Response,
    principal: AuthPrincipal = Depends(require_roles("designer", "admin")),
    plan_repository: PlanRepository = Depends(get_plan_repository),
    idempotency_key: str | None = Header(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
) -> ModelJobResponse:
    operation = "model-job.generate"
    payload = request.model_dump(mode="json")
    request_hash = request_fingerprint(payload)
    claim = plan_repository.claim_idempotency(
        actor_sub=principal.subject,
        operation=operation,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.status == "replay":
        replayed = plan_repository.get_model_job(claim.resource_id or "")
        if replayed is None:
            raise IdempotencyConflictError()
        _set_model_job_headers(http_response, replayed.id)
        return _model_job_response(replayed)
    completed = False
    try:
        job = plan_repository.enqueue_model_job(
            operation="generate",
            payload=payload,
            actor_sub=principal.subject,
            actor_name=principal.display_name,
            request_id=get_request_id(),
            request_hash=request_hash,
            max_attempts=settings.model_job_max_attempts,
            max_pending=settings.model_job_queue_max_pending,
            idempotency_operation=operation,
            idempotency_key=idempotency_key,
        )
        completed = True
        _set_model_job_headers(http_response, job.id)
        return _model_job_response(job)
    finally:
        if not completed:
            _release_idempotency_safely(
                plan_repository,
                actor_sub=principal.subject,
                operation=operation,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )


@app.post(
    "/jobs/optimize",
    response_model=ModelJobResponse,
    status_code=202,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def enqueue_optimize_job(
    request: OptimizeRequest,
    http_response: Response,
    principal: AuthPrincipal = Depends(require_roles("designer", "admin")),
    plan_repository: PlanRepository = Depends(get_plan_repository),
    idempotency_key: str | None = Header(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
) -> ModelJobResponse:
    parent_plan = _validated_parent_plan(request, plan_repository, principal)
    operation = "model-job.optimize"
    payload = request.model_dump(mode="json")
    request_hash = request_fingerprint(payload)
    claim = plan_repository.claim_idempotency(
        actor_sub=principal.subject,
        operation=operation,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.status == "replay":
        replayed = plan_repository.get_model_job(claim.resource_id or "")
        if replayed is None:
            raise IdempotencyConflictError()
        _set_model_job_headers(http_response, replayed.id)
        return _model_job_response(replayed)
    completed = False
    try:
        job = plan_repository.enqueue_model_job(
            operation="optimize",
            payload=payload,
            actor_sub=principal.subject,
            actor_name=principal.display_name,
            request_id=get_request_id(),
            request_hash=request_hash,
            max_attempts=settings.model_job_max_attempts,
            max_pending=settings.model_job_queue_max_pending,
            parent_plan_id=parent_plan.id if parent_plan else None,
            idempotency_operation=operation,
            idempotency_key=idempotency_key,
        )
        completed = True
        _set_model_job_headers(http_response, job.id)
        return _model_job_response(job)
    finally:
        if not completed:
            _release_idempotency_safely(
                plan_repository,
                actor_sub=principal.subject,
                operation=operation,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )


@app.get(
    "/jobs",
    response_model=ModelJobListResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def list_model_jobs(
    limit: int = Query(default=100, ge=1, le=500),
    principal: AuthPrincipal = Depends(require_roles("designer", "admin")),
    plan_repository: PlanRepository = Depends(get_plan_repository),
) -> ModelJobListResponse:
    actor_sub = None if principal.has_any_role({"admin"}) else principal.subject
    return ModelJobListResponse(
        jobs=[
            _model_job_response(job)
            for job in plan_repository.list_model_jobs(
                actor_sub=actor_sub,
                limit=limit,
            )
        ],
    )


@app.get(
    "/jobs/{job_id}",
    response_model=ModelJobResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_model_job(
    job_id: str,
    principal: AuthPrincipal = Depends(require_roles("designer", "admin")),
    plan_repository: PlanRepository = Depends(get_plan_repository),
) -> ModelJobResponse:
    job = _get_model_job_or_raise(job_id, plan_repository)
    _ensure_model_job_access(job, principal)
    return _model_job_response(job)


@app.post(
    "/jobs/{job_id}/cancel",
    response_model=ModelJobResponse,
    status_code=202,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def cancel_model_job(
    job_id: str,
    principal: AuthPrincipal = Depends(require_roles("designer", "admin")),
    plan_repository: PlanRepository = Depends(get_plan_repository),
) -> ModelJobResponse:
    job = _get_model_job_or_raise(job_id, plan_repository)
    _ensure_model_job_access(job, principal)
    cancelled = plan_repository.cancel_model_job(
        job_id=job.id,
        actor_sub=principal.subject,
        actor_name=principal.display_name,
    )
    if cancelled is None:
        raise ModelJobNotFoundError()
    return _model_job_response(cancelled)


@app.post(
    "/generate",
    response_model=GenerateResponse,
    responses={
        401: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def generate(
    request: GenerateRequest,
    http_request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    principal: AuthPrincipal = Depends(require_roles("designer", "admin")),
    guard: ModelAPITrafficGuard | RedisModelAPITrafficGuard = Depends(get_model_api_guard),
    plan_repository: PlanRepository = Depends(get_plan_repository),
    llm_client_provider=Depends(get_llm_client),
    idempotency_key: str | None = Header(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
) -> GenerateResponse:
    operation = "plan.generate"
    request_hash = request_fingerprint(request.model_dump(mode="json"))
    claim = plan_repository.claim_idempotency(
        actor_sub=principal.subject,
        operation=operation,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.status == "replay":
        replayed = plan_repository.get_plan(claim.resource_id or "")
        if replayed is None:
            raise IdempotencyConflictError()
        return _generate_response_from_plan(replayed)
    completed = False
    try:
        with guarded_llm_client(
            http_request,
            credentials,
            guard,
            llm_client_provider,
        ) as llm_client:
            result = generate_control_plan(
                request,
                llm_client,
                request_id=get_request_id(),
            )
        plan = plan_repository.create_plan(
            source="generate",
            report_markdown=result.report_markdown,
            response=result.model_dump(mode="json"),
            review_required=bool(result.safety_gate and result.safety_gate.review_required),
            actor_sub=principal.subject if principal.authenticated else None,
            actor_name=principal.display_name,
            request_id=get_request_id(),
            idempotency_actor=principal.subject,
            idempotency_operation=operation,
            idempotency_key=idempotency_key,
            idempotency_request_hash=request_hash,
        )
        completed = True
        return result.model_copy(
            update={
                "plan_id": plan.id,
                "parent_plan_id": plan.parent_plan_id,
                "content_hash": plan.content_hash,
                "created_at": plan.created_at,
            },
        )
    except SkillExecutionError as exc:
        raise APIServiceError("控制方案生成失败", str(exc)) from exc
    except AppError:
        raise
    except LLMClientError as exc:
        raise APIServiceError("控制方案生成失败", str(exc)) from exc
    except Exception as exc:
        raise APIServiceError("控制方案生成失败", "服务内部错误") from exc
    finally:
        if not completed:
            _release_idempotency_safely(
                plan_repository,
                actor_sub=principal.subject,
                operation=operation,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )


@app.post(
    "/optimize",
    response_model=OptimizeResponse,
    responses={
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def optimize(
    request: OptimizeRequest,
    http_request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    principal: AuthPrincipal = Depends(require_roles("designer", "admin")),
    guard: ModelAPITrafficGuard | RedisModelAPITrafficGuard = Depends(get_model_api_guard),
    plan_repository: PlanRepository = Depends(get_plan_repository),
    llm_client_provider=Depends(get_llm_client),
    idempotency_key: str | None = Header(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
) -> OptimizeResponse:
    operation = "plan.optimize"
    request_hash = request_fingerprint(request.model_dump(mode="json"))
    claim = plan_repository.claim_idempotency(
        actor_sub=principal.subject,
        operation=operation,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.status == "replay":
        replayed = plan_repository.get_plan(claim.resource_id or "")
        if replayed is None:
            raise IdempotencyConflictError()
        return _optimize_response_from_plan(replayed)
    completed = False
    try:
        parent_plan = _validated_parent_plan(request, plan_repository, principal)
        with guarded_llm_client(
            http_request,
            credentials,
            guard,
            llm_client_provider,
        ) as llm_client:
            result = optimize_control_plan(
                request,
                llm_client,
                request_id=get_request_id(),
            )
        if (
            parent_plan
            and parent_plan.review_required
            and not (result.safety_gate and result.safety_gate.review_required)
        ):
            result = result.model_copy(
                update={
                    "safety_gate": SafetyGate(
                        status="review_required",
                        review_required=True,
                        export_allowed=False,
                        reasons=["派生方案内容已变更，必须作为新版本重新完成安全审批。"],
                    ),
                },
            )
        plan = plan_repository.create_plan(
            source="optimize",
            report_markdown=result.optimized_report,
            response=result.model_dump(mode="json"),
            review_required=bool(result.safety_gate and result.safety_gate.review_required),
            parent_plan_id=parent_plan.id if parent_plan else None,
            actor_sub=principal.subject if principal.authenticated else None,
            actor_name=principal.display_name,
            request_id=get_request_id(),
            idempotency_actor=principal.subject,
            idempotency_operation=operation,
            idempotency_key=idempotency_key,
            idempotency_request_hash=request_hash,
        )
        completed = True
        return result.model_copy(
            update={
                "plan_id": plan.id,
                "parent_plan_id": plan.parent_plan_id,
                "content_hash": plan.content_hash,
                "created_at": plan.created_at,
            },
        )
    except SkillExecutionError as exc:
        raise APIServiceError("控制方案优化失败", str(exc)) from exc
    except AppError:
        raise
    except LLMClientError as exc:
        raise APIServiceError("控制方案优化失败", str(exc)) from exc
    except Exception as exc:
        raise APIServiceError("控制方案优化失败", "服务内部错误") from exc
    finally:
        if not completed:
            _release_idempotency_safely(
                plan_repository,
                actor_sub=principal.subject,
                operation=operation,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            )


def _generate_response_from_plan(plan: PlanRecord) -> GenerateResponse:
    return GenerateResponse.model_validate(plan.response).model_copy(
        update={
            "plan_id": plan.id,
            "parent_plan_id": plan.parent_plan_id,
            "content_hash": plan.content_hash,
            "created_at": plan.created_at,
        },
    )


def _optimize_response_from_plan(plan: PlanRecord) -> OptimizeResponse:
    return OptimizeResponse.model_validate(plan.response).model_copy(
        update={
            "plan_id": plan.id,
            "parent_plan_id": plan.parent_plan_id,
            "content_hash": plan.content_hash,
            "created_at": plan.created_at,
        },
    )


def _model_job_response(job: ModelJobRecord) -> ModelJobResponse:
    return ModelJobResponse(
        job_id=job.id,
        operation=job.operation,
        status=job.status,
        progress=job.progress,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        result=job.result,
        error_code=job.error_code,
        error_message=job.error_message,
        plan_id=job.plan_id,
        parent_plan_id=job.parent_plan_id,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        updated_at=job.updated_at,
    )


def _set_model_job_headers(response: Response, job_id: str) -> None:
    response.headers["Location"] = f"/jobs/{job_id}"
    response.headers["Retry-After"] = "1"


def _get_model_job_or_raise(
    job_id: str,
    plan_repository: PlanRepository,
) -> ModelJobRecord:
    job = plan_repository.get_model_job(job_id)
    if job is None:
        raise ModelJobNotFoundError()
    return job


def _ensure_model_job_access(
    job: ModelJobRecord,
    principal: AuthPrincipal,
) -> None:
    if principal.has_any_role({"admin"}) or job.actor_sub == principal.subject:
        return
    raise AuthorizationDeniedError()


def _validated_parent_plan(
    request: OptimizeRequest,
    plan_repository: PlanRepository,
    principal: AuthPrincipal,
) -> PlanRecord | None:
    if request.plan_id is None:
        return None
    plan = plan_repository.get_plan(request.plan_id)
    if plan is None:
        raise PlanNotFoundError()
    _ensure_plan_access(
        plan,
        principal,
        plan_repository,
        denied_action="plan.optimize.denied",
    )
    if content_hash(request.original_report) != plan.content_hash:
        raise PlanVersionConflictError()
    return plan


def _get_plan_or_raise(plan_id: str, plan_repository: PlanRepository) -> PlanRecord:
    plan = plan_repository.get_plan(plan_id)
    if plan is None:
        raise PlanNotFoundError()
    return plan


def _ensure_plan_access(
    plan: PlanRecord,
    principal: AuthPrincipal,
    plan_repository: PlanRepository,
    *,
    denied_action: str,
) -> None:
    if not principal.authenticated:
        return
    if principal.has_any_role({"reviewer", "admin"}):
        return
    if plan.created_by == principal.subject:
        return
    plan_repository.append_audit_event(
        actor_sub=principal.subject,
        actor_name=principal.display_name,
        action=denied_action,
        resource_type="plan",
        resource_id=plan.id,
        plan_hash=plan.content_hash,
        request_id=get_request_id(),
        details={"reason": "object_access_denied"},
    )
    raise AuthorizationDeniedError()


def _audit_response(record: AuditRecord) -> AuditEventResponse:
    return AuditEventResponse(
        event_id=record.id,
        actor_sub=record.actor_sub,
        actor_name=record.actor_name,
        action=record.action,
        resource_type=record.resource_type,
        resource_id=record.resource_id,
        plan_hash=record.plan_hash,
        request_id=record.request_id,
        details=record.details,
        previous_hash=record.previous_hash,
        event_hash=record.event_hash,
        signature_algorithm=record.signature_algorithm,
        signing_key_id=record.signing_key_id,
        created_at=record.created_at,
    )


def _latest_review_payload(plan_repository: PlanRepository, plan: PlanRecord):
    review = plan_repository.latest_review(plan.id)
    if review is None:
        return None
    return {
        "review_id": review.id,
        "decision": review.decision,
        "reviewer_sub": review.reviewer_sub,
        "reviewer": review.reviewer,
        "comment": review.comment,
        "reviewed_at": review.created_at,
    }


@app.get(
    "/plans",
    response_model=PlanListResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def list_plans(
    limit: int = Query(default=100, ge=1, le=500),
    principal: AuthPrincipal = Depends(
        require_roles("designer", "reviewer", "admin"),
    ),
    plan_repository: PlanRepository = Depends(get_plan_repository),
) -> PlanListResponse:
    created_by = (
        principal.subject
        if principal.authenticated
        and not principal.has_any_role({"reviewer", "admin"})
        else None
    )
    plans = plan_repository.list_plans(created_by=created_by, limit=limit)
    summaries = []
    for plan in plans:
        latest_review = plan_repository.latest_review(plan.id)
        summaries.append(
            PlanSummaryResponse(
                plan_id=plan.id,
                parent_plan_id=plan.parent_plan_id,
                source=plan.source,
                content_hash=plan.content_hash,
                review_required=plan.review_required,
                export_allowed=plan_repository.export_allowed(plan),
                created_by=plan.created_by,
                created_by_name=plan.created_by_name,
                latest_decision=latest_review.decision if latest_review else None,
                created_at=plan.created_at,
            ),
        )
    return PlanListResponse(plans=summaries)


@app.get(
    "/plans/{plan_id}",
    response_model=PlanResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_plan(
    plan_id: str,
    principal: AuthPrincipal = Depends(
        require_roles("designer", "reviewer", "admin"),
    ),
    plan_repository: PlanRepository = Depends(get_plan_repository),
) -> PlanResponse:
    plan = _get_plan_or_raise(plan_id, plan_repository)
    _ensure_plan_access(
        plan,
        principal,
        plan_repository,
        denied_action="plan.read.denied",
    )
    return PlanResponse(
        plan_id=plan.id,
        parent_plan_id=plan.parent_plan_id,
        source=plan.source,
        content_hash=plan.content_hash,
        report_markdown=plan.report_markdown,
        response=plan.response,
        review_required=plan.review_required,
        export_allowed=plan_repository.export_allowed(plan),
        created_by=plan.created_by,
        created_by_name=plan.created_by_name,
        latest_review=_latest_review_payload(plan_repository, plan),
        created_at=plan.created_at,
    )


@app.post(
    "/plans/{plan_id}/reviews",
    response_model=ReviewResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def review_plan(
    plan_id: str,
    request: ReviewRequest,
    principal: AuthPrincipal = Depends(require_roles("reviewer", "admin")),
    plan_repository: PlanRepository = Depends(get_plan_repository),
    idempotency_key: str | None = Header(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
) -> ReviewResponse:
    plan = _get_plan_or_raise(plan_id, plan_repository)
    if (
        principal.authenticated
        and plan.created_by is not None
        and plan.created_by == principal.subject
    ):
        plan_repository.append_audit_event(
            actor_sub=principal.subject,
            actor_name=principal.display_name,
            action="plan.review.self_denied",
            resource_type="plan",
            resource_id=plan.id,
            plan_hash=plan.content_hash,
            request_id=get_request_id(),
            details={"decision": request.decision},
        )
        raise SelfReviewDeniedError()
    operation = f"plan.review:{plan.id}"
    request_hash = request_fingerprint(
        {
            "plan_id": plan.id,
            "content_hash": plan.content_hash,
            **request.model_dump(mode="json"),
        },
    )
    claim = plan_repository.claim_idempotency(
        actor_sub=principal.subject,
        operation=operation,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if claim.status == "replay":
        review = plan_repository.get_review(claim.resource_id or "")
        if review is None:
            raise IdempotencyConflictError()
    else:
        completed = False
        try:
            review = plan_repository.create_review(
                plan=plan,
                decision=request.decision,
                reviewer=principal.display_name,
                reviewer_sub=principal.subject if principal.authenticated else None,
                comment=request.comment,
                request_id=get_request_id(),
                idempotency_actor=principal.subject,
                idempotency_operation=operation,
                idempotency_key=idempotency_key,
                idempotency_request_hash=request_hash,
            )
            completed = True
        finally:
            if not completed:
                _release_idempotency_safely(
                    plan_repository,
                    actor_sub=principal.subject,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                )
    return ReviewResponse(
        review_id=review.id,
        plan_id=review.plan_id,
        decision=review.decision,
        reviewer_sub=review.reviewer_sub,
        reviewer=review.reviewer,
        comment=review.comment,
        content_hash=review.content_hash,
        reviewed_at=review.created_at,
        export_allowed=plan_repository.export_allowed(plan),
    )


@app.get(
    "/plans/{plan_id}/export",
    responses={
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def export_plan(
    plan_id: str,
    principal: AuthPrincipal = Depends(
        require_roles("designer", "reviewer", "admin"),
    ),
    plan_repository: PlanRepository = Depends(get_plan_repository),
) -> PlainTextResponse:
    plan = _get_plan_or_raise(plan_id, plan_repository)
    _ensure_plan_access(
        plan,
        principal,
        plan_repository,
        denied_action="plan.export.denied",
    )
    authorized_plan, allowed = plan_repository.authorize_export(
        plan_id=plan.id,
        actor_sub=principal.subject,
        actor_name=principal.display_name,
        request_id=get_request_id(),
    )
    if authorized_plan is None:
        raise PlanNotFoundError()
    if not allowed:
        raise PlanReviewRequiredError()
    return PlainTextResponse(
        authorized_plan.report_markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="control-plan-{authorized_plan.id}.md"'
            ),
            "X-Content-SHA256": authorized_plan.content_hash,
        },
    )


@app.get(
    "/plans/{plan_id}/audit",
    response_model=AuditLogResponse,
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def get_plan_audit(
    plan_id: str,
    principal: AuthPrincipal = Depends(
        require_roles("designer", "reviewer", "admin"),
    ),
    plan_repository: PlanRepository = Depends(get_plan_repository),
) -> AuditLogResponse:
    plan = _get_plan_or_raise(plan_id, plan_repository)
    _ensure_plan_access(
        plan,
        principal,
        plan_repository,
        denied_action="plan.audit.read.denied",
    )
    return AuditLogResponse(
        chain_valid=plan_repository.verify_audit_chain(),
        events=[
            _audit_response(event)
            for event in plan_repository.list_audit_events(resource_id=plan.id)
        ],
    )


@app.get(
    "/audit/events",
    response_model=AuditLogResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_audit_events(
    limit: int = Query(default=100, ge=1, le=500),
    _: AuthPrincipal = Depends(require_roles("admin")),
    plan_repository: PlanRepository = Depends(get_plan_repository),
) -> AuditLogResponse:
    return AuditLogResponse(
        chain_valid=plan_repository.verify_audit_chain(),
        events=[
            _audit_response(event)
            for event in plan_repository.list_audit_events(limit=limit)
        ],
    )
