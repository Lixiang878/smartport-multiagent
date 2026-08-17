"""LLM 客户端：OpenAI / GLM 兼容的 chat/completions 接口。

设计原则：
- 仅使用标准库 urllib（零额外依赖）；
- API Key 缺失或调用失败时返回 None，调用方自动降级规则引擎，
  确保无密钥环境系统 100% 可运行。

配置来源（优先级：参数 > 环境变量 > 默认值）：
- SMARTPORT_LLM_BASE_URL：兼容接口地址（默认 GLM 开放平台）
- SMARTPORT_LLM_API_KEY：API 密钥（亦可复用 OPENAI_API_KEY）
- SMARTPORT_LLM_MODEL：模型名（默认 glm-4-flash）
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger("smartport.llm")

DEFAULT_BASE_URL = "https://api.open.bigmodel.cn/api/paas/v4"
DEFAULT_MODEL = "glm-4-flash"


class LLMClient:
    """轻量 OpenAI 兼容 Chat 客户端。"""

    def __init__(
        self,
        api_base: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.api_base = (
            api_base
            or os.environ.get("SMARTPORT_LLM_BASE_URL")
            or DEFAULT_BASE_URL
        ).rstrip("/")
        self.api_key = (
            api_key
            or os.environ.get("SMARTPORT_LLM_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        self.model = model or os.environ.get("SMARTPORT_LLM_MODEL") or DEFAULT_MODEL
        self.timeout = timeout

    def is_available(self) -> bool:
        """是否具备调用条件（有密钥即视为可用）。"""
        return bool(self.api_key)

    def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> str | None:
        """调用 /chat/completions；任何异常返回 None（调用方降级）。"""
        if not self.is_available():
            return None
        url = f"{self.api_base}/chat/completions"
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except (urllib.error.URLError, KeyError, IndexError, ValueError,
                TimeoutError, OSError) as exc:
            logger.warning("llm call failed, fallback to rules: %s", exc)
            return None


def build_client(config: dict | None = None) -> LLMClient:
    """从配置构建客户端（configs/llm.json 的 llm 段）。"""
    cfg = config or {}
    return LLMClient(
        api_base=cfg.get("api_base"),
        api_key=cfg.get("api_key"),
        model=cfg.get("model"),
        timeout=float(cfg.get("timeout", 20.0)),
    )
