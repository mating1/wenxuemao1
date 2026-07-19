"""Pydantic 请求/响应模型"""
from typing import Optional
from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    login_id: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=4, max_length=128)
    role: str = Field(..., pattern="^(student|teacher)$")
    education_level: str = ""   # 学生必填 undergraduate/vocational
    major: str = ""
    grade: str = ""


class LoginRequest(BaseModel):
    login_id: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)


class ProfileUpdate(BaseModel):
    foundation_score: Optional[float] = None
    cognitive_style: Optional[str] = None
    weak_points: Optional[list] = None
    practical_score: Optional[float] = None
    learning_goals: Optional[dict] = None
    emotion_state: Optional[str] = None


class DialogueRequest(BaseModel):
    user_id: int
    message: str
    session_id: Optional[int] = None


class ResourceGenerateRequest(BaseModel):
    topic: str
    education_level: str = Field(..., pattern="^(undergraduate|vocational)$")
    foundation: float = 0.0
    resource_types: list[str] = ["handout"]
    verify: bool = True
    question_types: list[str] = []
    question_counts: dict[str, int] = {}  # 每种题型数量，如 {"choice": 2, "fill_blank": 3}
    user_id: int = 0


class ResourceVerifyRequest(BaseModel):
    resource_content: str
    resource_type: str
    topic: str
    education_level: str
    foundation: float = 0.0


class PathwayRequest(BaseModel):
    student_id: int
    subject: str = ""


class TeacherOverviewRequest(BaseModel):
    student_ids: list[int]


class ClassExerciseRequest(BaseModel):
    weak_points: list[str]
    education_level: str
    count: int = 10
