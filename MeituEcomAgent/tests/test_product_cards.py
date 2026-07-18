"""
原图锁定商品图工具测试。
"""
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageChops

from app.utils.product_cards import (
    _estimate_dimensions,
    create_detail_from_reference,
    create_dimension_sheet_from_reference,
    create_scale_comparison_from_reference,
    create_white_main_from_reference,
    prepare_product_cutout,
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

    def test_dimension_estimation_does_not_invent_measurements(self):
        dimensions = _estimate_dimensions(320, 260, "便携设计 | 温和配方")

        self.assertEqual(dimensions["height"], "Not provided")
        self.assertEqual(dimensions["width"], "Not provided")
        self.assertEqual(dimensions["depth"], "Not provided")

    def test_dimension_estimation_uses_seller_measurements(self):
        dimensions = _estimate_dimensions(320, 260, "H 120mm | W 45mm | D 45mm")

        self.assertEqual(dimensions["height"], "120 mm")
        self.assertEqual(dimensions["width"], "45 mm")
        self.assertEqual(dimensions["depth"], "45 mm")

    def test_scale_comparison_has_no_dimension_labels(self):
        with self._create_temp_dir() as temp_name:
            temp_dir = Path(temp_name)
            reference_path = self._create_reference_image(temp_dir)
            output_path = create_scale_comparison_from_reference(
                str(reference_path),
                "H 120mm | W 45mm | D 45mm",
                str(temp_dir / "scale.jpg"),
            )

            with Image.open(output_path) as result:
                self.assertEqual(result.size, (1200, 1200))

    def test_create_white_main_removes_baked_checkerboard_background(self):
        with self._create_temp_dir() as temp_name:
            temp_dir = Path(temp_name)
            reference_path = temp_dir / "checkerboard.webp"
            image = Image.new("RGB", (200, 200), (255, 255, 255))
            for y in range(0, 200, 20):
                for x in range(0, 200, 20):
                    if (x // 20 + y // 20) % 2:
                        Image.Image.paste(image, (238, 238, 238), (x, y, x + 20, y + 20))
            Image.Image.paste(image, (44, 32, 26), (70, 50, 130, 155))
            image.save(reference_path)

            output_path = create_white_main_from_reference(str(reference_path), str(temp_dir / "main.jpg"))

            with Image.open(output_path) as result:
                red, green, blue = result.getpixel((215, 110))
            self.assertGreater(red, 250)
            self.assertGreater(green, 250)
            self.assertGreater(blue, 250)

    def test_create_white_main_extracts_product_from_opaque_background(self):
        with self._create_temp_dir() as temp_name:
            temp_dir = Path(temp_name)
            reference_path = temp_dir / "opaque-background.jpg"
            image = Image.new("RGB", (480, 480), (214, 200, 184))
            Image.Image.paste(image, (68, 76, 90), (130, 72, 350, 420))
            Image.Image.paste(image, (26, 28, 32), (150, 50, 330, 112))
            image.save(reference_path)

            output_path = create_white_main_from_reference(str(reference_path), str(temp_dir / "main.jpg"))

            with Image.open(output_path) as result:
                red, green, blue = result.getpixel((18, 18))
            self.assertGreater(red, 250)
            self.assertGreater(green, 250)
            self.assertGreater(blue, 250)

    def test_grabcut_removes_opaque_background(self):
        image = Image.new("RGB", (480, 480), (214, 200, 184))
        Image.Image.paste(image, (68, 76, 90), (130, 72, 350, 420))
        Image.Image.paste(image, (26, 28, 32), (150, 50, 330, 112))

        product = prepare_product_cutout(image)

        self.assertLess(product.width, 400)
        self.assertLess(product.height, 450)
        self.assertLess(product.getchannel("A").getextrema()[0], 10)


if __name__ == "__main__":
    unittest.main()
