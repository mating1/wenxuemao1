"""
对话会话模型
"""
from datetime import datetime
from sqlalchemy import String, Integer, Text, DateTime, JSON, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.student import EmotionState


class DialogueSession(Base):
    """对话会话"""
    __tablename__ = "dialogue_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)

    title: Mapped[str] = mapped_column(String(300), default="")
    # 当前活跃的 Agent
    active_agent: Mapped[str] = mapped_column(String(100), default="collection")
    # 会话上下文快照
    context_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    messages: Mapped[list["DialogueMessage"]] = relationship(
        cascade="all, delete-orphan", back_populates="session",
        order_by="DialogueMessage.created_at"
    )


class DialogueMessage(Base):
    """对话消息"""
    __tablename__ = "dialogue_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("dialogue_sessions.id"), index=True)

    role: Mapped[str] = mapped_column(String(50))  # user | agent | system
    agent_name: Mapped[str] = mapped_column(String(100), default="")
    content: Mapped[str] = mapped_column(Text)

    # 消息触发的学情更新 (JSON快照)
    profile_update: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["DialogueSession"] = relationship(back_populates="messages")
