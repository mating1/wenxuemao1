"""
Agent 基类 —— 所有智能体继承此基类
提供统一的LLM调用、日志、错误处理
"""
import json
from typing import Optional
from loguru import logger
from app.services.llm_client import get_llm_client, LLMProvider


class BaseAgent:
    """多智能体基类"""

    # 子类覆盖
    name: str = "base"
    description: str = ""
    system_prompt: str = ""
    default_provider: LLMProvider = LLMProvider.DEEPSEEK
    temperature: float = 0.7

    def __init__(self):
        self.llm = get_llm_client()

    def _build_messages(
        self,
        user_content: str,
        extra_context: Optional[str] = None,
        system_override: Optional[str] = None,
    ) -> list[dict]:
        """构造消息列表。system_override 不为 None 时覆盖默认 system_prompt（不修改实例状态，并发安全）。"""
        system = system_override if system_override is not None else self.system_prompt
        if extra_context:
            system += f"\n\n## 当前上下文\n{extra_context}"
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]

    async def ask(
        self,
        prompt: str,
        *,
        context: Optional[str] = None,
        provider: Optional[LLMProvider] = None,
        temperature: Optional[float] = None,
        use_claude: bool = False,
        system_override: Optional[str] = None,
    ) -> str:
        """向Agent提问，返回文本响应。use_claude 仅在 Claude Key 可用时生效，否则自动降级。"""
        from app.config import settings
        messages = self._build_messages(prompt, context, system_override=system_override)
        t = temperature if temperature is not None else self.temperature

        # 检查 Key 是否真实（排除占位符）
        _has_claude = bool(settings.anthropic_api_key) and "your-" not in settings.anthropic_api_key
        if use_claude and not _has_claude:
            logger.info(f"[Agent:{self.name}] Claude Key 未配置或为占位符，降级到 {self.default_provider.value}")
            use_claude = False
        p = LLMProvider.ANTHROPIC if use_claude else (provider or self.default_provider)

        try:
            response = await self.llm.chat(messages, provider=p, temperature=t)
            logger.info(f"[Agent:{self.name}] 响应 {len(response.content)} 字符, "
                        f"提供商={response.provider.value}, 延迟={response.latency_ms:.0f}ms")
            return response.content
        except Exception:
            logger.exception(f"[Agent:{self.name}] LLM调用失败 ({p.value}), 尝试降级...")
            # 如果指定提供商失败，尝试用默认提供商兜底
            if p != self.default_provider:
                try:
                    response = await self.llm.chat(messages, provider=self.default_provider, temperature=t)
                    logger.info(f"[Agent:{self.name}] 降级到 {self.default_provider.value} 成功")
                    return response.content
                except Exception:
                    logger.exception(f"[Agent:{self.name}] 降级也失败")
            raise

    async def ask_json(
        self,
        prompt: str,
        *,
        context: Optional[str] = None,
        provider: Optional[LLMProvider] = None,
        temperature: Optional[float] = None,
        use_claude: bool = False,
        system_override: Optional[str] = None,
    ) -> dict:
        """向Agent提问，返回解析后的JSON"""
        if "json" not in prompt.lower():
            enhanced = (
                f"{prompt}\n\n"
                f"请严格按照JSON格式输出，不要包含任何markdown代码块标记。"
                f"输出必须是有效的JSON对象。"
            )
        else:
            enhanced = prompt

        text = await self.ask(
            enhanced,
            context=context,
            provider=provider,
            temperature=temperature,
            use_claude=use_claude,
            system_override=system_override,
        )
        return self._parse_json(text)

    def _parse_json(self, text: str) -> dict:
        """智能解析LLM返回的JSON"""
        text = text.strip()
        # 去掉可能的 markdown 代码块
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:]) if len(lines) > 1 else text
            if text.endswith("```"):
                text = text[:-3]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试提取第一个 { } 之间的内容
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
            logger.warning(f"[Agent:{self.name}] JSON解析失败，返回原始文本")
            return {"raw": text, "parse_error": True}
