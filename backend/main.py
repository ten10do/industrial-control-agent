import os
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

if __package__:
    from .agent_core import generate_control_plan, optimize_control_plan
    from .errors import AppError
    from .llm_client import DeepSeekLLMClient, LLMClient, LLMClientError
    from .observability import get_request_id, log_workflow_event, set_request_id
    from .schemas import ErrorResponse, GenerateRequest, GenerateResponse, OptimizeRequest, OptimizeResponse
    from .traffic_guard import (
        ModelAPITrafficGuard,
        TrafficGuardLease,
        TrafficGuardSettings,
    )
else:
    from agent_core import generate_control_plan, optimize_control_plan
    from errors import AppError
    from llm_client import DeepSeekLLMClient, LLMClient, LLMClientError
    from observability import get_request_id, log_workflow_event, set_request_id
    from schemas import ErrorResponse, GenerateRequest, GenerateResponse, OptimizeRequest, OptimizeResponse
    from traffic_guard import (
        ModelAPITrafficGuard,
        TrafficGuardLease,
        TrafficGuardSettings,
    )


PROJECT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
bearer_scheme = HTTPBearer(auto_error=False)


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


def _allowed_origins() -> list[str]:
    origins = ["http://localhost:5173"]
    frontend_origin = os.getenv("FRONTEND_ORIGIN", "").strip().rstrip("/")
    if frontend_origin and frontend_origin not in origins:
        origins.append(frontend_origin)
    return origins


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    load_dotenv(PROJECT_ENV_FILE)
    application.state.model_api_guard = ModelAPITrafficGuard(
        TrafficGuardSettings.from_env(),
    )
    yield


def get_model_api_guard(request: Request) -> ModelAPITrafficGuard:
    return request.app.state.model_api_guard


def get_llm_client() -> Callable[[], DeepSeekLLMClient]:
    return DeepSeekLLMClient


@contextmanager
def guarded_llm_client(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
    guard: ModelAPITrafficGuard,
    client_provider: LLMClient | Callable[[], LLMClient],
) -> Iterator[LLMClient]:
    access_token = credentials.credentials if credentials is not None else None
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
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    expose_headers=["Retry-After", "WWW-Authenticate", "X-Request-ID"],
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
def health() -> dict[str, str]:
    return {"status": "ok"}


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
    "/generate",
    response_model=GenerateResponse,
    responses={
        401: {"model": ErrorResponse},
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
    guard: ModelAPITrafficGuard = Depends(get_model_api_guard),
    llm_client_provider=Depends(get_llm_client),
) -> GenerateResponse:
    try:
        with guarded_llm_client(
            http_request,
            credentials,
            guard,
            llm_client_provider,
        ) as llm_client:
            return generate_control_plan(
                request,
                llm_client,
                request_id=get_request_id(),
            )
    except AppError:
        raise
    except LLMClientError as exc:
        raise APIServiceError("控制方案生成失败", str(exc)) from exc
    except Exception as exc:
        raise APIServiceError("控制方案生成失败", "服务内部错误") from exc


@app.post(
    "/optimize",
    response_model=OptimizeResponse,
    responses={
        401: {"model": ErrorResponse},
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
    guard: ModelAPITrafficGuard = Depends(get_model_api_guard),
    llm_client_provider=Depends(get_llm_client),
) -> OptimizeResponse:
    try:
        with guarded_llm_client(
            http_request,
            credentials,
            guard,
            llm_client_provider,
        ) as llm_client:
            return optimize_control_plan(
                request,
                llm_client,
                request_id=get_request_id(),
            )
    except AppError:
        raise
    except LLMClientError as exc:
        raise APIServiceError("控制方案优化失败", str(exc)) from exc
    except Exception as exc:
        raise APIServiceError("控制方案优化失败", "服务内部错误") from exc
