"""
Agent 5: 校验防幻觉Agent
三方辩论式资源校验：生成Agent→学生Agent挑刺→教师Agent修正（并行评审+单轮修正）
"""
import json
from typing import Optional
from loguru import logger
from app.agents.base import BaseAgent
from app.services.llm_client import LLMProvider, get_llm_client


class VerificationAgent(BaseAgent):
    name = "校验防幻觉Agent"
    description = "通过并行评审+投票修正机制，验证生成资源的正确性与适用性"
    default_provider = LLMProvider.DEEPSEEK  # 校验默认也走 DeepSeek，有 Claude Key 时自动升级
    temperature = 0.3

    STUDENT_REVIEWER_PROMPT = """你扮演一位{education_level}学生（基础水平{foundation}/100分），正在阅读一份名为"{resource_type}"的学习材料，主题是"{topic}"。

## 你的任务
以学生的视角，找出这份材料中的问题：
1. **难以理解的地方**：哪些段落/概念写得太难、太跳跃？
2. **超纲内容**：哪些内容对{foundation}分基础的学生明显超纲？
3. **缺少的内容**：作为学生，你还想看哪些解释/示例？
4. **错误表述**：有没有明显表述不通顺、前后矛盾的地方？

## 输出格式
JSON: {{"issues": [{{"type": "too_hard|beyond_scope|missing|unclear", "location": "在材料中的位置描述", "description": "具体问题", "severity": "high|medium|low"}}], "overall_rating": 1-10, "keep_as_is": ["值得保留的亮点"]}}"""

    TEACHER_REVIEWER_PROMPT = """你是一位资深{education_level}教师/教授，正在审核一份名为"{resource_type}"的学习材料，主题是"{topic}"。

## 你的任务
以教师的专业视角，进行内容审核：
1. **知识点准确性**：核心概念定义是否正确、无歧义？
2. **逻辑连贯性**：内容组织是否合理、有递进关系？
3. **教学适用性**：是否匹配目标学生的学历层次与基础水平？
4. **语言规范**：表述是否严谨、专业术语使用是否准确？
5. **完整性**：是否覆盖了主题的核心知识点？

## 输出格式
JSON: {{"corrections": [{{"issue": "问题描述", "original": "原文引用(简短)", "corrected": "修正后的表述", "reason": "修正理由"}}], "accuracy_score": 1-10, "completeness_score": 1-10, "final_verdict": "approve|revise|reject"}}"""

    ARBITER_PROMPT = """你是一位教育质量把控专家。现在有一份学习资源经过了学生评审和教师评审，请汇总评审意见并输出最终修正版资源。

## 学生评审意见
{student_review}

## 教师评审意见
{teacher_review}

## 你的任务
1. 合并双方的修改建议，去重、排优先级
2. 对于存在的分歧（学生觉得太难、老师觉得合适等），以教师意见为主
3. **基于原始资源内容 + 评审意见，输出修正版完整资源内容**（保留原结构，只改有问题的地方，不要无中生有重写）
4. 如果评审意见基本无问题，revised_content 可与原始内容基本一致

## 输出格式
JSON: {{
  "merged_issues_count": 数量,
  "priority_fixes": ["最重要的3条修改"],
  "quality_assessment": {{"content_accuracy": 1-10, "pedagogical_fit": 1-10, "student_accessible": 1-10, "overall": 1-10}},
  "revised_content": "完整修正版资源内容（Markdown，保留原结构，仅修改评审指出的问题）",
  "final_note": "总结评价（30字以内）"
}}

**重要：revised_content 必须是完整的、可直接使用的资源内容，不是修改摘要。**"""

    async def verify(
        self,
        resource_content: str,
        resource_type: str,
        topic: str,
        education_level: str,
        foundation: float = 50.0,
        major: str = "",
    ) -> dict:
        """
        并行评审 + 裁判汇总。

        Args:
            resource_content: 待校验的资源内容
            resource_type: 资源类型
            topic: 主题
            education_level: undergraduate | vocational
            foundation: 学生基础分
            major: 学生专业

        Returns:
            校验结果，含修正建议和质量评分
        """
        level_label = "本科" if education_level == "undergraduate" else "高职专科"

        # 专业背景
        major_line = ""
        if major:
            major_line = (
                f"\n目标学生专业: {major}\n"
                f"请结合该专业的学科特点和培养目标，评审该材料是否贴合专业方向。"
            )

        # 准备共同的上下文
        review_context = f"""
## 待审核材料 ({resource_type})
主题: {topic}
目标学生: {level_label}，基础分 {foundation}/100{major_line}

### 材料内容
{resource_content[:8000]}"""

        # ---- 第一轮：并行评审 ----
        logger.info(f"[Verification] 启动并行评审: {resource_type}/{topic}")

        llm = get_llm_client()

        student_prompt = self.STUDENT_REVIEWER_PROMPT.format(
            education_level=level_label, foundation=foundation,
            resource_type=resource_type, topic=topic,
        )
        teacher_prompt = self.TEACHER_REVIEWER_PROMPT.format(
            education_level=level_label,
            resource_type=resource_type, topic=topic,
        )

        # 并行评审（有 Claude Key 则教师评审用 Claude，否则全部 DeepSeek）
        from app.config import settings
        _has_claude = bool(settings.anthropic_api_key) and "your-" not in settings.anthropic_api_key
        student_result = await self._safe_review(
            student_prompt, review_context, use_claude=False
        )
        teacher_result = await self._safe_review(
            teacher_prompt, review_context, use_claude=_has_claude
        )

        # ---- 第二轮：裁判汇总 ----
        arbiter_prompt = self.ARBITER_PROMPT.format(
            student_review=json.dumps(student_result, ensure_ascii=False),
            teacher_review=json.dumps(teacher_result, ensure_ascii=False),
        )

        arbiter_context = f"## 原始资源内容（完整）\n{resource_content[:8000]}"
        final_result = await self.ask_json(
            arbiter_prompt,
            context=arbiter_context,
            temperature=0.3,
            use_claude=_has_claude,
        )

        # 提取修正版资源内容；若 arbiter 未输出则保留原始内容作为兜底
        revised_content = final_result.get("revised_content") or resource_content
        # 若解析异常（parse_error 标记），不覆盖原始内容
        if final_result.get("parse_error"):
            revised_content = resource_content

        logger.info(
            f"[Verification] 校验完成: 准确度={final_result.get('quality_assessment',{}).get('overall','?')}/10, "
            f"已生成修正版资源({len(revised_content)}字符)"
        )

        return {
            "student_review": student_result,
            "teacher_review": teacher_result,
            "arbiter": final_result,
            "revised_content": revised_content,
            "resource_type": resource_type,
            "topic": topic,
        }

    async def _safe_review(self, prompt: str, context: str, use_claude: bool) -> dict:
        """安全的评审调用，失败时自动降级"""
        from app.config import settings
        # 检查 Key 是否真实（排除占位符）
        has_claude = bool(settings.anthropic_api_key) and "your-" not in settings.anthropic_api_key
        provider = LLMProvider.ANTHROPIC if (use_claude and has_claude) else LLMProvider.DEEPSEEK

        try:
            messages = self._build_messages(prompt, context)
            response = await get_llm_client().chat(
                messages, provider=provider, temperature=0.3
            )
            text = response.content.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:]) if len(lines) > 1 else text
                if text.endswith("```"):
                    text = text[:-3]
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
            return {"raw_response": text, "parse_error": True}
        except Exception as e:
            logger.warning(f"[Verification] {provider.value} 评审失败: {e}, 尝试降级")
            if provider == LLMProvider.ANTHROPIC:
                try:
                    response = await get_llm_client().chat(
                        messages, provider=LLMProvider.DEEPSEEK, temperature=0.3
                    )
                    text = response.content.strip()
                    start = text.find("{")
                    end = text.rfind("}") + 1
                    if start >= 0 and end > start:
                        return json.loads(text[start:end])
                    return {"raw_response": text, "parse_error": True}
                except Exception as e2:
                    return {"error": str(e2), "parse_error": True}
            return {"error": str(e), "parse_error": True}
