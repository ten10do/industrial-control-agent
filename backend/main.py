import os

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .agent_core import AgentCoreError, generate_control_plan, optimize_control_plan
from .llm_client import DeepSeekLLMClient, LLMClientError
from .schemas import ErrorResponse, GenerateRequest, GenerateResponse, OptimizeRequest, OptimizeResponse


class APIServiceError(RuntimeError):
    def __init__(self, message: str, detail: str | None = None, status_code: int = 502) -> None:
        self.message = message
        self.detail = detail
        self.status_code = status_code
        super().__init__(message)


def _allowed_origins() -> list[str]:
    origins = ["http://localhost:5173"]
    frontend_origin = os.getenv("FRONTEND_ORIGIN", "").strip().rstrip("/")
    if frontend_origin and frontend_origin not in origins:
        origins.append(frontend_origin)
    return origins


def get_llm_client() -> DeepSeekLLMClient:
    load_dotenv()
    return DeepSeekLLMClient()


app = FastAPI(
    title="基于大模型的工业控制方案设计 Agent 系统 API",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.exception_handler(APIServiceError)
async def api_service_error_handler(_: Request, exc: APIServiceError) -> JSONResponse:
    payload = ErrorResponse(message=exc.message, detail=exc.detail)
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump())


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, __: RequestValidationError) -> JSONResponse:
    payload = ErrorResponse(message="请求参数校验失败", detail="请检查必填字段和字段长度。")
    return JSONResponse(status_code=422, content=payload.model_dump())


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
    responses={422: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
)
def generate(
    request: GenerateRequest,
    llm_client: DeepSeekLLMClient = Depends(get_llm_client),
) -> GenerateResponse:
    try:
        return generate_control_plan(request, llm_client)
    except LLMClientError as exc:
        raise APIServiceError("控制方案生成失败", str(exc)) from exc
    except AgentCoreError as exc:
        raise APIServiceError("控制方案生成失败", str(exc)) from exc
    except Exception as exc:
        raise APIServiceError("控制方案生成失败", "服务内部错误") from exc


@app.post(
    "/optimize",
    response_model=OptimizeResponse,
    responses={422: {"model": ErrorResponse}, 502: {"model": ErrorResponse}},
)
def optimize(
    request: OptimizeRequest,
    llm_client: DeepSeekLLMClient = Depends(get_llm_client),
) -> OptimizeResponse:
    try:
        return optimize_control_plan(request, llm_client)
    except LLMClientError as exc:
        raise APIServiceError("控制方案优化失败", str(exc)) from exc
    except AgentCoreError as exc:
        raise APIServiceError("控制方案优化失败", str(exc)) from exc
    except Exception as exc:
        raise APIServiceError("控制方案优化失败", "服务内部错误") from exc
