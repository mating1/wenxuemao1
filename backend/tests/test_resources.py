"""
资源 API 测试
覆盖：
- 修复 #3 回归：/compare 接口专科分支不再引用 undergraduate 的 qt
- 修复 #11 回归：/generate verify 后用 revised_content 入库
- 双分支对比接口返回结构正确
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.base import get_db
from app.models.student import UserProfile, UserRole, EducationLevel
from app.models.resource import LearningResource, EducationBranch


@pytest_asyncio.fixture
async def client(temp_db, fake_llm):
    """FastAPI 测试客户端，使用 temp_db 和 fake_llm"""
    app.dependency_overrides[get_db] = temp_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(temp_db):
    """创建一个测试学生"""
    async for session in temp_db():
        import bcrypt
        user = UserProfile(
            name="测试学生",
            login_id="test001",
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


class TestCompareNoNameError:
    """修复 #3 回归：/compare 不含 question_bank 时不应 NameError"""

    @pytest.mark.asyncio
    async def test_compare_without_question_bank(self, client, test_user):
        """resource_types 不含 question_bank 时，专科分支不应崩溃"""
        resp = await client.post("/api/resources/compare", json={
            "topic": "二叉树遍历",
            "education_level": "undergraduate",
            "foundation": 50,
            "resource_types": ["handout"],  # 不含 question_bank
            "verify": False,
            "question_types": [],
        })
        assert resp.status_code == 200, f"应返回 200，实际: {resp.status_code} {resp.text}"
        data = resp.json()
        assert "undergraduate" in data
        assert "vocational" in data
        assert "handout" in data["undergraduate"]["resources"]
        assert "handout" in data["vocational"]["resources"]

    @pytest.mark.asyncio
    async def test_compare_with_question_bank(self, client, test_user):
        """含 question_bank 时同样应正常工作"""
        resp = await client.post("/api/resources/compare", json={
            "topic": "二叉树遍历",
            "education_level": "undergraduate",
            "foundation": 50,
            "resource_types": ["handout", "question_bank"],
            "verify": False,
            "question_types": ["choice", "true_false"],
        })
        assert resp.status_code == 200, f"应返回 200，实际: {resp.status_code} {resp.text}"
        data = resp.json()
        assert "question_bank" in data["undergraduate"]["resources"]
        assert "question_bank" in data["vocational"]["resources"]

    @pytest.mark.asyncio
    async def test_compare_empty_resource_types(self, client, test_user):
        """空 resource_types 也应正常返回（不应 NameError）"""
        resp = await client.post("/api/resources/compare", json={
            "topic": "二叉树遍历",
            "education_level": "undergraduate",
            "foundation": 50,
            "resource_types": [],
            "verify": False,
            "question_types": [],
        })
        assert resp.status_code == 200


class TestGenerateWithVerification:
    """修复 #11 回归：/generate 开启 verify 后应使用修正版内容入库"""

    @pytest.mark.asyncio
    async def test_generate_verify_uses_revised_content(self, client, test_user, temp_db):
        """开启 verify 时，入库的 content 应是修正版而非原始生成版"""
        resp = await client.post("/api/resources/generate", json={
            "topic": "递归",
            "education_level": "undergraduate",
            "foundation": 50,
            "resource_types": ["handout"],
            "verify": True,
            "question_types": [],
            "user_id": test_user.id,
        })
        assert resp.status_code == 200, f"应返回 200，实际: {resp.status_code} {resp.text}"
        data = resp.json()
        # fake_llm 对生成返回 "# 测试讲义..."，对 arbiter 返回 "# 修正版讲义..."
        # 修复后 results[rtype].content 应为修正版
        content = data["resources"]["handout"]["content"]
        assert "修正版" in content, f"应使用修正版内容，实际: {content[:100]}"
        # quality_score 应来自 arbiter 的 quality_assessment.overall = 8
        assert data["resources"]["handout"]["quality_score"] == 8
        assert data["resources"]["handout"]["debate_rounds"] == 2

        # 验证数据库中存的也是修正版（LearningResource 无 topic 字段，用 title 过滤）
        async for session in temp_db():
            from sqlalchemy import select
            result = await session.execute(
                select(LearningResource).where(LearningResource.title == "递归 - handout")
            )
            resources = result.scalars().all()
            assert len(resources) > 0, "应有资源入库"
            db_content = resources[0].content
            assert "修正版" in db_content, f"DB 中应存修正版内容，实际: {db_content[:100]}"
            break

    @pytest.mark.asyncio
    async def test_generate_no_verify_keeps_original(self, client, test_user):
        """关闭 verify 时，content 应是原始生成内容"""
        resp = await client.post("/api/resources/generate", json={
            "topic": "递归",
            "education_level": "undergraduate",
            "foundation": 50,
            "resource_types": ["handout"],
            "verify": False,
            "question_types": [],
            "user_id": test_user.id,
        })
        assert resp.status_code == 200
        data = resp.json()
        content = data["resources"]["handout"]["content"]
        # 未开 verify 时应是原始生成内容（fake_llm 返回 "# 测试讲义..."）
        assert "测试讲义" in content, f"未开 verify 应保留原始内容，实际: {content[:100]}"
        # 默认质量分 7.0，debate_rounds 0
        assert data["resources"]["handout"]["quality_score"] == 7.0
        assert data["resources"]["handout"]["debate_rounds"] == 0


class TestDualBranchDifference:
    """双分支对比：本科版和专科版应都存在且 branch 字段正确"""

    @pytest.mark.asyncio
    async def test_compare_persists_both_branches(self, client, test_user, temp_db):
        """/compare 应同时持久化本科和专科两份资源"""
        resp = await client.post("/api/resources/compare", json={
            "topic": "排序算法",
            "education_level": "undergraduate",
            "foundation": 50,
            "resource_types": ["handout"],
            "verify": False,
            "question_types": [],
        })
        assert resp.status_code == 200

        async for session in temp_db():
            from sqlalchemy import select
            result = await session.execute(
                select(LearningResource).where(LearningResource.title.like("%排序算法%"))
            )
            resources = result.scalars().all()
            branches = {r.branch.value for r in resources}
            assert "undergraduate" in branches, "应持久化本科分支"
            assert "vocational" in branches, "应持久化专科分支"
            break
