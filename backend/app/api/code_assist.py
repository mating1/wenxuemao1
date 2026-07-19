"""
智能学科助理 API —— 根据学生专业自动匹配工具
"""
import json, traceback
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.base import get_db
from app.models.student import UserProfile
from app.services.llm_client import get_llm_client
from sqlalchemy import select
from loguru import logger

router = APIRouter()


class AssistRequest(BaseModel):
    user_id: int
    mode: str = ""   # 前端传来：explain / write / review / analyze / translate / debug / brainstorm
    content: str = ""   # 学生输入的主文本
    extra: str = ""     # 附加说明


# 专业→学科分类
def classify_major(major: str) -> str:
    m = (major or "").lower()
    cs_kw = ["计算机", "软件", "人工智能", "数据", "信息", "网络", "computer", "ai", "cs", "编程"]
    eng_kw = ["机械", "土木", "电气", "电子", "自动化", "通信", "材料", "能源", "engineer"]
    biz_kw = ["工商", "管理", "市场", "会计", "金融", "经济", "财务", "business", "commerce"]
    med_kw = ["临床", "医学", "护理", "药学", "生物医学", "medical", "medicine", "药"]
    arts_kw = ["英语", "中文", "新闻", "法学", "哲学", "历史", "政治", "社会", "翻译", "文学", "law", "history", "art"]
    sci_kw = ["数学", "物理", "化学", "生物", "统计", "math", "physics", "chemistry", "biology"]
    for kw in cs_kw:
        if kw in m: return "cs"
    for kw in eng_kw:
        if kw in m: return "engineering"
    for kw in biz_kw:
        if kw in m: return "business"
    for kw in med_kw:
        if kw in m: return "medical"
    for kw in arts_kw:
        if kw in m: return "arts"
    for kw in sci_kw:
        if kw in m: return "science"
    return "general"


MODE_PROMPTS = {
    "explain": {
        "cs": "解释以下代码的逻辑和关键点，逐段讲解：",
        "engineering": "解释以下工程技术概念/公式的原理和应用：",
        "business": "解释以下商业概念/经济原理，用通俗案例说明：",
        "medical": "解释以下医学/生理学概念，用生活类比帮助理解：",
        "arts": "解释以下概念/理论，结合经典文献或历史背景：",
        "science": "解释以下科学概念/公式，用实验或现象辅助理解：",
        "general": "用通俗易懂的方式解释以下内容：",
    },
    "write": {
        "cs": "根据需求写代码，带注释和示例：",
        "engineering": "撰写技术方案/设计文档，结构清晰：",
        "business": "撰写商业计划/市场分析/财务方案：",
        "medical": "撰写病例分析/诊疗思路/医学综述：",
        "arts": "撰写论文/评论/翻译/文献综述：",
        "science": "撰写实验报告/论文/数学推导：",
        "general": "撰写一份结构化的文档：",
    },
    "review": {
        "cs": "审查代码质量：逻辑/规范/安全/可维护性，给出改进建议：",
        "engineering": "审查技术方案的可行性和潜在问题：",
        "business": "审查商业方案的逻辑漏洞和改进方向：",
        "medical": "审查诊断思路/用药方案的合理性：",
        "arts": "审查文章/论述的逻辑、结构和质量：",
        "science": "审查实验设计/数据处理的合理性和改进建议：",
        "general": "审阅以下内容，指出问题和改进方向：",
    },
    "analyze": {
        "cs": "分析算法的时间空间复杂度，给出优化方向：",
        "engineering": "分析工程问题的关键因素和约束条件：",
        "business": "分析商业案例/SWOT/财务数据：",
        "medical": "分析病例/检验报告/症状关联：",
        "arts": "分析文章/论点/文献的内在逻辑：",
        "science": "分析数据/实验结果的统计意义：",
        "general": "深入分析以下内容：",
    },
    "debug": {
        "cs": "诊断代码错误/异常，定位问题并修正：",
        "engineering": "诊断工程故障的原因和解决方案：",
        "business": "诊断业务流程/方案中的问题：",
        "medical": "鉴诊症状差异/鉴别诊断：",
        "arts": "诊断文章/论述的结构和语法问题：",
        "science": "诊断实验过程中的错误/异常数据：",
        "general": "找出以下内容中的问题：",
    },
    "brainstorm": {
        "cs": "基于以下想法，拓展技术方案和实现路径：",
        "engineering": "基于以下思路，头脑风暴工程设计方向：",
        "business": "基于以下想法，头脑风暴商业模式和盈利方向：",
        "medical": "基于以下线索，头脑风暴可能的诊断方向：",
        "arts": "基于以下想法，头脑风暴写作/研究方向：",
        "science": "基于以下问题，头脑风暴研究假设和实验设计：",
        "general": "基于以下想法，发散思维拓展多种可能：",
    },
}


