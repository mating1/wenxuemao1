"""用户与学情画像模型"""
from datetime import datetime
from enum import Enum
from typing import Optional
from sqlalchemy import String, Integer, Float, Text, DateTime, JSON, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class EducationLevel(str, Enum):
    UNDERGRADUATE = "undergraduate"
    VOCATIONAL = "vocational"


class UserRole(str, Enum):
    STUDENT = "student"
    TEACHER = "teacher"


class CognitiveStyle(str, Enum):
    VISUAL = "visual"
    AUDITORY = "auditory"
    VERBAL = "verbal"
    HANDS_ON = "hands_on"


class EmotionState(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    FRUSTRATED = "frustrated"
    CONFUSED = "confused"
    MOTIVATED = "motivated"


class UserProfile(Base):
    """用户主表——学生和教师统一"""
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    login_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), nullable=False, index=True)

    education_level: Mapped[Optional[str]] = mapped_column(String(13), nullable=True)
    major: Mapped[str] = mapped_column(String(200), default="")
    grade: Mapped[str] = mapped_column(String(50), default="")

    foundation_score: Mapped[float] = mapped_column(Float, default=0.0)
    cognitive_style: Mapped[CognitiveStyle] = mapped_column(SAEnum(CognitiveStyle), default=CognitiveStyle.VERBAL)
    weak_points: Mapped[dict] = mapped_column(JSON, default=list)
    practical_score: Mapped[float] = mapped_column(Float, default=0.0)
    learning_goals: Mapped[dict] = mapped_column(JSON, default=dict)
    emotion_state: Mapped[EmotionState] = mapped_column(SAEnum(EmotionState), default=EmotionState.NEUTRAL)
    knowledge_graph: Mapped[dict] = mapped_column(JSON, default=dict)

    # 学习积分（跟基础分/实训分独立，用于兑换皮肤等）
    points: Mapped[int] = mapped_column(Integer, default=0)
    # 已解锁的猫咪皮肤ID，JSON数组如 ["default","tabby"]
    unlocked_cats: Mapped[dict] = mapped_column(JSON, default=lambda: ["default"])
    # 当前使用的猫咪皮肤
    active_cat: Mapped[str] = mapped_column(String(50), default="default")
    # 猫咪名字
    cat_name: Mapped[str] = mapped_column(String(50), default="助学小猫")

    # 用户头像 (base64)
    avatar: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    knowledge_points: Mapped[list["KnowledgePoint"]] = relationship(cascade="all, delete-orphan", back_populates="user")
    error_records: Mapped[list["ErrorRecord"]] = relationship(cascade="all, delete-orphan", back_populates="user")


class TeacherStudent(Base):
    """教师-学生关联表"""
    __tablename__ = "teacher_students"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TeacherTask(Base):
    """教师下发的学习任务"""
    __tablename__ = "teacher_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    subject: Mapped[str] = mapped_column(String(100), default="")
    deadline: Mapped[str] = mapped_column(String(50), default="")  # 格式: "2026-07-20" 或 "3天内"
    completed: Mapped[bool] = mapped_column(default=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class StudentNotification(Base):
    """学生通知（催一催等）"""
    __tablename__ = "student_notifications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    from_user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), default=0)  # 谁发的
    from_name: Mapped[str] = mapped_column(String(100), default="")
    type: Mapped[str] = mapped_column(String(50), default="nudge")  # nudge / task / system
    content: Mapped[str] = mapped_column(Text, default="")
    is_read: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# 向后兼容别名
StudentProfile = UserProfile


class UserResource(Base):
    """用户已生成的资料记录"""
    __tablename__ = "user_resources"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    resource_type: Mapped[str] = mapped_column(String(50))
    topic: Mapped[str] = mapped_column(String(200), default="")
    content_preview: Mapped[str] = mapped_column(Text, default="")  # 前200字预览
    learned: Mapped[bool] = mapped_column(default=False)
    learned_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(100), default="")
    mastery: Mapped[float] = mapped_column(Float, default=0.0)
    depth_required: Mapped[str] = mapped_column(String(50), default="basic")
    last_reviewed: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user: Mapped["UserProfile"] = relationship(back_populates="knowledge_points")


class ErrorRecord(Base):
    __tablename__ = "error_records"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    student_answer: Mapped[str] = mapped_column(Text, default="")
    correct_answer: Mapped[str] = mapped_column(Text, default="")
    knowledge_point: Mapped[str] = mapped_column(String(200), default="")
    error_type: Mapped[str] = mapped_column(String(100), default="")
    times_wrong: Mapped[int] = mapped_column(Integer, default=1)
    resolved: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user: Mapped["UserProfile"] = relationship(back_populates="error_records")


class LearningLog(Base):
    """学习行为日志——记录用户每天的学习活动，用于统计连续学习天数"""
    __tablename__ = "learning_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)
    activity_type: Mapped[str] = mapped_column(String(50))  # chat / resource / pathway / code
    activity_detail: Mapped[str] = mapped_column(String(500), default="")
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    date_str: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD，方便按天统计
