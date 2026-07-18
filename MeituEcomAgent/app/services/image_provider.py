"""
图片生成 Provider 抽象。

生产默认使用云端 OpenAI-compatible 图片接口；本地 ComfyUI 仅作为 dev provider 保留。
"""
import base64
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple

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


class DashScopeImageProvider:
    """阿里云百炼通义万相图片生成 Provider。"""

    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        self.client = client
        self.output_dir = settings.resolve_project_path(settings.OUTPUT_DIR)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def check_connection(self) -> bool:
        """百炼健康检查不发起付费请求，仅验证关键配置。"""
        return bool(
            settings.DASHSCOPE_API_KEY
            and settings.DASHSCOPE_API_BASE
            and settings.DASHSCOPE_IMAGE_MODEL
        )

    async def generate_image(self, request: ImageGenerationRequest) -> str:
        """创建百炼异步生图任务，轮询完成后下载临时图片 URL。"""
        task_id = await self._create_task(request)
        image_url = await self._wait_for_task(task_id)
        image_bytes = await self._download_image(image_url)
        return self._save_image(image_bytes, request.image_type)

    async def close(self) -> None:
        """关闭注入的 HTTP 客户端。"""
        if self.client is not None:
            await self.client.aclose()

    async def _create_task(self, request: ImageGenerationRequest) -> str:
        """调用百炼创建异步文生图任务。"""
        input_data = {
            "prompt": self._build_prompt(request),
        }
        if request.negative_prompt:
            input_data["negative_prompt"] = request.negative_prompt.strip()
        payload = {
            "model": settings.DASHSCOPE_IMAGE_MODEL,
            "input": input_data,
            "parameters": self._build_parameters(),
        }
        response_data = await self._request_json(
            "POST",
            f"{self._api_base}/services/aigc/text2image/image-synthesis",
            json=payload,
            headers={
                **self._auth_headers,
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            },
        )
        task_id = response_data.get("output", {}).get("task_id")
        if not task_id:
            raise ImageProviderError("百炼图片任务创建失败：响应缺少 task_id")
        logger.info(
            "百炼图片任务已创建 | task_id=%s | model=%s | size=%s",
            task_id,
            settings.DASHSCOPE_IMAGE_MODEL,
            settings.DASHSCOPE_IMAGE_SIZE,
        )
        return str(task_id)

    async def _wait_for_task(self, task_id: str) -> str:
        """轮询百炼任务直到成功或失败。"""
        deadline = datetime.now().timestamp() + settings.IMAGE_PROVIDER_TIMEOUT
        while datetime.now().timestamp() < deadline:
            response_data = await self._request_json(
                "GET",
                f"{self._api_base}/tasks/{task_id}",
                headers=self._auth_headers,
            )
            output = response_data.get("output", {})
            task_status = output.get("task_status", "")
            if task_status == "SUCCEEDED":
                image_url = self._extract_image_url(output)
                logger.info("百炼图片任务已完成 | task_id=%s", task_id)
                return image_url
            if task_status in {"FAILED", "CANCELED", "UNKNOWN"}:
                message = output.get("message") or response_data.get("message") or task_status
                raise ImageProviderError(f"百炼图片任务失败: {message}")
            await self._sleep()
        raise ImageProviderError(f"百炼图片任务超时: task_id={task_id}")

    async def _download_image(self, image_url: str) -> bytes:
        """下载百炼返回的临时图片 URL。"""
        response = await self._request("GET", image_url, headers={})
        return response.content

    async def _request_json(self, method: str, url: str, **kwargs: Any) -> dict:
        """发送 HTTP 请求并解析 JSON 响应。"""
        response = await self._request(method, url, **kwargs)
        data = response.json()
        if not isinstance(data, dict):
            raise ImageProviderError("百炼接口返回非 JSON 对象")
        return data

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """复用注入客户端或创建临时客户端发送请求。"""
        try:
            if self.client is not None:
                response = await self.client.request(method, url, **kwargs)
            else:
                async with httpx.AsyncClient(timeout=settings.IMAGE_PROVIDER_TIMEOUT) as client:
                    response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            response_text = exc.response.text[:500] if exc.response is not None else ""
            logger.error(
                "百炼图片接口 HTTP 错误 | method=%s | status=%s | body=%s",
                method,
                exc.response.status_code if exc.response is not None else "unknown",
                response_text,
            )
            raise ImageProviderError(f"百炼图片接口 HTTP 错误: {response_text or str(exc)}") from exc
        except httpx.HTTPError as exc:
            logger.error("百炼图片接口连接异常 | method=%s | error=%s", method, str(exc))
            raise ImageProviderError(f"百炼图片接口连接异常: {str(exc)}") from exc

    async def _sleep(self) -> None:
        """等待下一轮任务轮询。"""
        import asyncio

        await asyncio.sleep(settings.DASHSCOPE_IMAGE_POLL_INTERVAL)

    def _build_prompt(self, request: ImageGenerationRequest) -> str:
        """构造适合百炼文生图的 prompt。"""
        prompt_parts = [
            request.positive_prompt.strip(),
            (
                "高端电商商品摄影，主体清晰锐利，真实材质纹理，柔和棚拍布光，"
                "干净构图，平台合规，无文字水印，无多余品牌标识，适合商品详情页交付。"
            ),
        ]
        if request.reference_image:
            prompt_parts.append("参考原商品图的主体特征，保持商品品类和核心卖点一致。")
        return "\n\n".join(part for part in prompt_parts if part)

    def _build_parameters(self) -> dict:
        """构造百炼图片质量参数。"""
        return {
            "size": settings.DASHSCOPE_IMAGE_SIZE,
            "n": 1,
            "seed": settings.DASHSCOPE_IMAGE_SEED,
            "prompt_extend": settings.DASHSCOPE_IMAGE_PROMPT_EXTEND,
            "watermark": settings.DASHSCOPE_IMAGE_WATERMARK,
        }

    def _extract_image_url(self, output: dict) -> str:
        """兼容百炼不同模型的图片 URL 字段。"""
        results = output.get("results")
        if isinstance(results, list) and results:
            first_result = results[0]
            if isinstance(first_result, dict) and first_result.get("url"):
                return str(first_result["url"])
        if output.get("result_url"):
            return str(output["result_url"])
        if output.get("url"):
            return str(output["url"])
        raise ImageProviderError("百炼图片任务成功但响应缺少图片 URL")

    def _save_image(self, image_bytes: bytes, image_type: str) -> str:
        """保存百炼生成图片到输出目录。"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:18]
        filename = f"{image_type}_dashscope_{timestamp}.png"
        filepath = self.output_dir / filename
        filepath.write_bytes(image_bytes)
        logger.info("百炼图片已保存 | path=%s | size=%d", filepath, len(image_bytes))
        return str(filepath)

    @property
    def _api_base(self) -> str:
        """返回百炼 API 根地址。"""
        return settings.DASHSCOPE_API_BASE.rstrip("/")

    @property
    def _auth_headers(self) -> dict:
        """返回百炼鉴权请求头。"""
        return {
            "Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}",
        }
