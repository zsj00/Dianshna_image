"""
图片生成 Provider 单元测试。
"""
import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.config import settings
from app.services.image_provider import CloudImageProvider, ImageGenerationRequest


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


if __name__ == "__main__":
    unittest.main()
