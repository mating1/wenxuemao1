"""
数据库基础 —— 异步SQLAlchemy基类与Session工厂
"""
import os
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

# 确保数据库文件所在目录存在
db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
if db_path.startswith("./"):
    db_path = str(Path(__file__).parent.parent.parent / db_path)  # backend/data/eduagent.db
    db_dir = str(Path(db_path).parent)
else:
    db_dir = str(Path(db_path).parent)

os.makedirs(db_dir, exist_ok=True)

# 使用绝对路径
absolute_db_url = f"sqlite+aiosqlite:///{db_path}"

engine = create_async_engine(
    absolute_db_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False} if "sqlite" in absolute_db_url else {},
)

async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入 —— 获取异步数据库会话"""
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """启动时创建所有表"""
    import app.models.student  # noqa
    import app.models.resource  # noqa
    import app.models.pathway  # noqa
    import app.models.dialogue  # noqa
    import app.models.student  # noqa  # TeacherStudent表也在这里


    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
