import os
from typing import Optional

from openai import OpenAI


class DeepSeekClient:
    """Small wrapper around the OpenAI-compatible DeepSeek chat API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com",
        model: str = "deepseek-chat",
        temperature: float = 0.3,
    ) -> None:
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("未找到 DEEPSEEK_API_KEY，请在 .env 文件中配置。")

        self.model = model
        self.temperature = temperature
        self.client = OpenAI(api_key=self.api_key, base_url=base_url)

    def chat(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
        )
        return response.choices[0].message.content or ""
