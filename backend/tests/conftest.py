"""
pytest 全局 fixtures
- 通过 monkeypatch 把 LLM 客户端替换为 FakeLLMClient，避免真实 API 调用
- 提供临时文件 SQLite 数据库用于接口测试
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

import pytest
import pytest_asyncio

# 让 backend/ 包可被导入
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# 在导入 app 之前设置测试用环境变量，避免读到真实 .env
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key-not-real")


# ============== Fake LLM 客户端 ==============

class FakeLLMResponse:
    def __init__(self, content: str, provider: str = "deepseek", model: str = "fake"):
        self.content = content
        self.provider = type("P", (), {"value": provider})()
        self.model = model
        self.tokens_used = 100
        self.latency_ms = 5.0


class FakeLLMClient:
    """
    假 LLM 客户端：按预设规则返回内容，便于测试编排逻辑。
    - chat() 根据 messages 中关键词返回不同 JSON 或文本
    - chat_stream() 一次性 yield 全部内容
    """

    def __init__(self):
        self.call_count = 0
        self.calls: list[list[dict]] = []

    async def chat(self, messages, *, provider=None, temperature=0.7, max_tokens=4096, fallback=True):
        self.call_count += 1
        self.calls.append(messages)
        text = "\n".join(m.get("content", "") for m in messages)

        # 采集 Agent：返回 profile_update JSON
        if "profile_update" in text or "学情采集" in text or "6维学情画像" in text:
            return FakeLLMResponse(
                '{"profile_update": {"foundation": 72, "weak_points": ["递归", "指针"]}}'
            )
        # 诊断 Agent
        if "诊断" in text and "overall_level" in text:
            return FakeLLMResponse(
                '{"diagnosis": {"overall_level": "一般", "top_weak_areas": [{"name": "递归", "mastery": 30, "reason": "练习不足"}], "strengths": ["循环"], "urgent_actions": ["补递归基础"]}}'
            )
        # 路径 Agent
        if "LearningPathway" in text or "学习路径" in text or "mastery_threshold" in text:
            return FakeLLMResponse(
                '{"title": "递归学习路径", "nodes": [{"id": "n1", "title": "递归基础", "mastery_threshold": 60}]}'
            )
        # 校验 Agent - arbiter（必须在生成判断之前，因 context 含原始资源）
        if "merged_issues_count" in text or "revised_content" in text:
            return FakeLLMResponse(
                '{"merged_issues_count": 2, "priority_fixes": ["修改递归定义", "补充示例"], "quality_assessment": {"content_accuracy": 8, "pedagogical_fit": 7, "student_accessible": 7, "overall": 8}, "revised_content": "# 修正版讲义\\n\\n递归是函数调用自身的过程。", "final_note": "已修正"}'
            )
        # 校验 Agent - 学生评审
        if "难以理解" in text and "issues" in text:
            return FakeLLMResponse(
                '{"issues": [{"type": "too_hard", "description": "递归部分太难", "severity": "medium"}], "overall_rating": 6, "keep_as_is": ["基础概念"]}'
            )
        # 校验 Agent - 教师评审
        if "知识点准确性" in text and "corrections" in text:
            return FakeLLMResponse(
                '{"corrections": [{"issue": "定义模糊", "original": "递归是...", "corrected": "递归是函数调用自身", "reason": "更精确"}], "accuracy_score": 7, "completeness_score": 8, "final_verdict": "revise"}'
            )
        # 生成 Agent（讲义/思维导图等）—— 放在校验之后，避免 arbiter context 含"讲义"被误匹配
        if "讲义" in text or "思维导图" in text or "Mermaid" in text:
            return FakeLLMResponse(f"# 测试讲义：{text[:50]}\n\n这是测试内容。")
        # 兜底：猫老师聊天回复
        return FakeLLMResponse(f"喵~ 这是测试回复。消息：{text[:80]}")

    async def chat_stream(self, messages, **kwargs):
        resp = await self.chat(messages, **kwargs)
        yield resp.content

    async def close(self):
        pass


@pytest.fixture
def fake_llm(monkeypatch):
    """
    替换全局 LLM 客户端为 FakeLLMClient。
    关键：BaseAgent 在 __init__ 时已调用 get_llm_client() 并存到 self.llm，
    所以除了替换模块级 get_llm_client，还要遍历所有已实例化的 Agent 实例替换 .llm。
    """
    fake = FakeLLMClient()
    from app.services import llm_client as lc
    monkeypatch.setattr(lc, "_llm_client", fake)
    monkeypatch.setattr(lc, "get_llm_client", lambda: fake)

    # 遍历已实例化的 Agent，替换它们的 .llm 属性
    from app.agents.base import BaseAgent
    import gc
    replaced = 0
    for obj in gc.get_objects():
        if isinstance(obj, BaseAgent):
            obj.llm = fake
            replaced += 1
    return fake


# ============== 临时文件数据库 fixture ==============

@pytest_asyncio.fixture
async def temp_db(monkeypatch):
    """
    用 monkeypatch 替换 db.base 模块级 engine，使用临时文件 SQLite。
    每个测试函数独立一个临时文件，测试结束自动删除。
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False, prefix="test_")
    tmp.close()
    db_url = f"sqlite+aiosqlite:///{tmp.name}"

    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    test_engine = create_async_engine(db_url, connect_args={"check_same_thread": False})
    test_factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    from app.db import base
    # 保存原始值
    orig_engine = base.engine
    orig_factory = base.async_session_factory
    # 替换为测试 engine
    base.engine = test_engine
    base.async_session_factory = test_factory
    # 同时替换 get_db 函数使用测试 factory
    async def test_get_db():
        async with test_factory() as session:
            try:
                yield session
            finally:
                await session.close()
    orig_get_db = base.get_db
    base.get_db = test_get_db

    # 初始化表结构
    await base.init_db()

    yield test_get_db

    # 清理
    await test_engine.dispose()
    base.engine = orig_engine
    base.async_session_factory = orig_factory
    base.get_db = orig_get_db
    try:
        os.unlink(tmp.name)
    except OSError:
        pass


@pytest_asyncio.fixture
async def db_session(temp_db):
    """从 temp_db 获取一个 session"""
    async for session in temp_db():
        yield session


# ============== 事件循环 ==============

@pytest.fixture
def event_loop():
    """统一事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
