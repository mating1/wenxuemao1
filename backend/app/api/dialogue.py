"""
对话交互 API —— 6 Agent 编排 Pipeline
流程: 采集→意图路由→诊断/生成/路径/校验→回复
"""
import traceback
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from app.db.base import get_db
from app.models.student import UserProfile, ErrorRecord, LearningLog
from app.models.dialogue import DialogueSession, DialogueMessage
from app.api.schemas import DialogueRequest
from app.agents.orchestrator import AgentOrchestrator

router = APIRouter()
_orchestrator = AgentOrchestrator()


async def _get_or_create_session(db: AsyncSession, student_id: int, session_id: int | None = None) -> DialogueSession:
    if session_id:
        result = await db.execute(select(DialogueSession).where(DialogueSession.id == session_id))
        s = result.scalar_one_or_none()
        if s: return s
    s = DialogueSession(student_id=student_id, title="新对话")
    db.add(s); await db.commit(); await db.refresh(s)
    return s


@router.post("/chat")
async def chat(data: DialogueRequest, db: AsyncSession = Depends(get_db)):
    """6 Agent 编排 Pipeline：采集→意图路由→按需诊断/生成/路径/校验→回复"""
    # 1. 学生
    r = await db.execute(select(UserProfile).where(UserProfile.id == data.user_id))
    student = r.scalar_one_or_none()
    if not student: raise HTTPException(status_code=404, detail="学生不存在")

    # 2. 会话
    session = await _get_or_create_session(db, data.user_id, data.session_id)
    hr = await db.execute(select(DialogueMessage).where(DialogueMessage.session_id == session.id).order_by(DialogueMessage.created_at.desc()).limit(6))
    history_rows = hr.scalars().all()  # Result 单次消费，先拿到列表再用
    # 构建 list[dict] 格式对话历史，供采集/诊断 Agent 使用
    dialogue_history = [
        {"role": h.role, "content": h.content}
        for h in reversed(history_rows)
    ]

    db.add(DialogueMessage(session_id=session.id, role="user", content=data.message))
    await db.commit()

    # 3. 画像
    lv = student.education_level or "undergraduate"
    profile = {"foundation_score": student.foundation_score, "cognitive_style": student.cognitive_style.value, "weak_points": student.weak_points, "practical_score": student.practical_score, "learning_goals": student.learning_goals, "emotion_state": student.emotion_state.value, "education_level": lv, "grade": student.grade or "", "major": student.major or ""}

    # 3.1 错题记录（最近 20 条未解决），供诊断 Agent 使用
    er = await db.execute(
        select(ErrorRecord)
        .where(ErrorRecord.user_id == data.user_id, ErrorRecord.resolved == False)
        .order_by(ErrorRecord.created_at.desc())
        .limit(20)
    )
    error_records = [
        {
            "knowledge_point": e.knowledge_point,
            "error_type": e.error_type,
            "times_wrong": e.times_wrong,
        }
        for e in er.scalars().all()
    ]

    # 4. 执行 6 Agent 编排
    pr = await _orchestrator.run(
        data.message, profile, lv,
        "本科" if lv == "undergraduate" else "专科高职",
        student.name,
        dialogue_history=dialogue_history,
        error_records=error_records,
    )

    # 5. 应用画像变更
    if pr.profile_update and not pr.profile_update.get("parse_error"):
        if "foundation" in pr.profile_update or "foundation_score" in pr.profile_update:
            student.foundation_score = max(0, float(pr.profile_update.get("foundation", pr.profile_update.get("foundation_score", student.foundation_score))))
        if "practical" in pr.profile_update or "practical_score" in pr.profile_update:
            student.practical_score = max(0, float(pr.profile_update.get("practical", pr.profile_update.get("practical_score", student.practical_score))))
        if pr.profile_update.get("weak_points") and isinstance(pr.profile_update["weak_points"], list): student.weak_points = pr.profile_update["weak_points"]

    # 有学习意图的对话 → 基础分+实训分至少各+1，保证越用越高
    learning_intents = {"diagnosis", "generate", "pathway", "homework"}
    if pr.intent in learning_intents:
        student.points = (student.points or 0) + 1
        if lv == "undergraduate":
            student.foundation_score = (student.foundation_score or 0) + 1
        else:
            student.practical_score = (student.practical_score or 0) + 1

    # 6. 保存消息和学习日志
    db.add(DialogueMessage(session_id=session.id, role="assistant", agent_name=" → ".join(pr.agents_used), content=pr.content, profile_update=pr.profile_update if isinstance(pr.profile_update, dict) else {}))
    
    # 记录学习行为
    from datetime import datetime as dt
    log = LearningLog(
        user_id=student.id,
        activity_type="chat",
        activity_detail=f"与{' → '.join(pr.agents_used)}对话: {data.message[:50]}",
        duration_seconds=0,
        date_str=dt.utcnow().strftime("%Y-%m-%d"),
    )
    db.add(log)
    
    await db.commit()

    resp = {"session_id": session.id, "agents_used": pr.agents_used, "agent_name": " → ".join(pr.agents_used), "content": pr.content, "intent": pr.intent, "profile_update": {"foundation_score": student.foundation_score, "practical_score": student.practical_score, "weak_points": student.weak_points}}
    if pr.diagnosis: resp["diagnosis"] = pr.diagnosis
    if pr.pathway: resp["pathway"] = pr.pathway
    if pr.resource_topic: resp["resource_topic"] = pr.resource_topic
    return resp


@router.get("/sessions")
async def list_sessions(user_id: int, db: AsyncSession = Depends(get_db)):
    """获取用户的会话列表（按更新时间倒序）"""
    r = await db.execute(
        select(DialogueSession)
        .where(DialogueSession.student_id == user_id)
        .order_by(DialogueSession.updated_at.desc())
        .limit(50)
    )
    sessions = r.scalars().all()
    return [
        {
            "id": s.id,
            "title": s.title or "新对话",
            "active_agent": s.active_agent,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(session_id: int, db: AsyncSession = Depends(get_db)):
    """获取指定会话的所有历史消息"""
    sr = await db.execute(select(DialogueSession).where(DialogueSession.id == session_id))
    session = sr.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    r = await db.execute(
        select(DialogueMessage)
        .where(DialogueMessage.session_id == session_id)
        .order_by(DialogueMessage.created_at.asc())
    )
    messages = r.scalars().all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "agent_name": m.agent_name or "",
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]
