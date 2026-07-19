"""
教师管理 API —— 班级大屏、批量分析、专项题库、学生管理、任务下发
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from app.db.base import get_db
from app.models.student import UserProfile, TeacherStudent, TeacherTask, StudentNotification, UserRole
from app.api.schemas import TeacherOverviewRequest, ClassExerciseRequest
from app.agents.teacher_agent import TeacherAgent

router = APIRouter()
_teacher = TeacherAgent()


# ---- 教师学生管理 ----
@router.post("/students/add")
async def add_student(teacher_id: int, student_login_id: str, db: AsyncSession = Depends(get_db)):
    """教师通过学号添加学生到自己班级"""
    # 验证教师存在
    t = await db.execute(select(UserProfile).where(UserProfile.id == teacher_id, UserProfile.role == UserRole.TEACHER))
    teacher = t.scalar_one_or_none()
    if not teacher:
        raise HTTPException(status_code=404, detail="教师不存在")

    # 查找学生
    s = await db.execute(select(UserProfile).where(UserProfile.login_id == student_login_id, UserProfile.role == UserRole.STUDENT))
    student = s.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail=f"未找到学号为「{student_login_id}」的学生")

    # 检查是否已在班级中
    existing = await db.execute(
        select(TeacherStudent).where(
            TeacherStudent.teacher_id == teacher_id,
            TeacherStudent.student_id == student.id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"学生「{student.name}」已在班级中")

    db.add(TeacherStudent(teacher_id=teacher_id, student_id=student.id))
    await db.commit()
    return {"ok": True, "student": {"id": student.id, "name": student.name, "login_id": student.login_id, "education_level": student.education_level}}


@router.get("/students/{teacher_id}")
async def get_my_students(teacher_id: int, db: AsyncSession = Depends(get_db)):
    """获取教师的所有学生"""
    result = await db.execute(
        select(UserProfile)
        .join(TeacherStudent, TeacherStudent.student_id == UserProfile.id)
        .where(TeacherStudent.teacher_id == teacher_id)
        .order_by(UserProfile.created_at.desc())
    )
    students = result.scalars().all()
    return [
        {"id": s.id, "name": s.name, "login_id": s.login_id,
         "education_level": s.education_level, "major": s.major, "grade": s.grade,
         "foundation_score": s.foundation_score, "practical_score": s.practical_score,
         "emotion_state": s.emotion_state.value if s.emotion_state else "neutral"}
        for s in students
    ]


# ---- 任务管理 ----
class TaskCreate(BaseModel):
    teacher_id: int
    student_id: int
    title: str
    description: str = ""
    subject: str = ""
    deadline: str = ""

@router.post("/tasks/create")
async def create_task(data: TaskCreate, db: AsyncSession = Depends(get_db)):
    """教师给学生下发任务"""
    task = TeacherTask(
        teacher_id=data.teacher_id, student_id=data.student_id,
        title=data.title, description=data.description,
        subject=data.subject, deadline=data.deadline,
    )
    db.add(task)
    # 发通知给学生
    notif = StudentNotification(
        student_id=data.student_id, from_user_id=data.teacher_id,
        from_name="", type="task",
        content=f"新任务: {data.title}",
    )
    db.add(notif)
    await db.commit()
    return {"ok": True, "task_id": task.id}


@router.get("/tasks/{teacher_id}")
async def get_teacher_tasks(teacher_id: int, db: AsyncSession = Depends(get_db)):
    """教师查看自己下发的所有任务"""
    result = await db.execute(
        select(TeacherTask).where(TeacherTask.teacher_id == teacher_id).order_by(TeacherTask.created_at.desc())
    )
    tasks = result.scalars().all()
    return [{"id": t.id, "student_id": t.student_id, "title": t.title,
             "description": t.description, "subject": t.subject, "deadline": t.deadline,
             "completed": t.completed, "completed_at": t.completed_at.isoformat() if t.completed_at else None,
             "created_at": t.created_at.isoformat()} for t in tasks]


@router.get("/tasks/student/{student_id}")
async def get_student_tasks(student_id: int, db: AsyncSession = Depends(get_db)):
    """学生查看自己的任务"""
    result = await db.execute(
        select(TeacherTask).where(TeacherTask.student_id == student_id).order_by(TeacherTask.created_at.desc())
    )
    tasks = result.scalars().all()
    return [{"id": t.id, "title": t.title, "description": t.description,
             "deadline": t.deadline, "completed": t.completed, "created_at": t.created_at.isoformat()} for t in tasks]


@router.post("/tasks/complete/{task_id}")
async def complete_task(task_id: int, db: AsyncSession = Depends(get_db)):
    """学生标记任务完成 +3积分"""
    result = await db.execute(select(TeacherTask).where(TeacherTask.id == task_id))
    t = result.scalar_one_or_none()
    if not t: raise HTTPException(status_code=404, detail="任务不存在")
    t.completed = True
    t.completed_at = datetime.utcnow()
    # 加分
    ur = await db.execute(select(UserProfile).where(UserProfile.id == t.student_id))
    u = ur.scalar_one_or_none()
    if u: u.points = (u.points or 0) + 3
    await db.commit()
    return {"ok": True, "points_gained": 3}


# ---- 催一催 ----
@router.post("/nudge/{student_id}")
async def nudge_student(student_id: int, teacher_id: int = 0, db: AsyncSession = Depends(get_db)):
    """教师催一催学生"""
    tr = await db.execute(select(UserProfile).where(UserProfile.id == teacher_id))
    teacher = tr.scalar_one_or_none()
    notif = StudentNotification(
        student_id=student_id, from_user_id=teacher_id,
        from_name=teacher.name if teacher else "老师", type="nudge",
        content=f"{teacher.name if teacher else '老师'} 拍了拍你：该学习啦！📚",
    )
    db.add(notif)
    await db.commit()
    return {"ok": True, "msg": "已发送催一催"}


@router.get("/notifications/{student_id}")
async def get_notifications(student_id: int, db: AsyncSession = Depends(get_db)):
    """学生获取通知列表"""
    result = await db.execute(
        select(StudentNotification).where(StudentNotification.student_id == student_id)
        .order_by(StudentNotification.created_at.desc()).limit(30)
    )
    items = result.scalars().all()
    unread = sum(1 for x in items if not x.is_read)
    return {"unread": unread, "items": [
        {"id": n.id, "type": n.type, "content": n.content, "from_name": n.from_name,
         "is_read": n.is_read, "created_at": n.created_at.isoformat()} for n in items
    ]}


@router.post("/notifications/read/{student_id}")
async def mark_notifications_read(student_id: int, db: AsyncSession = Depends(get_db)):
    """全部标为已读"""
    result = await db.execute(
        select(StudentNotification).where(StudentNotification.student_id == student_id, StudentNotification.is_read == False)
    )
    for n in result.scalars().all(): n.is_read = True
    await db.commit()
    return {"ok": True}


@router.delete("/students/{teacher_id}/{student_id}")
async def remove_student(teacher_id: int, student_id: int, db: AsyncSession = Depends(get_db)):
    """教师从班级中移除学生"""
    result = await db.execute(
        select(TeacherStudent).where(
            TeacherStudent.teacher_id == teacher_id,
            TeacherStudent.student_id == student_id,
        )
    )
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="关联不存在")
    await db.delete(link)
    await db.commit()
    return {"ok": True}


@router.post("/overview")
async def class_overview(data: TeacherOverviewRequest, db: AsyncSession = Depends(get_db)):
    """全班学情总览 —— 教师大屏核心数据"""
    result = await db.execute(
        select(UserProfile).where(UserProfile.id.in_(data.student_ids))
    )
    students = result.scalars().all()

    students_data = [
        {
            "name": s.name,
            "education_level": s.education_level,
            "major": s.major or "",
            "foundation_score": s.foundation_score,
            "practical_score": s.practical_score,
            "weak_points": s.weak_points,
            "emotion_state": s.emotion_state.value,
            "cognitive_style": s.cognitive_style.value,
        }
        for s in students
    ]

    # 基础统计（不需要LLM的简单计算）
    avg_foundation = round(
        sum(s["foundation_score"] for s in students_data) / max(len(students_data), 1), 1
    )
    avg_practical = round(
        sum(s["practical_score"] for s in students_data) / max(len(students_data), 1), 1
    )
    ug_count = sum(1 for s in students_data if s["education_level"] == "undergraduate")
    voc_count = len(students_data) - ug_count

    # AI深度分析
    analysis = await _teacher.class_overview(students_data)

    # 报表数据（用于ECharts）
    report = await _teacher.export_report(students_data, analysis.get("summary", {}))

    return {
        "class_stats": {
            "total": len(students_data),
            "avg_foundation": avg_foundation,
            "avg_practical": avg_practical,
            "undergraduate_count": ug_count,
            "vocational_count": voc_count,
        },
        "analysis": analysis,
        "charts": report.get("charts", {}),
        "insights": report.get("top_insights", []),
        "urgent": report.get("urgent_interventions", []),
    }


@router.post("/exercises")
async def generate_class_exercises(
    data: ClassExerciseRequest,
    db: AsyncSession = Depends(get_db),
):
    """针对班级薄弱点生成专项题库"""
    content = await _teacher.generate_class_exercises(
        weak_points=data.weak_points,
        education_level=data.education_level,
        count=data.count,
    )
    return {"content": content, "weak_points": data.weak_points, "count": data.count}


@router.get("/students/{student_id}/report")
async def student_detailed_report(
    student_id: int,
    db: AsyncSession = Depends(get_db),
):
    """单个学生详细学情报告"""
    result = await db.execute(select(UserProfile).where(UserProfile.id == student_id))
    student = result.scalar_one_or_none()
    if not student:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="学生不存在")

    return {
        "id": student.id,
        "name": student.name,
        "education_level": student.education_level,
        "major": student.major,
        "grade": student.grade,
        "profile": {
            "foundation_score": student.foundation_score,
            "cognitive_style": student.cognitive_style.value,
            "weak_points": student.weak_points,
            "practical_score": student.practical_score,
            "learning_goals": student.learning_goals,
            "emotion_state": student.emotion_state.value,
        },
        "knowledge_graph": student.knowledge_graph,
        "updated_at": student.updated_at.isoformat(),
    }
