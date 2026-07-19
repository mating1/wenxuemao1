"""
学习路径 API
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from app.db.base import get_db
from app.models.student import UserProfile
from app.models.pathway import LearningPathway, PathwayNode
from app.api.schemas import PathwayRequest
from app.agents.pathway_agent import PathwayAgent
from app.agents.diagnosis_agent import DiagnosisAgent

router = APIRouter()

_pathway = PathwayAgent()
_diagnosis = DiagnosisAgent()


@router.post("/generate")
async def generate_pathway(data: PathwayRequest, db: AsyncSession = Depends(get_db)):
    """为指定学生生成个性化学习路径"""
    result = await db.execute(select(UserProfile).where(UserProfile.id == data.student_id))
    student = result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail="学生不存在")

    # 先诊断
    diagnosis = await _diagnosis.diagnose(
        profile={
            "foundation_score": student.foundation_score,
            "cognitive_style": student.cognitive_style.value,
            "weak_points": student.weak_points,
            "practical_score": student.practical_score,
            "learning_goals": student.learning_goals,
            "emotion_state": student.emotion_state.value,
            "major": student.major or "",
        },
        education_level=student.education_level,
        error_records=[],
    )

    # 再规划路径
    plan = await _pathway.plan(
        profile={
            "foundation_score": student.foundation_score,
            "cognitive_style": student.cognitive_style.value,
            "weak_points": student.weak_points,
            "practical_score": student.practical_score,
            "learning_goals": student.learning_goals,
            "major": student.major or "",
        },
        diagnosis=diagnosis,
        education_level=student.education_level,
        subject=data.subject,
    )

    # 持久化
    pathway = LearningPathway(
        student_id=student.id,
        title=plan.get("title", f"{data.subject}学习路径"),
        subject=data.subject,
        description=plan.get("description", ""),
        total_nodes=len(plan.get("nodes", [])),
        difficulty_track=plan.get("difficulty_track", "basic"),
        estimated_hours=float(plan.get("estimated_hours", 10)),
    )
    db.add(pathway)
    await db.commit()
    await db.refresh(pathway)

    # 保存节点
    for node_data in plan.get("nodes", []):
        node = PathwayNode(
            pathway_id=pathway.id,
            order_index=node_data.get("order", 0),
            title=node_data.get("title", ""),
            node_type=node_data.get("type", "lesson"),
            description=node_data.get("description", ""),
            resource_ids=node_data.get("resource_ids", []),
            mastery_threshold=float(node_data.get("mastery_threshold", 70)),
        )
        db.add(node)

    await db.commit()

    logger.info(f"[Pathway] 生成路径: {pathway.title}, {pathway.total_nodes}个节点")
    return {
        "pathway_id": pathway.id,
        "title": pathway.title,
        "subject": pathway.subject,
        "description": pathway.description,
        "difficulty_track": pathway.difficulty_track,
        "estimated_hours": pathway.estimated_hours,
        "total_nodes": pathway.total_nodes,
        "nodes": plan.get("nodes", []),
        "diagnosis": diagnosis,
    }


@router.get("/{pathway_id}")
async def get_pathway(pathway_id: int, db: AsyncSession = Depends(get_db)):
    """获取学习路径及节点"""
    result = await db.execute(select(LearningPathway).where(LearningPathway.id == pathway_id))
    pathway = result.scalar_one_or_none()
    if not pathway:
        raise HTTPException(status_code=404, detail="路径不存在")

    nodes_result = await db.execute(
        select(PathwayNode)
        .where(PathwayNode.pathway_id == pathway_id)
        .order_by(PathwayNode.order_index)
    )
    nodes = nodes_result.scalars().all()

    return {
        "id": pathway.id,
        "title": pathway.title,
        "subject": pathway.subject,
        "description": pathway.description,
        "difficulty_track": pathway.difficulty_track,
        "estimated_hours": pathway.estimated_hours,
        "progress_pct": pathway.progress_pct,
        "completed_nodes": pathway.completed_nodes,
        "total_nodes": pathway.total_nodes,
        "nodes": [
            {
                "id": n.id,
                "order": n.order_index,
                "title": n.title,
                "type": n.node_type,
                "description": n.description,
                "mastery_threshold": n.mastery_threshold,
                "completed": n.completed,
            }
            for n in nodes
        ],
        "created_at": pathway.created_at.isoformat(),
    }


@router.post("/{pathway_id}/nodes/{node_id}/complete")
async def complete_node(
    pathway_id: int,
    node_id: int,
    db: AsyncSession = Depends(get_db),
):
    """标记节点完成 + 积分奖励"""
    result = await db.execute(select(PathwayNode).where(PathwayNode.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")

    node.completed = True
    from datetime import datetime
    node.completed_at = datetime.utcnow()

    # 更新路径进度
    pathway_result = await db.execute(select(LearningPathway).where(LearningPathway.id == pathway_id))
    pathway = pathway_result.scalar_one_or_none()
    if pathway:
        pathway.completed_nodes = sum(1 for n in pathway.nodes if n.completed)
        pathway.progress_pct = round(
            pathway.completed_nodes / max(pathway.total_nodes, 1) * 100, 1
        )
        # 完成节点 +3积分
        user_result = await db.execute(select(UserProfile).where(UserProfile.id == pathway.student_id))
        user = user_result.scalar_one_or_none()
        if user:
            user.points = (user.points or 0) + 3

    await db.commit()
    return {"status": "ok", "progress_pct": pathway.progress_pct if pathway else 0, "points_gained": 3}
