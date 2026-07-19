"""
全局配置 —— 从 .env 读取，提供统一配置入口
"""
import os
from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # API Keys
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    anthropic_api_key: str = ""
    xunfei_app_id: str = ""
    xunfei_api_key: str = ""
    xunfei_api_secret: str = ""
    dashscope_api_key: str = ""

    # 数据库
    database_url: str = "sqlite+aiosqlite:///./data/eduagent.db"
    chroma_persist_dir: str = "./data/chroma"

    # Redis
    redis_url: str = ""

    # 服务
    debug: bool = True
    secret_key: str = "dev-secret-change-in-production"
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # LLM 默认配置
    default_model: str = "deepseek"
    fallback_model: str = "dashscope"

    # 生成控制
    max_debate_rounds: int = 2
    resource_cache_hours: int = 72

    model_config = {
        "env_file": os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        "env_file_encoding": "utf-8",
        "extra": "allow",
    }

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
