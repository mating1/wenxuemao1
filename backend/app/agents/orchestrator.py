"""
6 Agent 编排器 —— 对话 Pipeline 中串联所有 Agent 协同工作

Pipeline:
  学生消息 → 采集Agent(画像更新)
          → 意图路由
               ├── 诊断意图 → 诊断Agent + 路径Agent
               ├── 生成意图 → 生成Agent + 校验Agent
               ├── 学习意图 → 诊断Agent
               └── 普通聊天 → 直接LLM回复

每条回复标注参与协作的 Agent 名称，供答辩展示。
"""
import json
from typing import Optional
from dataclasses import dataclass, field
from loguru import logger

from app.agents.base import BaseAgent
from app.agents.collection_agent import CollectionAgent
from app.agents.diagnosis_agent import DiagnosisAgent
from app.agents.pathway_agent import PathwayAgent
from app.agents.generation_agent import GenerationAgent
from app.agents.verification_agent import VerificationAgent
from app.services.llm_client import get_llm_client, LLMProvider


@dataclass
class PipelineResult:
    """编排结果"""
    content: str = ""                       # 最终回复给学生的文本
    agents_used: list[str] = field(default_factory=list)
    profile_update: dict = field(default_factory=dict)
    diagnosis: Optional[dict] = None
    pathway: Optional[dict] = None
    resource: Optional[str] = None
    resource_topic: Optional[str] = None
    verification: Optional[dict] = None
    intent: str = "chat"


