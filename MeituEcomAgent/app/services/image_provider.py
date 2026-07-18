"""
图片生成 Provider 抽象。

生产默认使用云端 OpenAI-compatible 图片接口；本地 ComfyUI 仅作为 dev provider 保留。
"""
import base64
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import httpx
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class ImageProviderError(Exception):
    """图片生成 Provider 异常基类。"""

    pass


@dataclass(frozen=True)
class ImageGenerationRequest:
    """云端图片生成请求。"""

    positive_prompt: str
    negative_prompt: str = ""
    resolution: Tuple[int, int] = (1024, 1024)
    image_type: str = "product"
    reference_image: str = ""


class CloudImageProvider:
    """OpenAI-compatible 云端图片生成 Provider。"""

    def __init__(self, client: Optional[AsyncOpenAI] = None) -> None:
        self.client = client or AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )
        self.output_dir = settings.resolve_project_path(settings.OUTPUT_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def check_connection(self) -> bool:
        """云端 Provider 健康检查不发起付费请求，仅验证关键配置。"""
        return bool(settings.OPENAI_API_KEY and settings.OPENAI_BASE_URL and settings.IMAGE_MODEL)

    async def generate_image(self, request: ImageGenerationRequest) -> str:
        """调用云端 images.generate 并保存返回图片。"""
        prompt = self._build_prompt(request)
        size = self._select_size(request.resolution)

        try:
            logger.info(
                "调用云端图片生成 | model=%s | size=%s | type=%s",
                settings.IMAGE_MODEL,
                size,
                request.image_type,
            )
            request_kwargs = {
                "model": settings.IMAGE_MODEL,
                "prompt": prompt,
                "size": size,
                "n": 1,
            }
            if settings.CLOUD_IMAGE_RESPONSE_FORMAT:
                request_kwargs["response_format"] = settings.CLOUD_IMAGE_RESPONSE_FORMAT
            response = await self.client.images.generate(**request_kwargs)
        except Exception as exc:
            raise ImageProviderError(f"云端图片生成失败: {str(exc)}") from exc

        data = getattr(response, "data", None) or []
        if not data:
            raise ImageProviderError("云端图片生成返回空结果")

        first_image = data[0]
        image_bytes = await self._extract_image_bytes(first_image)
        return self._save_image(image_bytes, request.image_type)

    async def close(self) -> None:
        """关闭底层 HTTP 连接。"""
        await self.client.close()

    def _build_prompt(self, request: ImageGenerationRequest) -> str:
        """合并正负向 prompt，保持云端模型可读。"""
        prompt_parts = [request.positive_prompt.strip()]
        if request.negative_prompt:
            prompt_parts.append(f"Avoid: {request.negative_prompt.strip()}")
        if request.reference_image:
            prompt_parts.append("Use the uploaded product as visual reference when supported by the provider.")
        return "\n\n".join(part for part in prompt_parts if part)

    def _select_size(self, resolution: Tuple[int, int]) -> str:
        """选择云端 API 支持的图片尺寸。"""
        configured = settings.CLOUD_IMAGE_SIZE.strip()
        if configured:
            return configured

        width, height = resolution
        if width > height:
            return "1536x1024"
        if height > width:
            return "1024x1536"
        return "1024x1024"

    async def _extract_image_bytes(self, image_data: object) -> bytes:
        """兼容 b64_json 与 url 两种响应。"""
        b64_json = getattr(image_data, "b64_json", None)
        if b64_json:
            return base64.b64decode(b64_json)

        image_url = getattr(image_data, "url", None)
        if image_url:
            async with httpx.AsyncClient(timeout=settings.IMAGE_PROVIDER_TIMEOUT) as client:
                response = await client.get(image_url)
                response.raise_for_status()
                return response.content

        raise ImageProviderError("云端图片响应缺少 b64_json/url")

    def _save_image(self, image_bytes: bytes, image_type: str) -> str:
        """保存云端生成图片到输出目录。"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:18]
        filename = f"{image_type}_cloud_{timestamp}.png"
        filepath = self.output_dir / filename
        filepath.write_bytes(image_bytes)
        logger.info("云端图片已保存 | path=%s | size=%d", filepath, len(image_bytes))
        return str(filepath)
