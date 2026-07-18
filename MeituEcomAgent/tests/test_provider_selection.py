"""
图片 Provider 选择测试。
"""
import unittest
import asyncio

from app.config import settings
from app.agents.image_generator import ImageGeneratorAgent


class TestProviderSelection(unittest.TestCase):
    """验证生产默认云端，ComfyUI 仅可选。"""

    def test_cloud_provider_does_not_initialize_comfyui(self):
        original_provider = settings.IMAGE_PROVIDER
        original_api_key = settings.OPENAI_API_KEY
        settings.IMAGE_PROVIDER = "cloud"
        settings.OPENAI_API_KEY = "test-key"
        agent = ImageGeneratorAgent()

        self.assertIsNone(agent.comfyui)
        self.assertIsNotNone(agent.cloud_provider)
        asyncio.run(agent.close())
        settings.IMAGE_PROVIDER = original_provider
        settings.OPENAI_API_KEY = original_api_key


if __name__ == "__main__":
    unittest.main()
