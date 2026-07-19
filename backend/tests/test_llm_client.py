"""
LLM 客户端测试
覆盖：
- _active_providers 逻辑（Key 占位符过滤）
- chat() 多提供商 fallback 逻辑
- 修复 #1: chat_stream 不再引用不存在的 PRIORITY_ORDER
- 修复 #2: DashScope body 格式正确
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.llm_client import LLMClient, LLMProvider, LLMResponse


class TestActiveProviders:
    """_active_providers: 检测已配置 Key 的提供商，过滤占位符"""

    def test_returns_deepseek_when_key_configured(self, monkeypatch):
        """真实 Key 应被识别"""
        from app import config
        monkeypatch.setattr(config.settings, "deepseek_api_key", "sk-real-key")
        monkeypatch.setattr(config.settings, "anthropic_api_key", "")
        monkeypatch.setattr(config.settings, "dashscope_api_key", "")
        monkeypatch.setattr(config.settings, "xunfei_api_key", "")

        client = LLMClient()
        providers = client._active_providers()
        assert LLMProvider.DEEPSEEK in providers

    def test_filters_placeholder_keys(self, monkeypatch):
        """含 'your-' 的占位符 Key 应被过滤"""
        from app import config
        monkeypatch.setattr(config.settings, "deepseek_api_key", "sk-your-key-here")
        monkeypatch.setattr(config.settings, "anthropic_api_key", "your-anthropic-key")
        monkeypatch.setattr(config.settings, "dashscope_api_key", "")
        monkeypatch.setattr(config.settings, "xunfei_api_key", "")

        client = LLMClient()
        providers = client._active_providers()
        # 占位符应被过滤，但因无可用 provider 应回退到 [DEEPSEEK]
        assert providers == [LLMProvider.DEEPSEEK]

    def test_multiple_real_keys_all_returned(self, monkeypatch):
        """多个真实 Key 都应被识别"""
        from app import config
        monkeypatch.setattr(config.settings, "deepseek_api_key", "sk-real-1")
        monkeypatch.setattr(config.settings, "anthropic_api_key", "sk-ant-real-2")
        monkeypatch.setattr(config.settings, "dashscope_api_key", "sk-dashscope-real-3")
        monkeypatch.setattr(config.settings, "xunfei_api_key", "")

        client = LLMClient()
        providers = client._active_providers()
        assert LLMProvider.DEEPSEEK in providers
        assert LLMProvider.ANTHROPIC in providers
        assert LLMProvider.DASHSCOPE in providers


class TestChatFallback:
    """chat() 多提供商 fallback 逻辑"""

    @pytest.mark.asyncio
    async def test_fallback_to_next_provider_on_failure(self, monkeypatch):
        """第一个 provider 失败时应 fallback 到下一个 provider"""
        from app import config
        monkeypatch.setattr(config.settings, "deepseek_api_key", "sk-real")
        monkeypatch.setattr(config.settings, "anthropic_api_key", "sk-ant-real")

        client = LLMClient()
        # mock _active_providers 返回两个 provider，触发 fallback 循环
        monkeypatch.setattr(
            client, "_active_providers",
            lambda: [LLMProvider.DEEPSEEK, LLMProvider.ANTHROPIC]
        )
        # mock _call_provider：第一次抛异常，第二次成功（返回 LLMResponse，匹配真实 _call_provider 契约）
        call_log = []
        async def mock_call(provider, messages, model, temperature, max_tokens):
            call_log.append(provider)
            if len(call_log) == 1:
                raise RuntimeError("模拟第一次失败")
            return LLMResponse(
                content="fallback success",
                provider=provider,
                model="fake",
                tokens_used=10,
                latency_ms=5.0,
            )

        monkeypatch.setattr(client, "_call_provider", mock_call)

        result = await client.chat(
            [{"role": "user", "content": "test"}],
            fallback=True,
        )
        assert result.content == "fallback success"
        assert len(call_log) == 2, "应触发 fallback 第二次调用"
        assert call_log[0] == LLMProvider.DEEPSEEK
        assert call_log[1] == LLMProvider.ANTHROPIC

    @pytest.mark.asyncio
    async def test_no_fallback_when_disabled(self, monkeypatch):
        """fallback=False 且只剩一个 provider 时不重试"""
        from app import config
        monkeypatch.setattr(config.settings, "deepseek_api_key", "sk-real")
        monkeypatch.setattr(config.settings, "anthropic_api_key", "")

        client = LLMClient()
        call_log = []
        async def mock_call(provider, messages, model, temperature, max_tokens):
            call_log.append(provider)
            raise RuntimeError("必失败")

        monkeypatch.setattr(client, "_call_provider", mock_call)

        with pytest.raises(RuntimeError):
            await client.chat(
                [{"role": "user", "content": "test"}],
                fallback=False,
            )
        assert len(call_log) == 1, "fallback=False 时只调用一次"


class TestChatStreamNoPRIORITY_ORDER:
    """修复 #1 回归测试：chat_stream 不再引用不存在的 self.PRIORITY_ORDER"""

    @pytest.mark.asyncio
    async def test_chat_stream_does_not_crash_with_no_provider(self, monkeypatch):
        """chat_stream 应使用 _active_providers() 而非 PRIORITY_ORDER"""
        from app import config
        monkeypatch.setattr(config.settings, "deepseek_api_key", "sk-real")
        monkeypatch.setattr(config.settings, "anthropic_api_key", "")

        client = LLMClient()
        # 验证 client 没有 PRIORITY_ORDER 属性（修复后应不存在）
        assert not hasattr(client, "PRIORITY_ORDER"), "PRIORITY_ORDER 属性不应存在"

        # mock _stream_provider 返回假数据
        async def fake_stream(provider, messages, model, temperature, max_tokens):
            yield "chunk1"
            yield "chunk2"

        monkeypatch.setattr(client, "_stream_provider", fake_stream)

        chunks = []
        async for chunk in client.chat_stream([{"role": "user", "content": "hi"}]):
            chunks.append(chunk)

        assert chunks == ["chunk1", "chunk2"], "chat_stream 应正常 yield"


