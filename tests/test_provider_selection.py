"""
图片 Provider 选择测试。
"""
import unittest
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

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
        self.assertIn("unobstructed horizontal surface", positive)
        self.assertIn("perspective-compatible", positive)
        self.assertIn("jar", negative)
        self.assertIn("bottle", negative)
        self.assertIn("duplicate product", negative)
        self.assertIn("floating object", negative)

    def test_retry_keeps_reference_locked_asset_without_calling_provider(self):
        with tempfile.TemporaryDirectory() as temp_name:
            reference_path = Path(temp_name) / "reference.png"
            Image.new("RGBA", (320, 420), (205, 180, 160, 255)).save(reference_path)
            agent = object.__new__(ImageGeneratorAgent)
            agent._generate_one_with_tracking = AsyncMock()

            output_path = asyncio.run(
                agent.regenerate_for_retry(
                    task_id="retry-lock-test",
                    image_type="detail_closeup",
                    prompt_data={"prompt_en": "ignored"},
                    reference_image_name=str(reference_path),
                    selling_points="H 12cm / W 4cm / D 4cm",
                )
            )

            self.assertTrue(Path(output_path).exists())
            agent._generate_one_with_tracking.assert_not_awaited()

    def test_scene_retry_uses_locked_white_main_for_compositing(self):
        with tempfile.TemporaryDirectory() as temp_name:
            reference_path = Path(temp_name) / "reference.png"
            Image.new("RGBA", (320, 420), (205, 180, 160, 255)).save(reference_path)
            agent = object.__new__(ImageGeneratorAgent)
            agent._generate_one_with_tracking = AsyncMock(return_value="scene.jpg")

            result = asyncio.run(
                agent.regenerate_for_retry(
                    task_id="scene-retry-test",
                    image_type="scene_lifestyle",
                    prompt_data={"prompt_en": "empty premium scene"},
                    reference_image_name=str(reference_path),
                    selling_points="H 12cm / W 4cm / D 4cm",
                )
            )

            self.assertEqual(result, "scene.jpg")
            white_main_path = agent._generate_one_with_tracking.await_args.kwargs["white_bg_path"]
            self.assertTrue(Path(white_main_path).exists())


if __name__ == "__main__":
    unittest.main()
