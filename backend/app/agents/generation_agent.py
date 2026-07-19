"""
Agent 4: 多模态资源生成Agent
双分支核心：本科理论分支 vs 专科实训分支，生成5类学习资源
"""
from app.agents.base import BaseAgent
from app.services.llm_client import LLMProvider


class GenerationAgent(BaseAgent):
    name = "资源生成Agent"
    description = "根据学情画像和学历层次，生成5类差异化学习资源"
    default_provider = LLMProvider.DEEPSEEK
    temperature = 0.7

    UNDERGRADUATE_SYSTEM = """你是一位**本科教育**专家，为本科生生成学习资源。"""
    VOCATIONAL_SYSTEM = """你是一位**高职教育**专家，为专科学生生成实训资源。"""

    QT_LABELS: dict[str, str] = {
        "choice": "选择题", "true_false": "判断题", "fill_blank": "填空题",
        "short_answer": "简答题", "coding": "代码题",
    }

    RESOURCE_PROMPTS = {
        "handout": {
            "label": "讲义",
            "undergraduate": (
                "你是本科教授。请为主题「{topic}」撰写一份本科深度讲义。\n\n"
                "## 结构要求\n"
                "1. 知识体系概述（2-3段）\n"
                "2. 核心概念定义（逐一列出，配公式/图示）\n"
                "3. 理论推导（分步骤，带公式编号）\n"
                "4. 典型算法/数据结构（伪代码+时间复杂度分析）\n"
                "5. 学术前沿拓展（相关研究方向和论文索引）\n"
                "6. 课后思考题（3道）\n\n"
                "目标学生基础分{foundation}/100。输出完整Markdown，用##标题分段。"
                "必须紧密围绕主题「{topic}」展开，不得偏离。"
            ),
            "vocational": (
                "你是高职实训讲师。请为主题「{topic}」撰写一份专科实训讲义。\n\n"
                "## 结构要求\n"
                "1. 技能应用场景（1段描述实际工作中哪里用到）\n"
                "2. 核心操作步骤（编号列表，每步配命令/代码）\n"
                "3. 完整代码/命令示例（可直接复制运行）\n"
                "4. 常见错误与解决方案（表格：错误现象|原因|解决）\n"
                "5. 岗位技能对照表（此技能对应哪些招聘岗位）\n"
                "6. 课后实操练习（2道）\n\n"
                "目标学生基础分{foundation}/100。输出完整Markdown，用##标题分段。"
                "必须紧密围绕主题「{topic}」展开，不得偏离。"
            ),
        },
        "mindmap": {
            "label": "思维导图",
            "undergraduate": (
                "输出一段 Mermaid graph TD 代码，主题：{topic}。\n"
                "**绝对禁止输出任何 markdown 标题、文字、解释。你的整个回答只能是一段 mermaid 代码！**\n"
                "节点 ID 只能是字母+数字，禁止小数点、特殊符号。文字用英文句号或空格分隔。\n"
                "示例（严格照抄格式，只用方形节点 B1[文字]）：\n"
                "graph TD\n"
                "  A[主题] --> B1[分点一]\n"
                "  A --> B2[分点二]\n"
                "  B1 --> C1[细项一]\n"
                "  B1 --> C2[细项二]\n"
                "  B2 --> C3[细项三]\n"
                "  B2 --> C4[细项四]\n"
                "生成 4 主分支 8 子节点，节点文字简洁，不许用冒号括号引号。"
            ),
            "vocational": (
                "输出一段 Mermaid graph TD 代码，主题：{topic}。\n"
                "**绝对禁止输出任何 markdown 标题、文字、解释。你的整个回答只能是一段 mermaid 代码！**\n"
                "节点 ID 只能是字母+数字，禁止小数点、特殊符号。文字用英文句号或空格分隔。\n"
                "示例（严格照抄格式，只用方形节点 B1[文字]）：\n"
                "graph TD\n"
                "  A[主题] --> B1[分点一]\n"
                "  A --> B2[分点二]\n"
                "  B1 --> C1[细项一]\n"
                "  B1 --> C2[细项二]\n"
                "  B2 --> C3[细项三]\n"
                "  B2 --> C4[细项四]\n"
                "生成 4 主分支 8 子节点，节点文字简洁，不许用冒号括号引号。"
            ),
        },
        "question_bank": {
            "label": "题库",
            "undergraduate": (
                "系统指令：生成题库。\n\n"
                "**必须输出纯 JSON！不准输出 Markdown 标题、段落、解释文字！只输出 JSON！**\n\n"
                "题型与数量：{qtypes}。每种题型严格按指定数量生成。\n\n"
                "JSON 格式：{{ \"questions\": [\n"
                "  {{ \"id\":1,\"type\":\"choice\",\"content\":\"题目?\",\"options\":[\"A. ...\",\"B. ...\",\"C. ...\",\"D. ...\"],\"answer\":\"A\",\"hint\":\"解析文字\",\"difficulty\":2 }},\n"
                "  {{ \"id\":2,\"type\":\"true_false\",\"content\":\"陈述句\",\"answer\":\"true\",\"hint\":\"解析文字\",\"difficulty\":1 }},\n"
                "  {{ \"id\":3,\"type\":\"fill_blank\",\"content\":\"...是___和___\",\"answer\":\"答案1，答案2\",\"hint\":\"解析文字\",\"difficulty\":2 }},\n"
                "  {{ \"id\":4,\"type\":\"short_answer\",\"content\":\"简述...\",\"answer\":\"3-5行参考答案\",\"hint\":\"答题要点提示\",\"difficulty\":3 }}\n"
                "] }}\n\n"
                "【禁止】不要加 Markdown 代码块 ```json，不要加标题，不要加解释，直接输出裸 JSON！"
            ),
            "vocational": (
                "系统指令：生成题库。\n\n"
                "**必须输出纯 JSON！不准输出 Markdown 标题、段落、解释文字！只输出 JSON！**\n\n"
                "题型与数量：{qtypes}。每种题型严格按指定数量生成。\n\n"
                "JSON 格式：{{ \"questions\": [\n"
                "  {{ \"id\":1,\"type\":\"choice\",\"content\":\"题目?\",\"options\":[\"A. ...\",\"B. ...\",\"C. ...\",\"D. ...\"],\"answer\":\"A\",\"hint\":\"解析文字\",\"difficulty\":2 }},\n"
                "  {{ \"id\":2,\"type\":\"true_false\",\"content\":\"陈述句\",\"answer\":\"true\",\"hint\":\"解析文字\",\"difficulty\":1 }},\n"
                "  {{ \"id\":3,\"type\":\"fill_blank\",\"content\":\"...是___和___\",\"answer\":\"答案1，答案2\",\"hint\":\"解析文字\",\"difficulty\":2 }},\n"
                "  {{ \"id\":4,\"type\":\"short_answer\",\"content\":\"简述...\",\"answer\":\"3-5行参考答案\",\"hint\":\"答题要点提示\",\"difficulty\":3 }}\n"
                "] }}\n\n"
                "【禁止】不要加 Markdown 代码块 ```json，不要加标题，不要加解释，直接输出裸 JSON！"
            ),
        },
        "practical_case": {
            "label": "实训案例",
            "undergraduate": (
                "你是本科实验课导师。请为主题「{topic}」写一份研究型实训案例。\n\n"
                "## 结构\n"
                "1. 研究背景与目标（为什么做这个实验，学到什么）\n"
                "2. 理论基础（相关公式/定理，不超过5行）\n"
                "3. 实验环境（所需软件/库/版本）\n"
                "4. 实验步骤（每步配代码片段和预期输出）\n"
                "5. 数据分析（如何验证结果，画什么图）\n"
                "6. 拓展思考题（2道开放性问题）\n\n"
                "目标基础分{foundation}/100。输出完整Markdown。**必须围绕主题「{topic}」，不得偏题。**"
            ),
            "vocational": (
                "你是高职企业导师。请为主题「{topic}」写一份岗位实训案例。\n\n"
                "## 结构\n"
                "1. 岗位场景（真实工作场景描述）\n"
                "2. 任务需求（甲方/领导给的具体需求）\n"
                "3. 操作步骤（配完整命令和代码，保证能跑通）\n"
                "4. 检查点（每步做完怎么验证对不对）\n"
                "5. 交付标准（做完要交付什么文件/截图）\n"
                "6. 面试/认证考点（这个案例涉及哪些面试题）\n\n"
                "目标基础分{foundation}/100。输出完整Markdown。**必须围绕主题「{topic}」，不得偏题。**"
            ),
        },
        "micro_lecture": {
            "label": "微课脚本",
            "undergraduate": (
                "为主题「{topic}」写一份本科10分钟微课脚本。严格按以下表格格式输出：\n\n"
                "| 时间 | 环节 | 画面/PPT内容 | 讲解词 |\n"
                "|------|------|-------------|--------|\n"
                "| 0:00-0:30 | 导入 | 显示主题标题 | 引入语... |\n"
                "| 0:30-2:00 | 概念讲解 | 定义与公式 | 讲解词... |\n"
                "| ... | ... | ... | ... |\n"
                "| 9:00-10:00 | 总结与思考题 | 复习要点+思考题 | 总结词... |\n\n"
                "要求：8-10个时间段。包含导入、概念、推导、示例、应用、总结。直接输出表格，不要废话。"
            ),
            "vocational": (
                "为主题「{topic}」写一份专科15分钟微课脚本。严格按以下表格格式输出：\n\n"
                "| 时间 | 环节 | 屏幕录制/演示内容 | 解说词 |\n"
                "|------|------|------------------|--------|\n"
                "| 0:00-0:30 | 导入 | 显示实操场景 | 引入语... |\n"
                "| 0:30-3:00 | 工具/环境准备 | 打开IDE/终端 | 操作说明... |\n"
                "| ... | ... | ... | ... |\n"
                "| 13:00-15:00 | 总结与课后任务 | 回顾+课后练习 | 总结词... |\n\n"
                "要求：10-12个时间段。侧重实操演示。直接输出表格，不要废话。"
            ),
        },
    }

    async def generate(
        self,
        resource_type: str,
        topic: str,
        education_level: str,
        foundation: float = 50.0,
        *,
        use_claude: bool = False,
        question_types: list[str] | None = None,
        question_counts: dict[str, int] | None = None,
        major: str = "",
    ) -> str:
        if resource_type not in self.RESOURCE_PROMPTS:
            raise ValueError(f"不支持的资源类型: {resource_type}")

        template = self.RESOURCE_PROMPTS[resource_type]
        branch = education_level if education_level == "vocational" else "undergraduate"
        prompt_template = template[branch]

        # 构建题型计数指令
        qtypes_str = ""
        total_count = 0
        if resource_type == "question_bank" and question_counts:
            parts = []
            for t, c in question_counts.items():
                if c > 0:
                    lt = self.QT_LABELS.get(t, t)
                    parts.append(f"{lt} {c} 道")
                    total_count += c
            if parts:
                qtypes_str = "、".join(parts)
                # 动态修改共X题
                prompt_template = prompt_template.replace("共6题", f"共{total_count}题")
        elif resource_type == "question_bank" and question_types:
            parts = [self.QT_LABELS.get(t, t) for t in question_types]
            qtypes_str = "、".join(parts)
        else:
            qtypes_str = "选择题、判断题、填空题、简答题"

        # 用 replace 不用 format，避免提示词里的花括号 {} 被误解析
        prompt = prompt_template.replace("{topic}", topic).replace("{foundation}", str(foundation)).replace("{qtypes}", qtypes_str)

        # 如果题型混合，额外强调不能全是一种题型
        if question_counts and len([c for c in question_counts.values() if c > 0]) >= 2:
            prompt += "\n\n**【关键要求】必须严格按每种题型的指定数量生成，不能全部是一种题型！每种题型的数量与指定数量一致！**"

        # 专业背景提示
        major_context = f"学生基础分: {foundation}/100"
        if major:
            major_context += f"\n学生专业: {major}"
            major_context += f"\n\n**重要**：该学生专业是「{major}」，请在生成资源时紧密围绕该专业领域。"
            major_context += f"举例、案例、应用场景、岗位对接等都要与该专业相关。"
        else:
            major_context += "\n学生专业未知，请生成通用型资源。"

        # 通过 system_override 传递分支 system_prompt，不修改实例属性（并发安全）
        system_override = (
            self.VOCATIONAL_SYSTEM if education_level == "vocational"
            else self.UNDERGRADUATE_SYSTEM
        )
        return await self.ask(
            prompt,
            context=major_context,
            temperature=0.7,
            use_claude=use_claude,
            system_override=system_override,
        )
