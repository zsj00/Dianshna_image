"""
原图锁定商品图工具测试。
"""
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops

from app.utils.product_cards import (
    create_detail_from_reference,
    create_dimension_sheet_from_reference,
    create_white_main_from_reference,
)


class ProductCardsTestCase(unittest.TestCase):
    """验证确定性商品卡片不会依赖随机生图。"""

    def _create_temp_dir(self) -> tempfile.TemporaryDirectory:
        temp_root = Path.cwd() / "output" / "test_tmp"
        temp_root.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(dir=temp_root)

    def _create_reference_image(self, temp_dir: Path) -> Path:
        image_path = temp_dir / "reference.png"
        image = Image.new("RGBA", (640, 520), (0, 0, 0, 0))
        product = Image.new("RGBA", (320, 260), (246, 220, 185, 255))
        lid = Image.new("RGBA", (320, 80), (12, 12, 14, 255))
        image.alpha_composite(product, (160, 180))
        image.alpha_composite(lid, (160, 120))
        image.save(image_path)
        return image_path

    def test_create_white_main_from_reference_keeps_white_canvas(self):
        with self._create_temp_dir() as temp_name:
            temp_dir = Path(temp_name)
            reference_path = self._create_reference_image(temp_dir)

            output_path = create_white_main_from_reference(str(reference_path), str(temp_dir / "main.jpg"))

            with Image.open(output_path) as result:
                self.assertEqual(result.size, (1200, 1200))
                self.assertEqual(result.getpixel((10, 10)), (255, 255, 255))

    def test_create_detail_from_reference_exports_square_detail(self):
        with self._create_temp_dir() as temp_name:
            temp_dir = Path(temp_name)
            reference_path = self._create_reference_image(temp_dir)

            output_path = create_detail_from_reference(str(reference_path), str(temp_dir / "detail.jpg"))

            with Image.open(output_path) as result:
                self.assertEqual(result.size, (1200, 1200))

    def test_create_dimension_sheet_draws_measurement_marks(self):
        with self._create_temp_dir() as temp_name:
            temp_dir = Path(temp_name)
            reference_path = self._create_reference_image(temp_dir)

            output_path = create_dimension_sheet_from_reference(
                str(reference_path),
                "轻盈质地 | 便携容量",
                str(temp_dir / "dimension.jpg"),
            )

            with Image.open(output_path) as image:
                result = image.convert("RGB")
            blank = Image.new("RGB", result.size, (255, 255, 255))
            diff_bbox = ImageChops.difference(result, blank).getbbox()
            self.assertEqual(result.size, (1200, 1200))
            self.assertIsNotNone(diff_bbox)


if __name__ == "__main__":
    unittest.main()
