import json
import os
from typing import Optional, Protocol

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    OpenAIError,
    RateLimitError,
)


class LLMClient(Protocol):
    def chat(self, prompt: str, system_prompt: Optional[str] = None) -> str: ...


class LLMClientError(RuntimeError):
    """Sanitized model-service error suitable for the API layer."""


class DeepSeekLLMClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        temperature: float = 0.2,
        timeout: float = 90.0,
    ) -> None:
        resolved_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not resolved_key:
            raise LLMClientError("模型服务未配置")

        self.model = model
        self.temperature = temperature
        self.client = OpenAI(api_key=resolved_key, base_url=base_url, timeout=timeout)

    def chat(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
            )
        except AuthenticationError as exc:
            raise LLMClientError("模型服务认证失败") from exc
        except APITimeoutError as exc:
            raise LLMClientError("模型服务请求超时") from exc
        except APIConnectionError as exc:
            raise LLMClientError("无法连接模型服务") from exc
        except RateLimitError as exc:
            raise LLMClientError("模型服务请求过于频繁") from exc
        except (APIError, OpenAIError) as exc:
            raise LLMClientError("模型服务调用失败") from exc
        except Exception as exc:
            raise LLMClientError("模型服务调用失败") from exc

        content = response.choices[0].message.content or ""
        if not content.strip():
            raise LLMClientError("模型服务返回内容为空")
        return content


class FakeLLMClient:
    """Deterministic local client used by tests; it never performs network I/O."""

    def chat(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        if "TASK:OPTIMIZE_CONTROL_PLAN" in prompt:
            return json.dumps(
                {
                    "optimized_report": "# 优化后的控制方案\n\n已补充故障保护和调试步骤。",
                    "change_summary": "补充传感器异常保护、报警逻辑和调试检查项。",
                },
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "requirement_analysis": "系统根据输入信号控制执行设备，并覆盖正常和异常工况。",
                "io_table": [
                    {
                        "address": "I0.0",
                        "signal_name": "启动信号",
                        "signal_type": "DI",
                        "device": "启动按钮",
                        "description": "请求系统启动",
                    },
                    {
                        "address": "Q0.0",
                        "signal_name": "设备运行输出",
                        "signal_type": "DO",
                        "device": "执行设备",
                        "description": "驱动主执行设备",
                    },
                ],
                "control_logic": "满足启动和安全条件时置位运行输出，停止条件有效时复位。",
                "safety_design": "急停、故障或信号异常时立即停止输出并保持报警。",
                "ladder_idea": "按输入处理、启停保持、安全联锁、输出和报警划分梯形图网络。",
                "report_markdown": "# 工业控制方案\n\n## 控制说明\n\n系统按控制要求执行。",
            },
            ensure_ascii=False,
        )
