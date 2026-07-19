"""用户管理 API —— 注册、登录、资料库"""
from datetime import datetime, timedelta
import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from app.db.base import get_db
from app.models.student import UserProfile, UserRole, EducationLevel, CognitiveStyle, EmotionState, UserResource, LearningLog
from app.api.schemas import RegisterRequest, LoginRequest, ProfileUpdate

router = APIRouter()


@router.post("/register")
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(UserProfile).where(UserProfile.login_id == data.login_id))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="该账号已注册")

    user = UserProfile(
        name=data.name,
        login_id=data.login_id,
        password_hash=bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode(),
        role=UserRole(data.role),
        education_level=data.education_level if data.role == "student" else None,
        major=data.major,
        grade=data.grade,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    logger.info(f"新注册: {user.name} ({user.role.value})")
    return {"id": user.id, "name": user.name, "login_id": user.login_id, "role": user.role.value}


@router.post("/login")
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserProfile).where(UserProfile.login_id == data.login_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="账号不存在")
    if not bcrypt.checkpw(data.password.encode(), user.password_hash.encode()):
        raise HTTPException(status_code=401, detail="密码错误")
    logger.info(f"登录: {user.name} ({user.role.value})")
    return _format_user(user)


@router.get("/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserProfile).where(UserProfile.id == user_id))
    u = result.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    return _format_user(u)


class ChangePasswordReq(BaseModel):
    user_id: int
    old_password: str
    new_password: str


@router.post("/change_password")
async def change_password(data: ChangePasswordReq, db: AsyncSession = Depends(get_db)):
    """修改密码：校验旧密码后写入新密码哈希"""
    if len(data.new_password) < 4:
        raise HTTPException(status_code=400, detail="新密码至少4位")
    result = await db.execute(select(UserProfile).where(UserProfile.id == data.user_id))
    u = result.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not bcrypt.checkpw(data.old_password.encode(), u.password_hash.encode()):
        raise HTTPException(status_code=401, detail="原密码错误")
    u.password_hash = bcrypt.hashpw(data.new_password.encode(), bcrypt.gensalt()).decode()
    await db.commit()
    logger.info(f"用户 {u.login_id} 修改密码成功")
    return {"ok": True}


@router.put("/{user_id}/profile")
async def update_profile(user_id: int, update: ProfileUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(UserProfile).where(UserProfile.id == user_id))
    u = result.scalar_one_or_none()
    if not u: raise HTTPException(status_code=404, detail="用户不存在")
    if update.foundation_score is not None: u.foundation_score = update.foundation_score
    if update.cognitive_style is not None: u.cognitive_style = CognitiveStyle(update.cognitive_style)
    if update.weak_points is not None: u.weak_points = update.weak_points
    if update.practical_score is not None: u.practical_score = update.practical_score
    if update.learning_goals is not None: u.learning_goals = update.learning_goals
    if update.emotion_state is not None: u.emotion_state = EmotionState(update.emotion_state)
    await db.commit()
    return {"status": "ok"}


@router.get("")
async def list_users(role: str = "", db: AsyncSession = Depends(get_db)):
    query = select(UserProfile)
    if role: query = query.where(UserProfile.role == UserRole(role))
    result = await db.execute(query.order_by(UserProfile.created_at.desc()))
    return [{"id": u.id, "name": u.name, "login_id": u.login_id, "role": u.role.value,
             "education_level": u.education_level,
             "foundation_score": u.foundation_score, "practical_score": u.practical_score}
            for u in result.scalars().all()]


# ---- 猫咪皮肤系统 ----
CAT_SKINS = [
    {"id": "default", "name": "小白", "emoji": "🐱", "color": "#FFFFFF", "cost": 0, "desc": "初始小白猫"},
    {"id": "tabby", "name": "小橘", "emoji": "🐈", "color": "#F97316", "cost": 30, "desc": "橘色虎斑猫"},
    {"id": "black", "name": "小黑", "emoji": "🐈‍⬛", "color": "#374151", "cost": 30, "desc": "酷酷的黑猫"},
    {"id": "calico", "name": "小花", "emoji": "😺", "color": "#EC4899", "cost": 50, "desc": "三花小公主"},
    {"id": "siamese", "name": "暹罗", "emoji": "😸", "color": "#8B5CF6", "cost": 80, "desc": "暹罗贵族猫"},
    {"id": "robot", "name": "机甲", "emoji": "🤖", "color": "#06B6D4", "cost": 150, "desc": "赛博机甲猫"},
    {"id": "space", "name": "星空", "emoji": "🌌", "color": "#6366F1", "cost": 200, "desc": "星空幻彩猫"},
]

@router.get("/cats")
async def get_cat_skins():
    """获取所有猫咪皮肤列表"""
    return {"skins": CAT_SKINS}

@router.get("/cats/{user_id}")
async def get_user_cats(user_id: int, db: AsyncSession = Depends(get_db)):
    """获取用户的猫咪状态"""
    result = await db.execute(select(UserProfile).where(UserProfile.id == user_id))
    u = result.scalar_one_or_none()
    if not u: raise HTTPException(status_code=404, detail="用户不存在")
    return {
        "points": u.points,
        "unlocked_cats": u.unlocked_cats or ["default"],
        "active_cat": u.active_cat or "default",
        "cat_name": u.cat_name or "助学小猫",
        "all_skins": CAT_SKINS,
    }

@router.post("/cats/unlock")
async def unlock_cat(user_id: int, cat_id: str, db: AsyncSession = Depends(get_db)):
    """用积分解锁猫咪皮肤"""
    result = await db.execute(select(UserProfile).where(UserProfile.id == user_id))
    u = result.scalar_one_or_none()
    if not u: raise HTTPException(status_code=404, detail="用户不存在")
    skin = next((s for s in CAT_SKINS if s["id"] == cat_id), None)
    if not skin: raise HTTPException(status_code=404, detail="皮肤不存在")
    if cat_id in (u.unlocked_cats or ["default"]): raise HTTPException(status_code=409, detail="已解锁")
    if u.points < skin["cost"]: raise HTTPException(status_code=400, detail=f"积分不足，需要{skin['cost']}积分")
    u.points -= skin["cost"]
    unlocked = list(u.unlocked_cats or ["default"])
    unlocked.append(cat_id)
    u.unlocked_cats = unlocked
    await db.commit()
    return {"points": u.points, "unlocked_cats": unlocked, "unlocked": True}

@router.post("/cats/equip")
async def equip_cat(user_id: int, cat_id: str, db: AsyncSession = Depends(get_db)):
    """切换当前猫咪皮肤"""
    result = await db.execute(select(UserProfile).where(UserProfile.id == user_id))
    u = result.scalar_one_or_none()
    if not u: raise HTTPException(status_code=404, detail="用户不存在")
    if cat_id not in (u.unlocked_cats or ["default"]): raise HTTPException(status_code=400, detail="未解锁该皮肤")
    u.active_cat = cat_id
    await db.commit()
    return {"active_cat": cat_id}

class RenameCatReq(BaseModel):
    user_id: int
    name: str

@router.post("/cats/rename")
async def rename_cat(data: RenameCatReq, db: AsyncSession = Depends(get_db)):
    """修改猫咪名字"""
    if not data.name or len(data.name.strip()) == 0:
        raise HTTPException(status_code=400, detail="名字不能为空")
    if len(data.name) > 20:
        raise HTTPException(status_code=400, detail="名字不能超过20个字")
    result = await db.execute(select(UserProfile).where(UserProfile.id == data.user_id))
    u = result.scalar_one_or_none()
    if not u: raise HTTPException(status_code=404, detail="用户不存在")
    u.cat_name = data.name.strip()
    await db.commit()
    return {"cat_name": u.cat_name}

# ---- 用户资料库 ----
class SaveResourceReq(BaseModel):
    user_id: int
    title: str = ""
    resource_type: str = ""
    topic: str = ""
    content_preview: str = ""


@router.post("/resources/save")
async def save_resource(data: SaveResourceReq, db: AsyncSession = Depends(get_db)):
    """保存生成的资料到用户资料库"""
    r = UserResource(
        user_id=data.user_id, title=data.title, resource_type=data.resource_type,
        topic=data.topic, content_preview=data.content_preview[:200],
    )
    db.add(r)
    
    # 记录资源生成行为
    type_map = {
        "handout": "讲义",
        "mindmap": "思维导图",
        "micro_lecture": "微课",
        "practical_case": "实训案例",
        "question_bank": "题库",
    }
    type_name = type_map.get(data.resource_type, data.resource_type)
    log = LearningLog(
        user_id=data.user_id,
        activity_type="resource",
        activity_detail=f"生成{type_name}: {data.title[:50]}",
        duration_seconds=0,
        date_str=datetime.utcnow().strftime("%Y-%m-%d"),
    )
    db.add(log)
    
    await db.commit()
    return {"id": r.id, "saved": True}


class AvatarUpload(BaseModel):
    image: str = ""

@router.post("/avatar/{user_id}")
async def upload_avatar(user_id: int, data: AvatarUpload, db: AsyncSession = Depends(get_db)):
    """上传头像（base64）"""
    if len(data.image) > 500000: raise HTTPException(status_code=400, detail="图片过大")
    result = await db.execute(select(UserProfile).where(UserProfile.id == user_id))
    u = result.scalar_one_or_none()
    if not u: raise HTTPException(status_code=404, detail="用户不存在")
    u.avatar = data.image
    await db.commit()
    return {"ok": True, "avatar": data.image[:100]}


class QuizAnswerReq(BaseModel):
    user_id: int
    question: str = ""
    student_answer: str = ""
    correct_answer: str = ""
    knowledge_point: str = ""
    error_type: str = ""  # 概念不清/计算错误/粗心/等等
    question_type: str = ""  # choice/true_false/fill_blank/short_answer/coding


@router.post("/quiz/answer")
async def quiz_answer(data: QuizAnswerReq, db: AsyncSession = Depends(get_db)):
    """答题积分：答对+1分，答错记录到 ErrorRecord 供诊断 Agent 使用"""
    from app.models.student import ErrorRecord

    result = await db.execute(select(UserProfile).where(UserProfile.id == data.user_id))
    u = result.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")

    student_answer = data.student_answer.strip()
    correct_answer = data.correct_answer.strip()

    # 判断对错
    correct = student_answer.lower() == correct_answer.lower()

    if correct:
        u.points = (u.points or 0) + 1
        await db.commit()
        return {"points": u.points, "gained": 1, "correct": True}

    # 答错了：写入/更新 ErrorRecord + 同步更新用户 weak_points
    kp = data.knowledge_point.strip() or data.question[:50]
    et = data.error_type.strip() or "概念不清"

    existing = await db.execute(
        select(ErrorRecord).where(
            ErrorRecord.user_id == data.user_id,
            ErrorRecord.knowledge_point == kp,
        )
    )
    record = existing.scalar_one_or_none()
    if record:
        record.times_wrong = (record.times_wrong or 1) + 1
        record.question = data.question
        record.student_answer = data.student_answer
        record.correct_answer = data.correct_answer
    else:
        db.add(ErrorRecord(
            user_id=data.user_id,
            question=data.question,
            student_answer=data.student_answer,
            correct_answer=data.correct_answer,
            knowledge_point=kp,
            error_type=et,
            times_wrong=1,
            resolved=False,
        ))

    # 同步更新用户画像的 weak_points（供 Dashboard 立即展示）
    current_weak = list(u.weak_points) if isinstance(u.weak_points, list) else []
    if kp not in current_weak:
        current_weak.append(kp)
        u.weak_points = current_weak

    await db.commit()
    return {"points": u.points or 0, "gained": 0, "correct": False, "weak_points": current_weak, "msg": "答错了，已记录到错题本"}


@router.get("/resources/{user_id}")
async def get_my_resources(user_id: int, db: AsyncSession = Depends(get_db)):
    """获取用户的资料库"""
    result = await db.execute(
        select(UserResource).where(UserResource.user_id == user_id).order_by(UserResource.created_at.desc()).limit(100)
    )
    items = result.scalars().all()
    learned_count = sum(1 for x in items if x.learned)
    total_points = learned_count * 4  # 每个已学资料=4积分
    return {
        "items": [{"id": r.id, "title": r.title, "resource_type": r.resource_type,
                    "topic": r.topic, "content_preview": r.content_preview,
                    "learned": r.learned, "learned_at": r.learned_at.isoformat() if r.learned_at else None,
                    "created_at": r.created_at.isoformat()}
                  for r in items],
        "stats": {"total": len(items), "learned": learned_count, "total_points": total_points},
    }


@router.post("/resources/learn/{resource_id}")
async def mark_learned(resource_id: int, user_id: int = 0, db: AsyncSession = Depends(get_db)):
    """标记资料为已学习，同时给用户加分"""
    result = await db.execute(select(UserResource).where(UserResource.id == resource_id))
    r = result.scalar_one_or_none()
    if not r: raise HTTPException(status_code=404, detail="资料不存在")
    if r.learned: raise HTTPException(status_code=409, detail="已标记过")

    r.learned = True
    r.learned_at = datetime.utcnow()

    # 给用户加分：理论类资料+基础分，实操类+实训分
    theory_types = ["handout", "mindmap", "micro_lecture"]
    practical_types = ["practical_case", "question_bank"]

    user_result = await db.execute(select(UserProfile).where(UserProfile.id == r.user_id))
    user = user_result.scalar_one_or_none()
    if user:
        if r.resource_type in theory_types:
            user.foundation_score = user.foundation_score + 2
        elif r.resource_type in practical_types:
            user.practical_score = user.practical_score + 2
        else:
            user.foundation_score = user.foundation_score + 1
            user.practical_score = user.practical_score + 1
        # 学完一份资料 +4 积分
        user.points = (user.points or 0) + 4

    # 记录学习行为
    type_map = {
        "handout": "讲义",
        "mindmap": "思维导图",
        "micro_lecture": "微课",
        "practical_case": "实训案例",
        "question_bank": "题库",
    }
    type_name = type_map.get(r.resource_type, r.resource_type)
    log = LearningLog(
        user_id=r.user_id,
        activity_type="learn",
        activity_detail=f"学习{type_name}: {r.title[:50]}",
        duration_seconds=0,
        date_str=datetime.utcnow().strftime("%Y-%m-%d"),
    )
    db.add(log)

    await db.commit()
    return {"learned": True, "foundation_score": user.foundation_score if user else 0,
            "practical_score": user.practical_score if user else 0}


def _format_user(u: UserProfile) -> dict:
    is_student = u.role == UserRole.STUDENT
    base = {
        "id": u.id, "name": u.name, "login_id": u.login_id, "role": u.role.value,
        "avatar": u.avatar or "",
        "points": u.points or 0,
        "weak_points": u.weak_points or [],
        "foundation_score": u.foundation_score,
        "practical_score": u.practical_score,
        "profile": {
            "foundation_score": u.foundation_score, "cognitive_style": u.cognitive_style.value if u.cognitive_style else "verbal",
            "weak_points": u.weak_points, "practical_score": u.practical_score,
            "learning_goals": u.learning_goals, "emotion_state": u.emotion_state.value if u.emotion_state else "neutral",
        },
    }
    if is_student:
        base["education_level"] = u.education_level or "undergraduate"
        base["major"] = u.major
        base["grade"] = u.grade
    return base


@router.get("/{user_id}/learning-stats")
async def get_learning_stats(user_id: int, db: AsyncSession = Depends(get_db)):
    """获取用户学习统计：连续学习天数、总学习天数、最近学习记录等"""
    u = await db.get(UserProfile, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 查询所有学习日志，按日期去重
    r = await db.execute(
        select(LearningLog)
        .where(LearningLog.user_id == user_id)
        .order_by(LearningLog.created_at.desc())
        .limit(200)
    )
    logs = r.scalars().all()

    # 按日期去重
    unique_dates = set()
    date_list = []
    for log in logs:
        if log.date_str not in unique_dates:
            unique_dates.add(log.date_str)
            date_list.append(log.date_str)

    # 计算连续学习天数
    streak = 0
    if date_list:
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        # 检查今天是否有学习记录
        current_date = datetime.utcnow().date()
        # 如果今天还没学，从昨天开始算
        if today_str not in unique_dates:
            current_date = current_date - timedelta(days=1)
        
        # 向前数连续天数
        while True:
            date_str = current_date.strftime("%Y-%m-%d")
            if date_str in unique_dates:
                streak += 1
                current_date = current_date - timedelta(days=1)
            else:
                break

    # 最近5条学习记录
    recent_logs = logs[:5]

    return {
        "streak_days": streak,
        "total_learning_days": len(unique_dates),
        "total_logs": len(logs),
        "recent_activities": [
            {
                "id": log.id,
                "type": log.activity_type,
                "detail": log.activity_detail,
                "created_at": log.created_at.isoformat(),
                "date": log.date_str,
            }
            for log in recent_logs
        ],
    }


@router.post("/{user_id}/learning-log")
async def add_learning_log(user_id: int, data: dict, db: AsyncSession = Depends(get_db)):
    """记录用户学习行为"""
    u = await db.get(UserProfile, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="用户不存在")

    activity_type = data.get("activity_type", "chat")
    activity_detail = data.get("activity_detail", "")
    duration = data.get("duration_seconds", 0)

    log = LearningLog(
        user_id=user_id,
        activity_type=activity_type,
        activity_detail=activity_detail[:500],
        duration_seconds=duration,
        date_str=datetime.utcnow().strftime("%Y-%m-%d"),
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)

    return {"id": log.id, "message": "记录成功"}
