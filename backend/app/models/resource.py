"""
学习资源模型 —— 5类资源与生成记录
"""
from datetime import datetime
from enum import Enum
from sqlalchemy import String, Integer, Float, Text, DateTime, JSON, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ResourceType(str, Enum):
    HANDOUT = "handout"           # 讲义
    MINDMAP = "mindmap"           # 思维导图
    QUESTION_BANK = "question_bank"  # 题库
    PRACTICAL_CASE = "practical_case"  # 实训案例
    MICRO_LECTURE = "micro_lecture"  # 微课脚本


class ResourceDifficulty(str, Enum):
    BASIC = "basic"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class EducationBranch(str, Enum):
    """资源分支标识 —— 双分支核心"""
    UNDERGRADUATE = "undergraduate"
    VOCATIONAL = "vocational"
    COMMON = "common"  # 通用资源


class LearningResource(Base):
    """学习资源主表"""
    __tablename__ = "learning_resources"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 资源元信息
    title: Mapped[str] = mapped_column(String(300))
    resource_type: Mapped[ResourceType] = mapped_column(SAEnum(ResourceType), index=True)
    difficulty: Mapped[ResourceDifficulty] = mapped_column(
        SAEnum(ResourceDifficulty), default=ResourceDifficulty.BASIC
    )
    branch: Mapped[EducationBranch] = mapped_column(
        SAEnum(EducationBranch), default=EducationBranch.COMMON, index=True
    )

    # 内容
    content: Mapped[str] = mapped_column(Text, default="")  # 文本/JSON/Markdown
    summary: Mapped[str] = mapped_column(Text, default="")

    # 关联知识点
    knowledge_points: Mapped[dict] = mapped_column(JSON, default=list)
    subject: Mapped[str] = mapped_column(String(100), default="")

    # 生成元数据
    generated_by_agent: Mapped[str] = mapped_column(String(100), default="")
    debate_rounds: Mapped[int] = mapped_column(Integer, default=0)  # 辩论校验轮次
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)  # 质量评分
    generation_prompt: Mapped[str] = mapped_column(Text, default="")  # 生成Prompt快照

    # 适用学生画像匹配
    target_foundation_min: Mapped[float] = mapped_column(Float, default=0.0)
    target_foundation_max: Mapped[float] = mapped_column(Float, default=100.0)
    target_cognitive_styles: Mapped[dict] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # 离线缓存标记
    cached_for_offline: Mapped[bool] = mapped_column(default=False)
