"""
资源生成与校验 API
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json
from loguru import logger

from app.db.base import get_db
from app.models.student import StudentProfile, UserProfile, UserResource
from app.models.resource import LearningResource, ResourceType, ResourceDifficulty, EducationBranch
from app.api.schemas import ResourceGenerateRequest, ResourceVerifyRequest
from app.agents.generation_agent import GenerationAgent
from app.agents.verification_agent import VerificationAgent

router = APIRouter()

_generation = GenerationAgent()
_verification = VerificationAgent()


@router.post("/generate")
async def generate_resources(data: ResourceGenerateRequest, db: AsyncSession = Depends(get_db)):
    """
    生成学习资源（核心接口）。
    支持双分支（本科/专科）和5类资源类型。
    可选开启辩论校验。
    """
    branch = EducationBranch.UNDERGRADUATE if data.education_level == "undergraduate" else EducationBranch.VOCATIONAL
    results = {}
    saved_resources = []

    # 查询学生专业信息，以便生成专业相关的资源
    student_major = ""
    if data.user_id > 0:
        sr = await db.execute(select(UserProfile).where(UserProfile.id == data.user_id))
        student = sr.scalar_one_or_none()
        if student:
            student_major = student.major or ""

    for rtype in data.resource_types:
        logger.info(f"[Resource] 生成 {rtype}, 分支={branch.value}, 主题={data.topic}, 专业={student_major}")
        try:
            content = await _generation.generate(
                resource_type=rtype,
                topic=data.topic,
                education_level=data.education_level,
                foundation=data.foundation,
                question_types=data.question_types if rtype == "question_bank" else None,
                question_counts=data.question_counts if rtype == "question_bank" and data.question_counts else None,
                major=student_major,
            )
        except Exception as e:
            logger.error(f"[Resource] 生成失败 {rtype}: {e}")
            content = f"[生成失败: {e}]"

        # 辩论校验
        verify_result = None
        quality_score = 7.0   # 默认分（生成成功即给基准分）
        debate_rounds = 0
        # 最终入库的内容：默认为原始生成内容；若校验输出修正版，则用修正版
        final_content = content
        if data.verify and "[生成失败" not in content:
            try:
                verify_result = await _verification.verify(
                    resource_content=content,
                    resource_type=rtype,
                    topic=data.topic,
                    education_level=data.education_level,
                    foundation=data.foundation,
                    major=student_major,
                )
                quality = verify_result.get("arbiter", {}).get("quality_assessment", {})
                if quality and quality.get("overall"):
                    quality_score = float(quality["overall"])
                    debate_rounds = 2
                # 使用 arbiter 输出的修正版资源作为最终内容（三方辩论校验的产物）
                # 阈值 10 字符：过滤空值/异常短内容，但允许简短修正版
                revised = verify_result.get("revised_content")
                if revised and isinstance(revised, str) and len(revised) > 10:
                    final_content = revised
                logger.info(f"[Resource] 校验完成 {rtype}: 质量={quality_score}/10, 使用修正版内容({len(final_content)}字符)")
            except Exception as e:
                logger.warning(f"[Resource] 校验失败 {rtype}: {str(e)[:200]}")
                # 校验失败不降分，保留默认分

        results[rtype] = {
            "content": final_content,
            "verification": verify_result,
            "quality_score": quality_score,
            "debate_rounds": debate_rounds,
        }

        # 持久化保存（用 final_content，若校验输出修正版则存的是修正版）
        resource = LearningResource(
            title=f"{data.topic} - {rtype}",
            resource_type=ResourceType(rtype),
            difficulty=ResourceDifficulty.BASIC if data.foundation < 40
                       else ResourceDifficulty.INTERMEDIATE if data.foundation < 70
                       else ResourceDifficulty.ADVANCED,
            branch=branch,
            content=final_content,
            summary=final_content[:300],
            knowledge_points=[data.topic],
            generated_by_agent="资源生成Agent",
            debate_rounds=debate_rounds,
            quality_score=quality_score,
            target_foundation_min=max(0, data.foundation - 15),
            target_foundation_max=min(100, data.foundation + 15),
            cached_for_offline=True,
        )
        db.add(resource)
        saved_resources.append(resource)

    await db.commit()

    # 自动存入用户资料库+加积分
    if data.user_id > 0:
        for i, rtype in enumerate(data.resource_types):
            c = results.get(rtype, {}).get("content", "")
            db.add(UserResource(user_id=data.user_id, title=f"{data.topic} - {rtype}",
                resource_type=rtype, topic=data.topic, content_preview=c[:200]))
        # 每生成一份资源 +2 积分
        points_gain = len(data.resource_types) * 2
        up_result = await db.execute(select(UserProfile).where(UserProfile.id == data.user_id))
        u = up_result.scalar_one_or_none()
        if u:
            u.points = (u.points or 0) + points_gain
        await db.commit()

    return {
        "topic": data.topic,
        "education_level": data.education_level,
        "branch": branch.value,
        "resources": results,
        "saved_ids": [r.id for r in saved_resources],
    }


@router.post("/verify")
async def verify_resource(data: ResourceVerifyRequest):
    """单独校验已有资源"""
    return await _verification.verify(
        resource_content=data.resource_content,
        resource_type=data.resource_type,
        topic=data.topic,
        education_level=data.education_level,
        foundation=data.foundation,
    )


@router.get("/{resource_id}")
async def get_resource(resource_id: int, db: AsyncSession = Depends(get_db)):
    """获取已生成的资源"""
    result = await db.execute(select(LearningResource).where(LearningResource.id == resource_id))
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=404, detail="资源不存在")
    return {
        "id": resource.id,
        "title": resource.title,
        "resource_type": resource.resource_type.value,
        "branch": resource.branch.value,
        "content": resource.content,
        "quality_score": resource.quality_score,
        "debate_rounds": resource.debate_rounds,
        "created_at": resource.created_at.isoformat(),
    }


@router.get("")
async def list_resources(
    branch: str = "",
    resource_type: str = "",
    db: AsyncSession = Depends(get_db),
):
    """按分支和类型筛选资源"""
    query = select(LearningResource)
    if branch:
        query = query.where(LearningResource.branch == EducationBranch(branch))
    if resource_type:
        query = query.where(LearningResource.resource_type == ResourceType(resource_type))
    query = query.order_by(LearningResource.created_at.desc()).limit(50)

    result = await db.execute(query)
    resources = result.scalars().all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "resource_type": r.resource_type.value,
            "branch": r.branch.value,
            "difficulty": r.difficulty.value,
            "quality_score": r.quality_score,
            "knowledge_points": r.knowledge_points,
            "created_at": r.created_at.isoformat(),
        }
        for r in resources
    ]


@router.post("/compare")
async def generate_dual_branch(data: ResourceGenerateRequest, db: AsyncSession = Depends(get_db)):
    """
    🔥 独有功能：同时生成本科版和专科版，供答辩时对比演示。
    两份资源都会持久化保存到数据库。
    """
    ug_request = ResourceGenerateRequest(
        topic=data.topic,
        education_level="undergraduate",
        foundation=data.foundation,
        resource_types=data.resource_types,
        verify=data.verify,
    )
    # 手动处理本科分支
    branch = EducationBranch.UNDERGRADUATE
    ug_results = {}
    for rtype in data.resource_types:
        try:
            qt = data.question_types if rtype == "question_bank" else None
            content = await _generation.generate(
                resource_type=rtype, topic=data.topic,
                education_level="undergraduate", foundation=data.foundation,
                use_claude=False, question_types=qt,
            )
        except Exception as e:
            content = f"[生成失败: {e}]"
        ug_results[rtype] = {"content": content}
        resource = LearningResource(
            title=f"[本科] {data.topic} - {rtype}",
            resource_type=ResourceType(rtype),
            difficulty=ResourceDifficulty.BASIC if data.foundation < 40
                       else ResourceDifficulty.INTERMEDIATE if data.foundation < 70
                       else ResourceDifficulty.ADVANCED,
            branch=branch,
            content=content,
            summary=content[:300],
            knowledge_points=[data.topic],
            generated_by_agent="资源生成Agent",
            target_foundation_min=max(0, data.foundation - 15),
            target_foundation_max=min(100, data.foundation + 15),
            cached_for_offline=True,
        )
        db.add(resource)

    await db.commit()

    # 专科分支
    branch = EducationBranch.VOCATIONAL
    voc_results = {}
    for rtype in data.resource_types:
        try:
            qt = data.question_types if rtype == "question_bank" else None
            content = await _generation.generate(
                resource_type=rtype, topic=data.topic,
                education_level="vocational", foundation=data.foundation,
                use_claude=False, question_types=qt,
            )
        except Exception as e:
            content = f"[生成失败: {e}]"
        voc_results[rtype] = {"content": content}
        resource = LearningResource(
            title=f"[专科] {data.topic} - {rtype}",
            resource_type=ResourceType(rtype),
            difficulty=ResourceDifficulty.BASIC if data.foundation < 40
                       else ResourceDifficulty.INTERMEDIATE if data.foundation < 70
                       else ResourceDifficulty.ADVANCED,
            branch=branch,
            content=content,
            summary=content[:300],
            knowledge_points=[data.topic],
            generated_by_agent="资源生成Agent",
            target_foundation_min=max(0, data.foundation - 15),
            target_foundation_max=min(100, data.foundation + 15),
            cached_for_offline=True,
        )
        db.add(resource)

    await db.commit()

    return {
        "topic": data.topic,
        "undergraduate": {"resources": ug_results, "education_level": "undergraduate"},
        "vocational": {"resources": voc_results, "education_level": "vocational"},
    }
