"""
图片 Provider 选择测试。
"""
import unittest
import asyncio
import tempfile
from pathlib import Path

from PIL import Image

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

    def test_dashscope_provider_does_not_initialize_comfyui(self):
        original_provider = settings.IMAGE_PROVIDER
        original_api_key = settings.DASHSCOPE_API_KEY
        settings.IMAGE_PROVIDER = "dashscope"
        settings.DASHSCOPE_API_KEY = "test-key"
        agent = ImageGeneratorAgent()

        self.assertIsNone(agent.comfyui)
        self.assertIsNotNone(agent.cloud_provider)
        asyncio.run(agent.close())
        settings.IMAGE_PROVIDER = original_provider
        settings.DASHSCOPE_API_KEY = original_api_key

    def test_cloud_provider_uses_reference_locked_main_image(self):
        original_provider = settings.IMAGE_PROVIDER
        settings.IMAGE_PROVIDER = "cloud"
        try:
            temp_root = Path.cwd() / "output" / "test_tmp"
            temp_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=temp_root) as temp_name:
                temp_dir = Path(temp_name)
                reference_path = temp_dir / "reference.png"
                Image.new("RGBA", (320, 320), (200, 180, 160, 255)).save(reference_path)

                output_path = ImageGeneratorAgent._generate_reference_locked_asset(
                    image_type="white_bg_main",
                    reference_image_name=str(reference_path),
                    selling_points="温和保湿",
                )

                self.assertTrue(Path(output_path).exists())
                with Image.open(output_path) as result:
                    self.assertEqual(result.size, (1200, 1200))
        finally:
            settings.IMAGE_PROVIDER = original_provider

    def test_comfyui_provider_also_uses_reference_locked_main_image(self):
        original_provider = settings.IMAGE_PROVIDER
        settings.IMAGE_PROVIDER = "comfyui"
        try:
            temp_root = Path.cwd() / "output" / "test_tmp"
            temp_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=temp_root) as temp_name:
                temp_dir = Path(temp_name)
                reference_path = temp_dir / "reference.png"
                Image.new("RGBA", (300, 420), (210, 190, 170, 255)).save(reference_path)

                output_path = ImageGeneratorAgent._generate_reference_locked_asset(
                    image_type="white_bg_main",
                    reference_image_name=str(reference_path),
                    selling_points="稳定锁图",
                )

                self.assertTrue(Path(output_path).exists())
                with Image.open(output_path) as result:
                    self.assertEqual(result.size, (1200, 1200))
        finally:
            settings.IMAGE_PROVIDER = original_provider

    def test_scene_background_prompt_excludes_product_objects(self):
        positive, negative = ImageGeneratorAgent._build_scene_background_prompt(
            positive_prompt="premium bathroom scene",
            negative_prompt="low quality",
            selling_points="高端礼盒感",
        )

        self.assertIn("no product object", positive)
        self.assertIn("central tabletop", positive)
        self.assertIn("jar", negative)
        self.assertIn("bottle", negative)


if __name__ == "__main__":
    unittest.main()
