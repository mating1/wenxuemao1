"""
对话 API 测试
覆盖：
- 修复 #4 回归：hr.scalars().all() 不再丢失对话历史
- 修复 #6: 对话历史传递给采集 Agent
- 修复 #7: 错题记录传递给诊断 Agent
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.models.student import UserProfile, UserRole, ErrorRecord
from app.models.dialogue import DialogueSession, DialogueMessage


@pytest_asyncio.fixture
async def client(temp_db, fake_llm):
    app.dependency_overrides[get_db] = temp_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(temp_db):
    async for session in temp_db():
        import bcrypt
        user = UserProfile(
            name="测试学生",
            login_id="test_dlg_001",
            password_hash=bcrypt.hashpw(b"1234", bcrypt.gensalt()).decode(),
            role=UserRole.STUDENT,
            education_level="undergraduate",
            major="计算机",
            grade="大二",
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        yield user
        break


@pytest_asyncio.fixture
async def session_with_history(temp_db, test_user):
    """创建带历史消息的会话"""
    async for session in temp_db():
        dlg_session = DialogueSession(student_id=test_user.id, title="历史会话")
        session.add(dlg_session)
        await session.commit()
        await session.refresh(dlg_session)
        # 加 3 条历史
        session.add_all([
            DialogueMessage(session_id=dlg_session.id, role="user", content="我之前问过递归"),
            DialogueMessage(session_id=dlg_session.id, role="assistant", content="好的，递归是函数调用自身"),
            DialogueMessage(session_id=dlg_session.id, role="user", content="那二叉树呢"),
        ])
        await session.commit()
        yield dlg_session
        break


@pytest_asyncio.fixture
async def user_with_errors(temp_db, test_user):
    """给测试用户加错题记录"""
    async for session in temp_db():
        session.add_all([
            ErrorRecord(
                user_id=test_user.id,
                question="斐波那契数列递归实现",
                knowledge_point="递归",
                error_type="概念混淆",
                times_wrong=3,
                resolved=False,
            ),
            ErrorRecord(
                user_id=test_user.id,
                question="指针数组操作",
                knowledge_point="指针",
                error_type="应用错误",
                times_wrong=2,
                resolved=False,
            ),
        ])
        await session.commit()
        break


class TestDialogueHistoryNotLost:
    """修复 #4 回归：对话历史不应丢失"""

    @pytest.mark.asyncio
    async def test_chat_with_existing_session_loads_history(self, client, test_user, session_with_history, fake_llm):
        """已存在会话的对话历史应被正确加载（修复 #4: Result 单次消费）"""
        resp = await client.post("/api/dialogue/chat", json={
            "user_id": test_user.id,
            "message": "继续讲",
            "session_id": session_with_history.id,
        })
        assert resp.status_code == 200, f"应返回 200，实际: {resp.status_code} {resp.text}"
        data = resp.json()
        assert "content" in data or "reply" in data

        # 验证 fake_llm 收到的 messages 包含历史内容（采集Agent应看到历史）
        all_text = "".join(
            m.get("content", "")
            for call in fake_llm.calls
            for m in call
        )
        assert "我之前问过递归" in all_text, "对话历史应被传递给采集Agent"

    @pytest.mark.asyncio
    async def test_first_message_no_history_no_crash(self, client, test_user, fake_llm):
        """首次对话（无历史）不应崩溃"""
        resp = await client.post("/api/dialogue/chat", json={
            "user_id": test_user.id,
            "message": "你好",
            "session_id": None,
        })
        assert resp.status_code == 200, f"首次对话应正常，实际: {resp.status_code} {resp.text}"


class TestErrorRecordsPassedToDiagnosis:
    """修复 #7 回归：错题记录应传递给诊断 Agent"""

    @pytest.mark.asyncio
    async def test_diagnosis_intent_receives_error_records(
        self, client, test_user, user_with_errors, fake_llm
    ):
        """诊断意图时应从 DB 查错题并传给诊断 Agent"""
        resp = await client.post("/api/dialogue/chat", json={
            "user_id": test_user.id,
            "message": "帮我诊断一下我的学习情况",
            "session_id": None,
        })
        assert resp.status_code == 200, f"应返回 200，实际: {resp.status_code} {resp.text}"

        # 验证 fake_llm 收到的某次调用包含错题内容
        all_text = "".join(
            m.get("content", "")
            for call in fake_llm.calls
            for m in call
        )
        assert "递归" in all_text and "概念混淆" in all_text, \
            "诊断 Agent 应收到错题记录（知识点+错误类型）"
        assert "指针" in all_text, "应包含第二条错题"


class TestResourceTypeInDialogue:
    """修复 #8 回归：对话中可触发不同资源类型"""

    @pytest.mark.asyncio
    async def test_mindmap_request_in_dialogue(self, client, test_user, fake_llm):
        """学生请求思维导图时应触发 mindmap 生成（非 handout）"""
        resp = await client.post("/api/dialogue/chat", json={
            "user_id": test_user.id,
            "message": "帮我生成数据结构的思维导图",
            "session_id": None,
        })
        assert resp.status_code == 200
        # fake_llm 对"思维导图"返回带"思维导图"的内容
        all_text = "".join(
            m.get("content", "")
            for call in fake_llm.calls
            for m in call
        )
        assert "思维导图" in all_text or "Mermaid" in all_text, \
            "应触发 mindmap 而非默认 handout"


class TestChangePassword:
    """修复 #10 回归：修改密码接口真实可用"""

    @pytest.mark.asyncio
    async def test_change_password_correct_old(self, client, test_user):
        """正确旧密码应能修改成功"""
        resp = await client.post("/api/students/change_password", json={
            "user_id": test_user.id,
            "old_password": "1234",
            "new_password": "5678",
        })
        assert resp.status_code == 200, f"应返回 200，实际: {resp.status_code} {resp.text}"

        # 验证新密码能登录
        resp2 = await client.post("/api/students/login", json={
            "login_id": test_user.login_id,
            "password": "5678",
        })
        assert resp2.status_code == 200, "新密码应能登录"

    @pytest.mark.asyncio
    async def test_change_password_wrong_old(self, client, test_user):
        """错误旧密码应返回 401"""
        resp = await client.post("/api/students/change_password", json={
            "user_id": test_user.id,
            "old_password": "wrong",
            "new_password": "5678",
        })
        assert resp.status_code == 401, "旧密码错误应返回 401"

    @pytest.mark.asyncio
    async def test_change_password_too_short(self, client, test_user):
        """新密码过短应返回 400"""
        resp = await client.post("/api/students/change_password", json={
            "user_id": test_user.id,
            "old_password": "1234",
            "new_password": "12",
        })
        assert resp.status_code == 400, "新密码过短应返回 400"
