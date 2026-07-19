"""
学习路径模型
"""
from datetime import datetime
from sqlalchemy import String, Integer, Float, Text, DateTime, JSON, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class LearningPathway(Base):
    """自适应学习路径"""
    __tablename__ = "learning_pathways"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("user_profiles.id"), index=True)

    title: Mapped[str] = mapped_column(String(300))
    subject: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")

    # 路径进度
    total_nodes: Mapped[int] = mapped_column(Integer, default=0)
    completed_nodes: Mapped[int] = mapped_column(Integer, default=0)
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0)

    # 路径元数据
    difficulty_track: Mapped[str] = mapped_column(String(50), default="basic")
    estimated_hours: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # 关联节点
    nodes: Mapped[list["PathwayNode"]] = relationship(
        cascade="all, delete-orphan", back_populates="pathway",
        order_by="PathwayNode.order_index"
    )


class PathwayNode(Base):
    """学习路径节点"""
    __tablename__ = "pathway_nodes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pathway_id: Mapped[int] = mapped_column(ForeignKey("learning_pathways.id"), index=True)

    order_index: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(300))
    node_type: Mapped[str] = mapped_column(String(50), default="lesson")  # lesson|exercise|case|review
    description: Mapped[str] = mapped_column(Text, default="")

    # 关联资源ID列表 (JSON)
    resource_ids: Mapped[dict] = mapped_column(JSON, default=list)

    # 完成条件: 掌握度阈值
    mastery_threshold: Mapped[float] = mapped_column(Float, default=70.0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    pathway: Mapped["LearningPathway"] = relationship(back_populates="nodes")
