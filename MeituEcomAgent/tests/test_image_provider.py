"""
图片生成 Provider 单元测试。
"""
import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.config import settings
from app.services.image_provider import (
    CloudImageProvider,
    DashScopeImageProvider,
    ImageGenerationRequest,
)


class FakeImagesClient:
    """模拟 OpenAI images client。"""

    async def generate(self, **kwargs):
        image_b64 = base64.b64encode(b"fake-png-bytes").decode("utf-8")
        return SimpleNamespace(data=[SimpleNamespace(b64_json=image_b64)])


class FakeOpenAIClient:
    """模拟 AsyncOpenAI client。"""

    def __init__(self):
        self.images = FakeImagesClient()
        self.closed = False

    async def close(self):
        self.closed = True


class FakeHttpResponse:
    """模拟 httpx Response。"""

    def __init__(self, data=None, content: bytes = b""):
        self._data = data or {}
        self.content = content

    def json(self):
        return self._data

    def raise_for_status(self):
        return None


class FakeDashScopeClient:
    """模拟百炼异步生图客户端。"""

    def __init__(self):
        self.closed = False
        self.requests = []

    async def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        if method == "POST":
            return FakeHttpResponse({"output": {"task_id": "task-1"}})
        if url.endswith("/tasks/task-1"):
            return FakeHttpResponse(
                {"output": {"task_status": "SUCCEEDED", "results": [{"url": "https://example.test/image.png"}]}}
            )
        return FakeHttpResponse(content=b"fake-dashscope-png")

    async def aclose(self):
        self.closed = True


class TestCloudImageProvider(unittest.IsolatedAsyncioTestCase):
    """云端图片 Provider 测试。"""

    async def test_generate_image_saves_b64_result(self):
        original_output_dir = settings.OUTPUT_DIR
        original_response_format = settings.CLOUD_IMAGE_RESPONSE_FORMAT
        with tempfile.TemporaryDirectory() as tmpdir:
            settings.OUTPUT_DIR = tmpdir
            settings.CLOUD_IMAGE_RESPONSE_FORMAT = "b64_json"
            provider = CloudImageProvider(client=FakeOpenAIClient())

            output_path = await provider.generate_image(
                ImageGenerationRequest(
                    positive_prompt="A clean product photo",
                    negative_prompt="watermark",
                    image_type="white_bg_main",
                )
            )

            self.assertTrue(Path(output_path).exists())
            self.assertEqual(Path(output_path).read_bytes(), b"fake-png-bytes")
            await provider.close()

        settings.OUTPUT_DIR = original_output_dir
        settings.CLOUD_IMAGE_RESPONSE_FORMAT = original_response_format

    async def test_check_connection_uses_config_only(self):
        original_api_key = settings.OPENAI_API_KEY
        settings.OPENAI_API_KEY = "test-key"
        provider = CloudImageProvider(client=FakeOpenAIClient())

        self.assertTrue(await provider.check_connection())
        await provider.close()
        settings.OPENAI_API_KEY = original_api_key


class TestDashScopeImageProvider(unittest.IsolatedAsyncioTestCase):
    """百炼图片 Provider 测试。"""

    async def test_generate_image_saves_async_task_result(self):
        original_output_dir = settings.OUTPUT_DIR
        original_api_key = settings.DASHSCOPE_API_KEY
        original_poll_interval = settings.DASHSCOPE_IMAGE_POLL_INTERVAL
        with tempfile.TemporaryDirectory() as tmpdir:
            settings.OUTPUT_DIR = tmpdir
            settings.DASHSCOPE_API_KEY = "test-key"
            settings.DASHSCOPE_IMAGE_POLL_INTERVAL = 0
            settings.DASHSCOPE_IMAGE_PROMPT_EXTEND = True
            settings.DASHSCOPE_IMAGE_WATERMARK = False
            fake_client = FakeDashScopeClient()
            provider = DashScopeImageProvider(client=fake_client)

            output_path = await provider.generate_image(
                ImageGenerationRequest(
                    positive_prompt="干净的白底商品图",
                    negative_prompt="水印",
                    image_type="white_bg_main",
                )
            )

            self.assertTrue(Path(output_path).exists())
            self.assertEqual(Path(output_path).read_bytes(), b"fake-dashscope-png")
            self.assertTrue(any(headers[2].get("headers", {}).get("X-DashScope-Async") == "enable" for headers in fake_client.requests))
            create_request = fake_client.requests[0][2]["json"]
            self.assertTrue(create_request["parameters"]["prompt_extend"])
            self.assertFalse(create_request["parameters"]["watermark"])
            self.assertEqual(create_request["parameters"]["seed"], settings.DASHSCOPE_IMAGE_SEED)
            await provider.close()
            self.assertTrue(fake_client.closed)

        settings.OUTPUT_DIR = original_output_dir
        settings.DASHSCOPE_API_KEY = original_api_key
        settings.DASHSCOPE_IMAGE_POLL_INTERVAL = original_poll_interval


if __name__ == "__main__":
    unittest.main()