class TestDashScopeBodyFormat:
    """修复 #2 回归测试：DashScope body 使用 OpenAI 兼容格式"""

    @pytest.mark.asyncio
    async def test_dashscope_uses_openai_compatible_body(self, monkeypatch):
        """_dashscope 构造的 body 应是 OpenAI 格式（messages 在顶层），不是 input/parameters"""
        from app import config
        monkeypatch.setattr(config.settings, "dashscope_api_key", "sk-real")

        client = LLMClient()
        captured_body = {}

        # mock httpx AsyncClient.post
        class FakeResponse:
            def raise_for_status(self): pass
            def json(self): return {"choices": [{"message": {"content": "ok"}}], "model": "qwen", "usage": {"total_tokens": 5}}

        async def fake_post(url, headers=None, json=None):
            captured_body["url"] = url
            captured_body["body"] = json
            return FakeResponse()

        monkeypatch.setattr(client._http, "post", fake_post)

        await client._dashscope(
            messages=[{"role": "user", "content": "hi"}],
            model=None, temperature=0.7, max_tokens=100,
        )

        body = captured_body["body"]
        # OpenAI 兼容格式：messages 在顶层
        assert "messages" in body, "body 应有顶层 messages 字段（OpenAI 格式）"
        assert "input" not in body, "body 不应有 input 字段（旧 DashScope 原生格式）"
        assert "parameters" not in body, "body 不应有 parameters 字段（旧 DashScope 原生格式）"
        assert body["model"] == "qwen-plus"
        assert body["stream"] is False
        assert captured_body["url"].endswith("/compatible-mode/v1/chat/completions")
