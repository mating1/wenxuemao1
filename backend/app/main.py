"""
FastAPI 主应用入口
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.config import settings
from app.db.base import init_db
from app.api import students, dialogue, resources, pathways, teacher, offline, code_assist


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    logger.info("🚀 多智能体学习辅导系统启动中...")
    await init_db()
    logger.info("✅ 数据库初始化完成")
    yield
    from app.services.llm_client import _llm_client
    if _llm_client:
        await _llm_client.close()
    logger.info("👋 系统关闭")


app = FastAPI(
    title="本专科分层实训多智能体学习辅导系统",
    description="中国软件杯 A3赛道 — 6角色多智能体集群 + 双分支分层架构",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(students.router, prefix="/api/students", tags=["学生管理"])
app.include_router(dialogue.router, prefix="/api/dialogue", tags=["对话交互"])
app.include_router(resources.router, prefix="/api/resources", tags=["资源生成"])
app.include_router(pathways.router, prefix="/api/pathways", tags=["学习路径"])
app.include_router(teacher.router, prefix="/api/teacher", tags=["教师管理"])
app.include_router(offline.router, prefix="/api/offline", tags=["离线端"])
app.include_router(code_assist.router, prefix="/api/code", tags=["学科助理"])


@app.get("/api/health")
async def health():
    """健康检查"""
    return {"status": "ok", "version": "1.0.0"}
