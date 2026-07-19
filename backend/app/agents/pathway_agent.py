"""
Agent 3: 路径规划Agent —— 根据画像生成自适应学习路径
"""
import uuid
from app.agents.base import BaseAgent
from app.services.llm_client import LLMProvider


class PathwayAgent(BaseAgent):
    name = "路径规划Agent"
    description = "根据学生画像与诊断结果，生成自适应个性化学习路径"
    default_provider = LLMProvider.DEEPSEEK
    temperature = 0.5

    system_prompt = """你是一位学习路径设计师，专门为学生定制个性化学习路线图。

## 你的设计原则
1. 因人而异：根据学生基础水平、认知风格、学习目标来设计路径
2. 阶梯递进：从基础→进阶→应用，每步都有明确的掌握度门槛
3. 匹配学历层次：
   - **本科**路径偏理论推导、算法原理、论文阅读、学术写作
   - **专科**路径偏代码实操、项目案例、职业技能认证、岗位实训
4. 每个节点关联具体的学习资源类型
5. 控制难度梯度：基础节点掌握度≥60%才能进入下一阶段

## 输出格式
严格输出JSON：
{
  "pathway": {
    "title": "路径名称",
    "description": "路径描述",
    "difficulty_track": "basic|intermediate|advanced",
    "estimated_hours": 估算总学时,
    "nodes": [
      {
        "order": 1,
        "title": "节点标题",
        "type": "lesson|exercise|case|review",
        "description": "节点描述",
        "resource_types": ["handout", "mindmap"],
        "mastery_threshold": 70,
        "knowledge_points": ["知识1"]
      }
    ]
  }
}

节点总数控制在 5-10 个，确保路径可执行性。"""

    async def plan(
        self,
        profile: dict,
        diagnosis: dict,
        education_level: str,
        subject: str = "",
    ) -> dict:
        """
        生成个性化学习路径。

        Args:
            profile: 6维学情画像
            diagnosis: 诊断结果
            education_level: undergraduate | vocational
            subject: 目标学科/主题
        """
        branch_instruction = (
            "请设计一条**本科层次**的学习路径，侧重理论推导、算法原理、学术深度。"
            if education_level == "undergraduate"
            else "请设计一条**专科层次**的学习路径，侧重代码实操、项目案例、岗位技能。"
        )

        # 专业背景
        major = profile.get("major", "")
        major_instruction = ""
        if major:
            major_instruction = (
                f"该学生专业为**{major}**，请围绕该专业的核心课程和技能要求设计学习路径，"
                f"确保路径内容与专业培养目标一致。"
            )

        context = f"""{branch_instruction}
{major_instruction}

## 学生画像
基础能力: {profile.get('foundation_score', 50)}/100
认知风格: {profile.get('cognitive_style', 'verbal')}
实训能力: {profile.get('practical_score', 50)}/100
薄弱点: {profile.get('weak_points', [])}
学习目标: {profile.get('learning_goals', {})}

## 诊断摘要
{diagnosis}

## 目标学科: {subject or '通用'}
"""
        result = await self.ask_json(
            f"请为上述学生设计一条个性化的'{subject or '通用'}'学习路径。",
            context=context,
            temperature=0.5,
        )
        pathway = result.get("pathway", result)
        # 为每个节点生成唯一ID
        for node in pathway.get("nodes", []):
            if "id" not in node:
                node["id"] = str(uuid.uuid4())[:8]
        return pathway
