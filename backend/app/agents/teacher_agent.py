"""
Agent 6: 教师管理Agent —— 批量学情查看、薄弱点题库、可视化报表
"""
from app.agents.base import BaseAgent
from app.services.llm_client import LLMProvider


class TeacherAgent(BaseAgent):
    name = "教师管理Agent"
    description = "班级管理、批量学情分析、专项题库生成、教学建议"
    default_provider = LLMProvider.DEEPSEEK
    temperature = 0.5

    system_prompt = """你是一位教学管理专家，帮助教师高效管理班级学习情况。

## 你的能力
1. 批量分析全班学生学情数据
2. 统计班级共性薄弱点，生成专项复习资料
3. 生成可视化学情报表数据
4. 给出针对性的教学建议
5. 自动分组：将学生按水平、薄弱点分类

## 输出格式（根据任务不同）
- 学情汇总：JSON格式报表数据，含统计数字
- 专项题库：Markdown格式，含题目+解析
- 教学建议：结构化文本，分优先级
- 分组建议：JSON数组，每组含学生名单+针对性策略"""

    async def class_overview(self, students: list[dict]) -> dict:
        """
        全班学情总览。

        Args:
            students: 学生画像列表 [{name, education_level, major, foundation_score, weak_points, ...}]
        """
        context = f"""
## 全班学生数据 ({len(students)}人)
{self._format_students(students)}
"""
        return await self.ask_json(
            """请分析该班级整体学情，输出：
{
  "summary": {
    "total_students": 人数,
    "avg_foundation": 平均基础分,
    "avg_practical": 平均实训分,
    "level_distribution": {"优秀": 人数, "良好": 人数, "一般": 人数, "薄弱": 人数},
    "major_distribution": {"专业名": 人数},
    "top3_weak_points": ["共性薄弱点1"],
    "undergrad_count": 本科人数,
    "vocational_count": 专科人数
  },
  "major_analysis": [{"major": "专业名", "student_count": 人数, "avg_foundation": 平均分, "common_weaknesses": ["该专业共性薄弱点"]}],
  "weak_point_heatmap": [{"point": "知识点", "affected_students": 受影响人数}],
  "teaching_suggestions": ["按专业分组教学建议1"],
  "groups": [{"name": "分组名", "students": ["姓名"], "focus": "关注重点", "major_hint": "涉及专业"}]
}""",
            context=context,
            temperature=0.4,
        )

    async def generate_class_exercises(
        self, weak_points: list[str], education_level: str, count: int = 10
    ) -> str:
        """
        针对班级共性薄弱点生成专项题库。

        Args:
            weak_points: 班级TOP薄弱知识点
            education_level: undergraduate | vocational
            count: 题目数量
        """
        level_text = "本科（侧重分析推导）" if education_level == "undergraduate" else "专科（侧重实操应用）"
        prompt = f"请针对以下班级共性薄弱知识点，生成{count}道专项练习题。面向{level_text}。\n薄弱点: {', '.join(weak_points)}\n含完整答案和解析。"
        return await self.ask(prompt, temperature=0.6)

    async def export_report(self, students: list[dict], class_stats: dict) -> dict:
        """
        导出可视化学情报表数据（JSON格式，供前端ECharts渲染）。

        Returns:
            包含多种图表所需的数据结构
        """
        context = f"## 班级统计\n{class_stats}\n## 学生数据\n{self._format_students(students)}"
        return await self.ask_json(
            """生成教学报表数据，用于前端ECharts可视化：
{
  "charts": {
    "level_pie": {"labels": [], "values": []},
    "weak_point_bar": {"labels": [], "values": []},
    "student_scatter": [{"name": "", "foundation": 0, "practical": 0}],
    "progress_line": {"dates": [], "avg_scores": []},
    "emotion_distribution": {"positive": 0, "neutral": 0, "frustrated": 0, "confused": 0, "motivated": 0}
  },
  "top_insights": ["关键发现1"],
  "urgent_interventions": ["需要立即干预的事项"]
}""",
            context=context,
            temperature=0.3,
        )

    def _format_students(self, students: list[dict]) -> str:
        lines = []
        for s in students:
            lines.append(
                f"- {s.get('name','?')}: 专业={s.get('major','未知')}, "
                f"学历={s.get('education_level','?')}, "
                f"基础={s.get('foundation_score',50)}, 实训={s.get('practical_score',50)}, "
                f"薄弱点={s.get('weak_points',[])}"
            )
        return "\n".join(lines)
