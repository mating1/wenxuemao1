"""
多LLM提供商统一调用客户端

支持: DeepSeek(主力), Claude(把关), 讯飞星火(门面), 通义千问(备用)
自动按优先级 fallback
"""
import json
import time
from typing import Optional, AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum

import httpx
from loguru import logger

from app.config import settings


class LLMProvider(str, Enum):
    DEEPSEEK = "deepseek"
    ANTHROPIC = "anthropic"
    XUNFEI = "xunfei"
    DASHSCOPE = "dashscope"


@dataclass
class LLMResponse:
    content: str
    provider: LLMProvider
    model: str
    tokens_used: int = 0
    latency_ms: float = 0.0


class LLMClient:
    """多提供商LLM客户端 —— 自动fallback"""

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(120.0))

    def _active_providers(self) -> list[LLMProvider]:
        """返回已配置了 Key 的提供商列表"""
        active = []
        if settings.deepseek_api_key and "your-" not in settings.deepseek_api_key:
            active.append(LLMProvider.DEEPSEEK)
        if settings.anthropic_api_key and "your-" not in settings.anthropic_api_key:
            active.append(LLMProvider.ANTHROPIC)
        if settings.dashscope_api_key and "your-" not in settings.dashscope_api_key:
            active.append(LLMProvider.DASHSCOPE)
        if settings.xunfei_api_key and "your-" not in settings.xunfei_api_key:
            active.append(LLMProvider.XUNFEI)
        return active or [LLMProvider.DEEPSEEK]

    async def close(self):
        await self._http.aclose()

    async def chat(
        self,
        messages: list[dict],
        *,
        provider: Optional[LLMProvider] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        fallback: bool = True,
    ) -> LLMResponse:
        providers = [provider] if provider else self._active_providers()
        if not providers:
            raise RuntimeError("未配置任何 API Key，请在 .env 文件中填写至少一个 API Key")
        last_error = None

        for p in providers:
            try:
                return await self._call_provider(
                    p, messages, model=model, temperature=temperature, max_tokens=max_tokens
                )
            except Exception as e:
                last_error = e
                logger.warning(f"[LLM] {p.value} 调用失败: {e}")
                if not fallback or p == providers[-1]:
                    raise
                continue

        raise RuntimeError(f"所有LLM提供商调用失败: {last_error}")

    async def chat_stream(
        self,
        messages: list[dict],
        *,
        provider: Optional[LLMProvider] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncGenerator[str, None]:
        """流式对话 —— 用于前端打字机效果"""
        providers = [provider] if provider else self._active_providers()
        if not providers:
            raise RuntimeError("未配置任何 API Key，请在 .env 文件中填写至少一个 API Key")
        last_error = None

        for p in providers:
            try:
                async for chunk in self._stream_provider(
                    p, messages, model=model, temperature=temperature, max_tokens=max_tokens
                ):
                    yield chunk
                return
            except Exception as e:
                last_error = e
                logger.warning(f"[LLM Stream] {p.value} 失败: {e}")
                continue

        raise RuntimeError(f"所有LLM流式调用失败: {last_error}")

    # ---- 各提供商实现 ----

    async def _call_provider(
        self, provider: LLMProvider, messages: list[dict],
        model: Optional[str], temperature: float, max_tokens: int
    ) -> LLMResponse:
        t0 = time.perf_counter()
        if provider == LLMProvider.DEEPSEEK:
            result = await self._deepseek(messages, model, temperature, max_tokens)
        elif provider == LLMProvider.ANTHROPIC:
            result = await self._anthropic(messages, model, temperature, max_tokens)
        elif provider == LLMProvider.XUNFEI:
            result = await self._xunfei(messages, model, temperature, max_tokens)
        elif provider == LLMProvider.DASHSCOPE:
            result = await self._dashscope(messages, model, temperature, max_tokens)
        else:
            raise ValueError(f"未知提供商: {provider}")
        return LLMResponse(
            content=result["content"],
            provider=provider,
            model=result.get("model", "unknown"),
            tokens_used=result.get("tokens", 0),
            latency_ms=(time.perf_counter() - t0) * 1000,
        )

    async def _stream_provider(self, provider, messages, model, temperature, max_tokens):
        # 流式实现：不同提供商的SSE解析
        if provider == LLMProvider.DEEPSEEK:
            async for chunk in self._stream_deepseek(messages, model, temperature, max_tokens):
                yield chunk
        elif provider == LLMProvider.ANTHROPIC:
            async for chunk in self._stream_anthropic(messages, model, temperature, max_tokens):
                yield chunk
        elif provider == LLMProvider.DASHSCOPE:
            async for chunk in self._stream_dashscope(messages, model, temperature, max_tokens):
                yield chunk
        elif provider == LLMProvider.XUNFEI:
            # 星火暂不流式，直接返回完整结果
            result = await self._xunfei(messages, model, temperature, max_tokens)
            yield result["content"]

    # ==================== DeepSeek ====================

    async def _deepseek(self, messages, model, temperature, max_tokens) -> dict:
        if not settings.deepseek_api_key:
            raise ValueError("DeepSeek API Key 未配置")

        body = {
            "model": model or "deepseek-chat",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        r = await self._http.post(
            f"{settings.deepseek_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.deepseek_api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        r.raise_for_status()
        data = r.json()
        choice = data["choices"][0]
        return {
            "content": choice["message"]["content"],
            "model": data.get("model", ""),
            "tokens": data.get("usage", {}).get("total_tokens", 0),
        }

    async def _stream_deepseek(self, messages, model, temperature, max_tokens):
        body = {
            "model": model or "deepseek-chat",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        async with self._http.stream(
            "POST",
            f"{settings.deepseek_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.deepseek_api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    chunk = json.loads(line[6:])
                    delta = chunk["choices"][0].get("delta", {})
                    if "content" in delta:
                        yield delta["content"]

    # ==================== Anthropic Claude ====================

    async def _anthropic(self, messages, model, temperature, max_tokens) -> dict:
        if not settings.anthropic_api_key:
            raise ValueError("Anthropic API Key 未配置")

        system_msg = ""
        user_messages = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                user_messages.append({"role": m["role"], "content": m["content"]})

        body = {
            "model": model or "claude-sonnet-4-20250514",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": user_messages,
        }
        if system_msg:
            body["system"] = system_msg

        r = await self._http.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=body,
        )
        r.raise_for_status()
        data = r.json()
        return {
            "content": data["content"][0]["text"],
            "model": data.get("model", ""),
            "tokens": data.get("usage", {}).get("input_tokens", 0)
                      + data.get("usage", {}).get("output_tokens", 0),
        }

    async def _stream_anthropic(self, messages, model, temperature, max_tokens):
        system_msg = ""
        user_messages = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                user_messages.append({"role": m["role"], "content": m["content"]})

        body = {
            "model": model or "claude-sonnet-4-20250514",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": user_messages,
            "stream": True,
        }
        if system_msg:
            body["system"] = system_msg

        async with self._http.stream(
            "POST",
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=body,
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if line.startswith("data: "):
                    event = json.loads(line[6:])
                    if event.get("type") == "content_block_delta":
                        delta = event.get("delta", {})
                        if "text" in delta:
                            yield delta["text"]

    # ==================== 讯飞星火 ====================

    async def _xunfei(self, messages, model, temperature, max_tokens) -> dict:
        if not all([settings.xunfei_app_id, settings.xunfei_api_key, settings.xunfei_api_secret]):
            raise ValueError("讯飞星火 API 未完整配置")

        # 获取鉴权URL
        import hmac
        import hashlib
        import base64
        from urllib.parse import urlencode, urlparse

        host = "spark-api.xf-yun.com"
        path = "/v4.0/chat"
        date_str = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())

        # 构造签名
        signature_origin = f"host: {host}\ndate: {date_str}\nGET {path} HTTP/1.1"
        signature_sha = hmac.new(
            settings.xunfei_api_secret.encode(),
            signature_origin.encode(),
            hashlib.sha256
        ).digest()
        signature_b64 = base64.b64encode(signature_sha).decode()

        authorization_origin = (
            f'api_key="{settings.xunfei_api_key}", '
            f'algorithm="hmac-sha256", '
            f'headers="host date request-line", '
            f'signature="{signature_b64}"'
        )
        authorization_b64 = base64.b64encode(authorization_origin.encode()).decode()

        url = f"https://{host}{path}"
        headers = {
            "Authorization": authorization_b64,
            "Date": date_str,
            "Content-Type": "application/json",
        }

        # 转换消息格式
        xunfei_messages = []
        for m in messages:
            role_map = {"user": "user", "assistant": "assistant", "system": "system"}
            xunfei_messages.append({
                "role": role_map.get(m["role"], "user"),
                "content": m["content"],
            })

        body = {
            "header": {"app_id": settings.xunfei_app_id},
            "parameter": {
                "chat": {
                    "domain": "generalv4.0",
                    "temperature": temperature,
                    "max_tokens": min(max_tokens, 4096),
                }
            },
            "payload": {
                "message": {"text": xunfei_messages}
            },
        }

        r = await self._http.post(url, headers=headers, json=body)
        r.raise_for_status()
        data = r.json()
        content = data["payload"]["choices"]["text"][0]["content"]
        return {
            "content": content,
            "model": "spark-v4.0",
            "tokens": data.get("payload", {}).get("usage", {}).get("text", {}).get("total_tokens", 0),
        }

    # ==================== 通义千问(DashScope) ====================

    async def _dashscope(self, messages, model, temperature, max_tokens) -> dict:
        if not settings.dashscope_api_key:
            raise ValueError("DashScope API Key 未配置")

        # OpenAI 兼容端点，使用标准 OpenAI body 格式
        body = {
            "model": model or "qwen-plus",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        r = await self._http.post(
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.dashscope_api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        r.raise_for_status()
        data = r.json()
        choice = data["choices"][0]
        return {
            "content": choice["message"]["content"],
            "model": data.get("model", ""),
            "tokens": data.get("usage", {}).get("total_tokens", 0),
        }

    async def _stream_dashscope(self, messages, model, temperature, max_tokens):
        # OpenAI 兼容端点流式：stream=true + 标准 SSE 解析
        body = {
            "model": model or "qwen-plus",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        async with self._http.stream(
            "POST",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.dashscope_api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    chunk = json.loads(line[6:])
                    delta = chunk["choices"][0].get("delta", {})
                    if "content" in delta:
                        yield delta["content"]


# 全局单例
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
