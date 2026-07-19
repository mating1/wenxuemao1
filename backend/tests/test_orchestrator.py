"""
Orchestrator 编排器测试
覆盖：
- 意图识别（关键词路由）
- _detect_resource_type 资源类型识别（修复 #8 的回归测试）
- _extract_topic / _extract_subject
- run() 完整 pipeline（用 fake_llm，验证 Agent 串联和上下文传递）
- 修复 #6: dialogue_history 不再写死
- 修复 #7: error_records 不再写死
"""
import pytest
from app.agents.orchestrator import AgentOrchestrator


class TestIntentDetection:
    """意图识别关键词路由"""

    @pytest.mark.parametrize("msg,expected", [
        ("帮我诊断一下我的学习情况", "diagnosis"),
        ("我哪里比较薄弱？", "diagnosis"),
        ("我学得怎样", "diagnosis"),
        ("帮我生成一份讲义", "generate"),
        ("给我一份思维导图", "generate"),
        ("出一份题库", "generate"),
        ("帮我规划学习路径", "pathway"),
        ("下一步学什么", "pathway"),
        ("学习计划", "pathway"),
        ("老师布置的作业", "homework"),
        ("你好", "chat"),
        ("今天天气真好", "chat"),
    ])
    def test_detect_intent(self, msg, expected):
        assert AgentOrchestrator.detect_intent(msg) == expected


class TestResourceTypeDetection:
    """资源类型识别 —— 修复 #8 的回归测试"""

    @pytest.mark.parametrize("msg,expected", [
        ("帮我生成讲义", "handout"),
        ("给我一份思维导图", "mindmap"),
        ("画个脑图", "mindmap"),
        ("出一份题库", "question_bank"),
        ("我想刷题", "question_bank"),
        ("来个实训案例", "practical_case"),
        ("做个实操项目", "practical_case"),
        ("生成微课", "micro_lecture"),
        ("帮我录个视频", "micro_lecture"),
        ("随便给我点资料", "handout"),  # 默认
        ("hello", "handout"),  # 默认
    ])
    def test_detect_resource_type(self, msg, expected):
        assert AgentOrchestrator._detect_resource_type(msg) == expected


class TestExtractTopic:
    """主题提取"""

    def test_extract_topic_with_prefix(self):
        assert AgentOrchestrator._extract_topic("帮我生成递归的讲义") == "递归"

    def test_extract_topic_no_prefix(self):
        # 无关键词时返回原消息
        assert AgentOrchestrator._extract_topic("二叉树") == "二叉树"


class TestExtractSubject:
    """学科提取"""

    @pytest.mark.parametrize("msg,expected", [
        ("帮我学Python", "Python"),
        ("数据结构怎么学", "数据结构"),
        ("高数复习", ""),  # "高数"不在列表，只有"高等数学"
        ("随便聊聊", ""),
    ])
    def test_extract_subject(self, msg, expected):
        assert AgentOrchestrator._extract_subject(msg) == expected


