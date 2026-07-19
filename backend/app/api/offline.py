"""
离线端 API —— 供前端离线模式缓存数据
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.base import get_db
from app.models.resource import LearningResource
from app.models.student import UserProfile, ErrorRecord

router = APIRouter()


@router.get("/cache/resources/{student_id}")
async def get_offline_resources(
    student_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    获取需要缓存到前端的资源列表。
    前端 Service Worker 会拉取这些资源存储到 IndexedDB。
    """
    # 获取学生信息以匹配资源
    result = await db.execute(select(UserProfile).where(UserProfile.id == student_id))
    student = result.scalar_one_or_none()
    if not student:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="学生不存在")

    # 查询匹配学生水平的资源
    foundation = student.foundation_score
    resource_result = await db.execute(
        select(LearningResource)
        .where(
            LearningResource.cached_for_offline == True,
            LearningResource.target_foundation_min <= foundation,
            LearningResource.target_foundation_max >= foundation,
        )
        .order_by(LearningResource.created_at.desc())
        .limit(100)
    )
    resources = resource_result.scalars().all()

    # 获取错题记录
    error_result = await db.execute(
        select(ErrorRecord)
        .where(ErrorRecord.user_id == student_id)
        .order_by(ErrorRecord.created_at.desc())
        .limit(200)
    )
    errors = error_result.scalars().all()

    return {
        "student_id": student_id,
        "education_level": student.education_level,
        "cache_timestamp": None,  # 前端填充
        "resources": [
            {
                "id": r.id,
                "title": r.title,
                "resource_type": r.resource_type.value,
                "content": r.content,
                "knowledge_points": r.knowledge_points,
            }
            for r in resources
        ],
        "error_records": [
            {
                "id": e.id,
                "question": e.question,
                "correct_answer": e.correct_answer,
                "knowledge_point": e.knowledge_point,
                "error_type": e.error_type,
            }
            for e in errors
        ],
        "profile_snapshot": {
            "foundation_score": student.foundation_score,
            "weak_points": student.weak_points,
            "practical_score": student.practical_score,
        },
    }


@router.get("/cache/sync-check/{student_id}")
async def sync_check(student_id: int, db: AsyncSession = Depends(get_db)):
    """
    离线端同步检查：返回上次同步后的更新数据。
    """
    result = await db.execute(select(LearningResource).where(
        LearningResource.cached_for_offline == True
    ).order_by(LearningResource.created_at.desc()).limit(20))
    resources = result.scalars().all()

    return {
        "new_resources": len(resources),
        "last_resource_date": resources[0].created_at.isoformat() if resources else None,
        "sync_needed": len(resources) > 0,
    }