class AgentOrchestrator:
    """6 Agent 编排器 —— 在对话 Pipeline 中串联所有 Agent"""

    def __init__(self):
        self.collection = CollectionAgent()
        self.diagnosis = DiagnosisAgent()
        self.pathway = PathwayAgent()
        self.generation = GenerationAgent()
        self.verification = VerificationAgent()

    # ---- 意图关键词 ----
    INTENT_KEYWORDS = {
        "diagnosis": ["诊断", "薄弱", "水平", "学得怎样", "检测一下", "我的问题", "哪弱", "怎么提升","我的分数"],
        "generate": ["生成", "给我一份", "做一份", "出一份", "讲义", "思维导图", "题库", "实训", "微课","写一份","整理一份","帮我生成"],
        "pathway": ["路径", "规划", "路线", "下一步", "接下来", "学习计划","计划"],
        "homework": ["作业","任务","老师","布置","上交"],
    }

    @staticmethod
    def detect_intent(message: str) -> str:
        """关键词法意图识别 —— 无需额外 LLM 调用"""
        msg = message
        # 检查各意图
        scores = {}
        for intent, keywords in AgentOrchestrator.INTENT_KEYWORDS.items():
            scores[intent] = sum(1 for k in keywords if k in msg)
        # 最高分意图
        if any(v > 0 for v in scores.values()):
            best = max(scores, key=scores.get)
            if scores[best] > 0:
                return best
        return "chat"

    async def run(
        self,
        student_message: str,
        student_profile: dict,
        education_level: str,
        education_level_label: str,
        student_name: str,
        dialogue_history: Optional[list[dict]] = None,
        error_records: Optional[list[dict]] = None,
    ) -> PipelineResult:
        """
        执行完整的 6 Agent 编排流程。

        Args:
            dialogue_history: 最近对话记录列表，每项 {"role": "user"|"assistant", "content": "..."}
            error_records: 学生错题记录列表，每项 {"knowledge_point": "...", "error_type": "...", "times_wrong": int}

        Returns:
            PipelineResult: 包含所有 Agent 协作结果的汇总对象
        """
        result = PipelineResult()
        agents_used = ["学情采集Agent"]  # 第一步必定用采集Agent
        dialogue_history = dialogue_history or []
        error_records = error_records or []

        # =====================================================
        # 第1步：意图识别（关键词规则，不调 LLM）
        # =====================================================
        intent = self.detect_intent(student_message)
        result.intent = intent
        logger.info(f"[Orchestrator] 意图={intent} 消息={student_message[:50]}")

        # =====================================================
        # 第2步：学情采集 —— 分析本轮对话更新画像
        # =====================================================
        profile_update = {}
        profile_update = await self.collection.collect(
            student_message=student_message,
            education_level=education_level,
            current_profile=student_profile,
            dialogue_history=dialogue_history,
        )
        result.profile_update = profile_update

        # =====================================================
        # 第3步：诊断 Agent —— 如果学生问诊断/学习类问题
        # =====================================================
        if intent in ("diagnosis", "pathway"):
            # 诊断 Agent 分析薄弱点
            agents_used.append("诊断Agent")
            diagnosis = await self.diagnosis.diagnose(
                profile=student_profile,
                education_level=education_level,
                error_records=error_records,
            )
            result.diagnosis = diagnosis
            logger.info(f"[Orchestrator] 诊断完成: {diagnosis.get('overall_level','?')}")

        # =====================================================
        # 第4步：路径 Agent —— 学生要学习规划
        # =====================================================
        if intent == "pathway" and result.diagnosis:
            agents_used.append("路径规划Agent")
            pathway = await self.pathway.plan(
                profile=student_profile,
                diagnosis=result.diagnosis,
                education_level=education_level,
                subject=self._extract_subject(student_message),
            )
            result.pathway = pathway
            logger.info(f"[Orchestrator] 路径规划: {pathway.get('title','?')}")

        # =====================================================
        # 第5步：生成 Agent —— 学生要学习资源
        # =====================================================
        if intent == "generate":
            agents_used.append("资源生成Agent")
            topic = self._extract_topic(student_message)
            resource_type = self._detect_resource_type(student_message)
            try:
                resource_content = await self.generation.generate(
                    resource_type=resource_type,
                    topic=topic,
                    education_level=education_level,
                    foundation=float(student_profile.get("foundation_score", 0)),
                    major=student_profile.get("major", ""),
                )
                result.resource = resource_content
                result.resource_topic = topic

                # =====================================================
                # 第6步：校验 Agent —— 对生成结果做辩论校验
                # =====================================================
                agents_used.append("校验防幻觉Agent")
                try:
                    verification = await self.verification.verify(
                        resource_content=resource_content,
                        resource_type=resource_type,
                        topic=topic,
                        education_level=education_level,
                        foundation=float(student_profile.get("foundation_score", 0)),
                        major=student_profile.get("major", ""),
                    )
                    result.verification = verification
                except Exception as e:
                    logger.warning(f"[Orchestrator] 校验失败: {str(e)[:100]}")

            except Exception as e:
                logger.error(f"[Orchestrator] 生成失败: {str(e)[:100]}")
                result.resource = f"[生成失败: {e}]"

        # =====================================================
        # 第7步：构建面向学生的最终回复
        # =====================================================
        result.agents_used = agents_used
        result.content = await self._build_response(
            intent=intent,
            student_name=student_name,
            education_level_label=education_level_label,
            diagnosis=result.diagnosis,
            pathway=result.pathway,
            resource=result.resource,
            resource_topic=result.resource_topic,
            verification=result.verification,
            agents_used=agents_used,
            student_message=student_message,
            profile=student_profile,
        )

        return result

    async def _build_response(self, intent: str, **ctx) -> str:
        """根据意图和 Agent 结果，构建最终面向学生的自然语言回复"""
        agents_str = " → ".join(ctx["agents_used"])
        profile = ctx["profile"]
        major = profile.get("major", "")
        grade = profile.get("grade", "")
        # 构建专业背景提示
        major_hint = ""
        if major:
            major_hint = f"该学生的专业是**{major}**。"
            if grade:
                major_hint += f"年级：{grade}。"
            major_hint += "请务必围绕该专业方向提供针对性的学习指导，举例子要结合该专业领域。"
        else:
            major_hint = "该学生的专业未知，可以通过对话了解其专业背景。"

        # 根据意图走不同回复模板
        if intent == "diagnosis" and ctx.get("diagnosis"):
            d = ctx["diagnosis"]
            diag_text = json.dumps(d, ensure_ascii=False, indent=2)
            diagnosis_prompt = (
                f"你是{ctx['student_name']}同学的学习助手。\n"
                f"{major_hint}\n"
                f"分析结果如下：\n{diag_text}\n\n"
                f"把诊断结果用通俗易懂的话告诉学生。"
                f"结合学生专业背景给出针对性的建议。"
                f"包含：1)总体水平 2)强项 3)薄弱点 4)接下来该补什么。300字以内。语气自然，不要太AI。"
            )
            return await self._call_llm(diagnosis_prompt)

        if intent == "generate" and ctx.get("resource"):
            summary_prompt = (
                f"你是{ctx['student_name']}同学的助学小猫。\n"
                f"{major_hint}\n"
                f"资源生成Agent和校验Agent已经为主题「{ctx['resource_topic']}」"
                f"生成了一份{ctx['education_level_label']}水平的完整学习资源，内容如下：\n\n"
                f"{ctx['resource'][:2000]}\n\n"
                f"给学生总结这份资源，结合专业背景说明价值："
                f"1)这份资源包括什么 2)重点学哪些部分 3)怎么检验学习效果。200字以内。"
            )
            main_content = ctx["resource"]
            summary = await self._call_llm(summary_prompt)
            return f"{summary}\n\n---\n\n{main_content}"

        if intent == "pathway" and ctx.get("pathway"):
            p = ctx["pathway"]
            path_text = json.dumps(p, ensure_ascii=False, indent=2)
            path_prompt = (
                f"你是{ctx['student_name']}同学的助学小猫。\n"
                f"{major_hint}\n"
                f"诊断Agent和路径规划Agent已为学生设计了学习路径：\n{path_text}\n\n"
                f"请用猫老师的口吻介绍这条学习路径，结合学生的专业背景说明路径如何帮助其专业发展，"
                f"鼓励学生开始第一步。200字以内。"
            )
            return await self._call_llm(path_prompt)

        # 普通聊天：用采集 Agent 的模式回复
        level_hint = ("你是本科导师，侧重理论推导、算法原理。"
                      if profile.get("education_level") == "undergraduate"
                      else "你是高职实训导师，侧重代码实操、岗位技能。")
        chat_prompt = (
            f"你是{ctx['student_name']}同学的助学小猫。{level_hint}\n"
            f"{major_hint}\n"
            f"学生消息: {ctx['student_message']}\n\n"
            f"当前学习数据: 基础分{profile.get('foundation_score',0)} 实训分{profile.get('practical_score',0)}\n"
            f"请根据该学生的学历层次和专业背景，给出与专业紧密相关的学习建议和回答。"
            f"用猫老师的口吻回复，偶尔带喵~，活泼可爱。300字以内。"
        )
        reply = await self._call_llm(chat_prompt)
        return reply

    async def _call_llm(self, prompt: str) -> str:
        """简化的 LLM 调用"""
        try:
            llm = get_llm_client()
            resp = await llm.chat(
                [{"role": "user", "content": prompt}],
                temperature=0.7
            )
            return resp.content
        except Exception as e:
            logger.error(f"[Orchestrator] LLM调用失败: {e}")
            return "喵~ AI服务暂时休息中，请稍后再试！"

    @staticmethod
    def _extract_topic(message: str) -> str:
        """从消息中提取学习主题"""
        for pre in ["生成", "给我一份", "做一份", "写一份", "整理一份", "关于", "帮我"]:
            if pre in message:
                idx = message.find(pre) + len(pre)
                topic = message[idx:].strip()
                for s in ["的讲义","的思维导图","的题库","的案例","的微课","的视频","吧","谢谢","。"]:
                    topic = topic.replace(s, "")
                return topic.strip() or message
        return message

    @staticmethod
    def _extract_subject(message: str) -> str:
        """从消息中提取学科名称"""
        subjects = ["Python","数据结构","算法","计算机网络","操作系统","数据库","线性代数","高等数学","英语","Java","C语言","前端","机器学习"]
        for s in subjects:
            if s in message:
                return s
        return ""

    # 资源类型关键词映射 —— 用于从学生消息识别期望的资源类型
    RESOURCE_TYPE_KEYWORDS: dict[str, list[str]] = {
        "mindmap":         ["思维导图", "脑图", "知识树", "知识图"],
        "question_bank":   ["题库", "题目", "练习题", "出题", "做题", "刷题", "测验"],
        "practical_case":  ["实训", "案例", "实战", "项目实战", "实操"],
        "micro_lecture":   ["微课", "视频", "讲解视频", "录播", "教学视频"],
        "handout":         ["讲义", "教程", "笔记", "总结", "资料"],
    }

    @classmethod
    def _detect_resource_type(cls, message: str) -> str:
        """根据学生消息关键词识别期望的资源类型，默认 handout。"""
        for rtype, keywords in cls.RESOURCE_TYPE_KEYWORDS.items():
            if any(kw in message for kw in keywords):
                return rtype
        return "handout"