TOOLS_BY_MAJOR = {
    "cs": [
        {"mode": "explain", "icon": "🔍", "label": "代码解释", "placeholder": "粘贴代码，逐段讲解"},
        {"mode": "write", "icon": "✍️", "label": "代码编写", "placeholder": "描述需求，帮你写代码"},
        {"mode": "debug", "icon": "🐛", "label": "Debug调试", "placeholder": "描述错误+贴代码，定位bug"},
        {"mode": "analyze", "icon": "📊", "label": "算法分析", "placeholder": "分析复杂度，优化方向"},
        {"mode": "review", "icon": "👀", "label": "代码审查", "placeholder": "检查逻辑/规范/安全"},
    ],
    "engineering": [
        {"mode": "explain", "icon": "🔍", "label": "原理解释", "placeholder": "解释工程原理/公式"},
        {"mode": "write", "icon": "✍️", "label": "方案撰写", "placeholder": "写技术方案/设计文档"},
        {"mode": "review", "icon": "👀", "label": "方案审查", "placeholder": "审查方案可行性"},
        {"mode": "debug", "icon": "🐛", "label": "故障诊断", "placeholder": "分析工程故障原因"},
        {"mode": "brainstorm", "icon": "💡", "label": "设计脑暴", "placeholder": "头脑风暴工程设计方案"},
    ],
    "business": [
        {"mode": "explain", "icon": "🔍", "label": "概念解读", "placeholder": "解读商业概念/经济原理"},
        {"mode": "analyze", "icon": "📊", "label": "案例分析", "placeholder": "分析商业案例/财务数据"},
        {"mode": "write", "icon": "✍️", "label": "方案撰写", "placeholder": "写商业计划/市场分析"},
        {"mode": "review", "icon": "👀", "label": "思路审查", "placeholder": "检查方案逻辑漏洞"},
        {"mode": "brainstorm", "icon": "💡", "label": "创意脑暴", "placeholder": "头脑风暴商业模式/营销创意"},
    ],
    "medical": [
        {"mode": "explain", "icon": "🔍", "label": "知识讲解", "placeholder": "解释医学/生理概念"},
        {"mode": "analyze", "icon": "📊", "label": "病例分析", "placeholder": "分析病例/检验报告"},
        {"mode": "debug", "icon": "🐛", "label": "鉴别诊断", "placeholder": "分析症状/鉴别可能诊断"},
        {"mode": "write", "icon": "✍️", "label": "综述撰写", "placeholder": "写病例报告/医学综述"},
        {"mode": "brainstorm", "icon": "💡", "label": "诊断推理", "placeholder": "基于症状推理可能病因"},
    ],
    "arts": [
        {"mode": "write", "icon": "✍️", "label": "论文写作", "placeholder": "写论文/文献综述/翻译"},
        {"mode": "review", "icon": "👀", "label": "文章批改", "placeholder": "检查逻辑/语法/结构"},
        {"mode": "explain", "icon": "🔍", "label": "深度解读", "placeholder": "解读理论/文献/历史"},
        {"mode": "analyze", "icon": "📊", "label": "批判分析", "placeholder": "分析论点/论据/逻辑链"},
        {"mode": "brainstorm", "icon": "💡", "label": "选题脑暴", "placeholder": "头脑风暴论文选题/写作方向"},
    ],
    "science": [
        {"mode": "explain", "icon": "🔍", "label": "概念解析", "placeholder": "解释科学概念/公式/定理"},
        {"mode": "write", "icon": "✍️", "label": "实验报告", "placeholder": "写实验报告/论文"},
        {"mode": "analyze", "icon": "📊", "label": "数据分析", "placeholder": "分析实验数据/统计结果"},
        {"mode": "debug", "icon": "🐛", "label": "实验排错", "placeholder": "找出实验错误/异常"},
        {"mode": "brainstorm", "icon": "💡", "label": "研究启发", "placeholder": "头脑风暴研究假设/实验设计"},
    ],
    "general": [
        {"mode": "explain", "icon": "🔍", "label": "知识讲解", "placeholder": "讲解任何你不理解的概念"},
        {"mode": "write", "icon": "✍️", "label": "文档写作", "placeholder": "写论文/报告/方案"},
        {"mode": "review", "icon": "👀", "label": "审阅批改", "placeholder": "检查内容逻辑和质量"},
        {"mode": "brainstorm", "icon": "💡", "label": "头脑风暴", "placeholder": "发散思维，拓展思路"},
        {"mode": "debug", "icon": "🐛", "label": "问题诊断", "placeholder": "分析原因，给出解决方案"},
    ],
}


@router.post("/assist")
async def discipline_assist(data: AssistRequest, db: AsyncSession = Depends(get_db)):
    user_r = await db.execute(select(UserProfile).where(UserProfile.id == data.user_id))
    user = user_r.scalar_one_or_none()
    if not user: raise HTTPException(status_code=404, detail="用户不存在")

    category = classify_major(user.major or "")
    prompt_map = MODE_PROMPTS.get(data.mode, MODE_PROMPTS.get("explain", {}))

    # 学历层次调整语气
    level_hint = "用学术严谨的表述" if user.education_level == "undergraduate" else "用实操导向的表述，偏重实际应用"
    prompt_prefix = prompt_map.get(category, prompt_map.get("general", "请回答以下问题："))

    full_prompt = (
        f"{prompt_prefix}\n"
        f"学生输入: {data.content[:3000]}\n"
        + (f"补充说明: {data.extra[:500]}\n" if data.extra else "") +
        f"要求: 1)分层结构化回答 {level_hint} 2)用Markdown格式 3)给出3个以上知识拓展点"
    )

    try:
        messages = [
            {"role": "system", "content": f"你是{user.name}的专属学科导师。专业方向: {user.major or '通用'}。{level_hint}。回复用Markdown，重要概念加粗，代码/公式用```包裹。"},
            {"role": "user", "content": full_prompt},
        ]
        llm = get_llm_client()
        resp = await llm.chat(messages, temperature=0.6)
        # 学科助理每次使用 +1 积分
        user.points = (user.points or 0) + 1
        await db.commit()
        return {
            "content": resp.content, "category": category,
            "tools": TOOLS_BY_MAJOR.get(category, TOOLS_BY_MAJOR["general"]),
        }
    except Exception as e:
        logger.error(f"[Assist] 失败: {traceback.format_exc()}")
        return {"content": f"AI服务暂不可用: {str(e)[:200]}", "category": category, "tools": []}


@router.get("/tools/{major}")
async def get_tools(major: str = ""):
    cat = classify_major(major)
    return {"category": cat, "tools": TOOLS_BY_MAJOR.get(cat, TOOLS_BY_MAJOR["general"])}