class TestRunPipeline:
    """run() 完整 pipeline 测试 —— 使用 fake_llm"""

    @pytest.mark.asyncio
    async def test_chat_intent_returns_content(self, fake_llm):
        """普通聊天意图：应返回非空内容，agents_used 至少含采集Agent"""
        orch = AgentOrchestrator()
        result = await orch.run(
            student_message="你好，今天学点什么",
            student_profile={"foundation_score": 50, "education_level": "undergraduate"},
            education_level="undergraduate",
            education_level_label="本科",
            student_name="小明",
        )
        assert result.content, "回复内容不应为空"
        assert "学情采集Agent" in result.agents_used
        assert result.intent == "chat"

    @pytest.mark.asyncio
    async def test_generate_intent_triggers_generation_and_verification(self, fake_llm):
        """生成意图：应触发生成Agent + 校验Agent"""
        orch = AgentOrchestrator()
        result = await orch.run(
            student_message="帮我生成递归的讲义",
            student_profile={"foundation_score": 50, "education_level": "undergraduate"},
            education_level="undergraduate",
            education_level_label="本科",
            student_name="小明",
        )
        assert result.intent == "generate"
        assert "资源生成Agent" in result.agents_used
        assert "校验防幻觉Agent" in result.agents_used
        assert result.resource is not None
        assert result.resource_topic == "递归"
        # 修复 #11: 校验后应输出修正版资源
        assert result.verification is not None
        assert "revised_content" in result.verification

    @pytest.mark.asyncio
    async def test_diagnosis_intent_triggers_diagnosis_agent(self, fake_llm):
        """诊断意图：应触发诊断Agent"""
        orch = AgentOrchestrator()
        result = await orch.run(
            student_message="帮我诊断一下我的学习情况",
            student_profile={"foundation_score": 50, "education_level": "undergraduate"},
            education_level="undergraduate",
            education_level_label="本科",
            student_name="小明",
        )
        assert result.intent == "diagnosis"
        assert "诊断Agent" in result.agents_used
        assert result.diagnosis is not None

    @pytest.mark.asyncio
    async def test_pathway_intent_triggers_pathway_agent(self, fake_llm):
        """路径意图：应触发诊断Agent + 路径Agent"""
        orch = AgentOrchestrator()
        result = await orch.run(
            student_message="帮我规划Python的学习路径",
            student_profile={"foundation_score": 50, "education_level": "undergraduate"},
            education_level="undergraduate",
            education_level_label="本科",
            student_name="小明",
        )
        assert result.intent == "pathway"
        assert "诊断Agent" in result.agents_used
        assert "路径规划Agent" in result.agents_used
        assert result.pathway is not None

    @pytest.mark.asyncio
    async def test_dialogue_history_passed_to_collection_agent(self, fake_llm):
        """
        修复 #6 回归测试：dialogue_history 应传递给采集 Agent
        验证：fake_llm 收到的 messages 中包含历史内容
        """
        orch = AgentOrchestrator()
        history = [
            {"role": "user", "content": "我之前问过递归"},
            {"role": "assistant", "content": "好的我教你"},
        ]
        await orch.run(
            student_message="继续",
            student_profile={"foundation_score": 50, "education_level": "undergraduate"},
            education_level="undergraduate",
            education_level_label="本科",
            student_name="小明",
            dialogue_history=history,
        )
        # 验证 fake_llm 至少被调用一次，且某次调用的 messages 包含历史
        assert fake_llm.call_count > 0
        all_text = "".join(
            m.get("content", "")
            for call in fake_llm.calls
            for m in call
        )
        assert "我之前问过递归" in all_text, "对话历史应被传递给采集Agent"

    @pytest.mark.asyncio
    async def test_error_records_passed_to_diagnosis_agent(self, fake_llm):
        """
        修复 #7 回归测试：error_records 应传递给诊断 Agent
        """
        orch = AgentOrchestrator()
        errors = [
            {"knowledge_point": "递归", "error_type": "概念混淆", "times_wrong": 3},
        ]
        await orch.run(
            student_message="帮我诊断一下",
            student_profile={"foundation_score": 50, "education_level": "undergraduate"},
            education_level="undergraduate",
            education_level_label="本科",
            student_name="小明",
            error_records=errors,
        )
        # 验证诊断 Agent 收到了错题记录
        all_text = "".join(
            m.get("content", "")
            for call in fake_llm.calls
            for m in call
        )
        assert "递归" in all_text and "概念混淆" in all_text, "错题记录应被传递给诊断Agent"

    @pytest.mark.asyncio
    async def test_resource_type_not_hardcoded(self, fake_llm):
        """
        修复 #8 回归测试：对话流程中资源类型不再硬编码 handout
        验证：请求"思维导图"时，传给生成Agent和校验Agent的 resource_type 是 mindmap
        """
        orch = AgentOrchestrator()
        result = await orch.run(
            student_message="帮我生成数据结构的思维导图",
            student_profile={"foundation_score": 50, "education_level": "undergraduate"},
            education_level="undergraduate",
            education_level_label="本科",
            student_name="小明",
        )
        assert result.intent == "generate"
        assert result.resource_topic == "数据结构"
        # 关键验证：校验结果中的 resource_type 应是 mindmap 而非 handout
        assert result.verification is not None
        assert result.verification.get("resource_type") == "mindmap", \
            f"资源类型应为 mindmap，实际: {result.verification.get('resource_type')}"
