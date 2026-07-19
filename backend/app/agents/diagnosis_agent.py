"""
Agent 2: 诊断Agent —— 分析学情数据，找出薄弱环节与学习建议
"""
from app.agents.base import BaseAgent
from app.services.llm_client import LLMProvider


class DiagnosisAgent(BaseAgent):
    name = "诊断Agent"
    description = "分析学情画像数据，产出知识薄弱点诊断与学习建议"
    default_provider = LLMProvider.DEEPSEEK
    temperature = 0.4

    system_prompt = """你是一位资深教育诊断专家，擅长分析学生的学习数据并给出精准诊断。

## 你的能力
1. 分析6维学情画像，识别核心薄弱环节
2. 对知识薄弱点进行根因分析：是概念不清、练习不足、还是应用能力欠缺
3. 区分本科与专科学生，给出不同侧重点的诊断
4. 给出可操作的改进建议

## 诊断维度
- **知识体系漏洞**: 哪些知识点存在盲区
- **思维模型偏差**: 哪些概念理解有误
- **学习策略问题**: 学习方法是否合适
- **情绪与动机**: 是否需要调整学习节奏

## 输出格式
严格输出JSON：
{
  "diagnosis": {
    "overall_level": "基础薄弱/一般/良好/优秀",
    "top_weak_areas": [{"name": "知识点", "mastery": 30, "reason": "根因"}],
    "strengths": ["优势1"],
    "cognitive_match": "当前学习方法是否匹配认知风格",
    "urgent_actions": ["需要立即补救的内容"],
    "long_term_advice": "长期学习策略建议",
    "recommended_resource_types": ["handout", "question_bank"],
    "motivation_tip": "一句鼓励的话"
  }
}"""

    async def diagnose(
        self,
        profile: dict,
        education_level: str,
        error_records: list[dict],
    ) -> dict:
        """
        对学情进行综合诊断。

        Args:
            profile: 6维学情画像
            education_level: undergraduate | vocational
            error_records: 错题记录列表
        """
        branch_focus = (
            "该生为**本科**学生，诊断时关注理论深度、算法理解、学术素养。"
            if education_level == "undergraduate"
            else "该生为**专科**学生，诊断时关注实践技能、岗位实操、职业认证。"
        )

        # 专业背景提示
        major = profile.get("major", "")
        major_focus = ""
        if major:
            major_focus = (
                f"该学生专业为**{major}**，请结合该专业的典型课程体系和能力要求进行诊断，"
                f"分析其在该专业核心领域的掌握程度。"
            )

        context = f"""{branch_focus}
{major_focus}

## 6维学情画像
{profile}

## 错题记录（最近20条）
{self._format_errors(error_records)}
"""
        result = await self.ask_json(
            "请对该名学生进行全面的学习诊断。",
            context=context,
            temperature=0.4,
        )
        return result.get("diagnosis", result)

    def _format_errors(self, errors: list[dict]) -> str:
        if not errors:
            return "(无错题记录)"
        lines = []
        for e in errors[:20]:
            lines.append(
                f"- 知识点:{e.get('knowledge_point','')} | "
                f"错因:{e.get('error_type','')} | "
                f"错误次数:{e.get('times_wrong',1)}"
            )
        return "\n".join(lines) if lines else "(无有效错题)"
