import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_DIR / ".env"
load_dotenv(ENV_FILE, override=False)
for env_key, env_value in dotenv_values(ENV_FILE).items():
    env_key = env_key.lstrip("\ufeff")
    if env_value and not os.getenv(env_key):
        os.environ[env_key] = env_value


class Settings:
    """应用配置类，所有环境变量统一从这里读取。"""

    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-ada-002")
    CHAT_MODEL: str = os.getenv("CHAT_MODEL", "qwen-plus")
    VISION_MODEL: str = os.getenv("VISION_MODEL", "qwen-vl-max")
    IMAGE_MODEL: str = os.getenv("IMAGE_MODEL", "dall-e-3")

    IMAGE_PROVIDER: str = os.getenv("IMAGE_PROVIDER", "cloud").strip().lower()
    IMAGE_PROVIDER_TIMEOUT: int = int(os.getenv("IMAGE_PROVIDER_TIMEOUT", "300"))
    CLOUD_IMAGE_SIZE: str = os.getenv("CLOUD_IMAGE_SIZE", "1024x1024")
    CLOUD_IMAGE_RESPONSE_FORMAT: str = os.getenv("CLOUD_IMAGE_RESPONSE_FORMAT", "b64_json")

    DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", OPENAI_API_KEY)
    DASHSCOPE_API_BASE: str = os.getenv("DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/api/v1")
    DASHSCOPE_IMAGE_MODEL: str = os.getenv("DASHSCOPE_IMAGE_MODEL", "wanx2.1-t2i-turbo")
    DASHSCOPE_IMAGE_SIZE: str = os.getenv("DASHSCOPE_IMAGE_SIZE", "1280*1280")
    DASHSCOPE_IMAGE_POLL_INTERVAL: float = float(os.getenv("DASHSCOPE_IMAGE_POLL_INTERVAL", "2"))
    DASHSCOPE_IMAGE_PROMPT_EXTEND: bool = os.getenv(
        "DASHSCOPE_IMAGE_PROMPT_EXTEND", "true"
    ).strip().lower() in {"1", "true", "yes", "on"}
    DASHSCOPE_IMAGE_WATERMARK: bool = os.getenv(
        "DASHSCOPE_IMAGE_WATERMARK", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}

    COMFYUI_SERVER_ADDRESS: str = os.getenv("COMFYUI_SERVER_ADDRESS", "host.docker.internal:8188")
    COMFYUI_ENABLED: bool = os.getenv("COMFYUI_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }
    ENABLE_LOCAL_PREPROCESSING: bool = os.getenv(
        "ENABLE_LOCAL_PREPROCESSING", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}

    RAG_PERSIST_DIR: str = os.getenv("RAG_PERSIST_DIR", "./knowledge_base_index")
    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "./output")
    KNOWLEDGE_BASE_DIR: str = os.getenv("KNOWLEDGE_BASE_DIR", "./knowledge_base")
    WORKFLOW_DIR: str = os.getenv("WORKFLOW_DIR", "./workflows")

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "./logs/app.log")

    @property
    def is_cloud_image_provider(self) -> bool:
        """判断当前是否使用云端图片生成。"""
        return self.IMAGE_PROVIDER == "cloud"

    @property
    def is_dashscope_image_provider(self) -> bool:
        """判断当前是否使用阿里云百炼图片生成。"""
        return self.IMAGE_PROVIDER == "dashscope"

    @property
    def is_comfyui_image_provider(self) -> bool:
        """判断当前是否使用本地 ComfyUI。"""
        return self.IMAGE_PROVIDER == "comfyui"

    @staticmethod
    def resolve_project_path(path_value: str) -> Path:
        """将相对路径解析到项目根目录，绝对路径原样返回。"""
        path = Path(path_value)
        if path.is_absolute():
            return path
        return PROJECT_DIR / path_value


settings = Settings()
