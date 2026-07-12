"""
配置管理模块 - 使用 python-dotenv 加载 .env 中的所有配置项
"""
import os
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()


class Settings:
    """应用配置类，以类属性方式暴露所有配置项"""

    # OpenAI 相关配置
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    # ComfyUI 服务地址
    COMFYUI_SERVER_ADDRESS: str = os.getenv("COMFYUI_SERVER_ADDRESS", "host.docker.internal:8188")

    # 模型配置
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-ada-002")
    CHAT_MODEL: str = os.getenv("CHAT_MODEL", "qwen-plus")
    VISION_MODEL: str = os.getenv("VISION_MODEL", "qwen-vl-max")
    IMAGE_MODEL: str = os.getenv("IMAGE_MODEL", "dall-e-3")

    # 路径配置
    RAG_PERSIST_DIR: str = os.getenv("RAG_PERSIST_DIR", "./knowledge_base_index")
    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "./output")
    KNOWLEDGE_BASE_DIR: str = os.getenv("KNOWLEDGE_BASE_DIR", "./knowledge_base")
    WORKFLOW_DIR: str = os.getenv("WORKFLOW_DIR", "./workflows")

    # 日志配置
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "./logs/app.log")


# 全局配置实例
settings = Settings()
