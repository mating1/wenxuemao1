"""
Agent 1: 学情采集Agent —— 通过对话采集6维学情画像
"""
from app.agents.base import BaseAgent
from app.services.llm_client import LLMProvider


class CollectionAgent(BaseAgent):
    name = "学情采集Agent"
    description = "通过自然对话采集学生6维学情画像，更新知识薄弱图谱"
    default_provider = LLMProvider.DEEPSEEK
    temperature = 0.6

    system_prompt = """你是一位专业的教育学情分析师，通过自然对话采集学生学习情况。你不做教学，只做信息收集与分析。

## 你的任务
在与学生的对话中，提取并更新以下6维度学情画像：

1. **基础能力** (foundation): 评估值0-100，根据学生对基础概念的回答准确度判断
2. **认知风格** (cognitive_style): visual(图表型)/auditory(音频型)/verbal(文字型)/hands_on(动手型)
3. **易错知识点** (weak_points): 数组，具体知识点名称，如["递归", "指针"]
4. **实训动手能力** (practical): 评估值0-100，根据对实践问题的回答判断
5. **学习目标** (learning_goals): {short_term: "短期目标", long_term: "长期目标"}
6. **情绪状态** (emotion): positive/neutral/frustrated/confused/motivated

## 对话规则
- 每次最多问2个问题，避免让学生疲惫
- 用自然的聊天语气，不要像做问卷
- 识别到新信息后默默更新画像，在每轮回复末尾以JSON输出画像更新
- 如果学生是专科/高职学生，多问实训、动手操作相关的问题
- 如果学生是本科学生，多问理论理解、算法推导相关的问题

## 输出格式
在每次回复的最后一行（学生看不到的位置），输出JSON画像快照：
```json
{"profile_update": {"foundation": 75, "weak_points": ["指针","动态规划"], ...}}
```

记住：你的回复主体是面向学生的自然对话，画像JSON仅作为内部标记放在最后。"""

    async def collect(
        self,
        student_message: str,
        education_level: str,
        current_profile: dict,
        dialogue_history: list[dict],
    ) -> dict:
        """
        处理学生消息，返回学情更新。

        Args:
            student_message: 学生当前消息
            education_level: undergraduate | vocational
            current_profile: 当前6维画像
            dialogue_history: 最近对话记录
        """
        # 根据学历层次调整提问策略
        branch_hint = (
            "该生是**本科**学生，请侧重考察理论基础、算法理解、论文阅读能力。"
            if education_level == "undergraduate"
            else "该生是**专科/高职**学生，请侧重考察动手操作、岗位实训、职业技能。"
        )

        # 根据专业调整提问方向
        major = current_profile.get("major", "")
        major_hint = ""
        if major:
            major_hint = (
                f"该学生的专业是**{major}**。请围绕该专业领域进行提问和评估，"
                f"重点关注该专业核心课程的知识掌握情况。"
            )
        else:
            major_hint = "该学生的专业未知，可以通过对话了解其专业背景和所学方向。"

        context = f"""
{branch_hint}
{major_hint}

## 当前学生画像
{current_profile}

## 最近对话
{self._format_history(dialogue_history)}
"""
        result = await self.ask_json(
            student_message,
            context=context,
            temperature=0.6,
        )
        return result.get("profile_update", result)

    def _format_history(self, history: list[dict]) -> str:
        if not history:
            return "(无历史)"
        lines = []
        for h in history[-10:]:  # 最近10轮
            role = "学生" if h.get("role") == "user" else "AI"
            content = h.get("content", "")[:200]
            lines.append(f"- [{role}]: {content}")
        return "\n".join(lines)

    async def greet(self, education_level: str, student_name: str = "同学") -> str:
        """生成初次问候语"""
        prompt = f"请向一位{education_level}学生{student_name}打招呼，做一个简短自然的自我介绍，并开始了解ta的学习情况。只需1-2句话+1个问题。"
        return await self.ask(prompt, temperature=0.8)
