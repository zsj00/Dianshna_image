"""基于上传原图生成确定性交付图，避免云端模型重画商品。"""
import logging
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


class ProductCardError(Exception):
    """商品卡片生成异常。"""

    pass


def create_white_main_from_reference(image_path: str, output_path: Optional[str] = None) -> str:
    """使用上传原图生成平台白底主图。"""
    path = Path(image_path)
    if not path.exists():
        raise ProductCardError(f"商品原图不存在: {image_path}")

    with Image.open(path) as img:
        product = img.convert("RGBA")
        canvas_size = 1200
        margin = int(canvas_size * 0.08)
        max_side = canvas_size - margin * 2
        scale = min(max_side / product.width, max_side / product.height)
        new_size = (max(1, int(product.width * scale)), max(1, int(product.height * scale)))
        product = product.resize(new_size, Image.LANCZOS)
        canvas = Image.new("RGBA", (canvas_size, canvas_size), (255, 255, 255, 255))
        pos = ((canvas_size - new_size[0]) // 2, (canvas_size - new_size[1]) // 2)
        canvas.paste(product, pos, product)
        output = Path(output_path) if output_path else path.parent / (path.stem + "_main_white.jpg")
        canvas.convert("RGB").save(output, "JPEG", quality=96)
        logger.info("基于原图生成白底主图 | %s -> %s", path.name, output.name)
        return str(output)


def create_detail_from_reference(image_path: str, output_path: Optional[str] = None) -> str:
    """使用上传原图生成细节特写。"""
    path = Path(image_path)
    if not path.exists():
        raise ProductCardError(f"商品原图不存在: {image_path}")

    with Image.open(path) as img:
        source = img.convert("RGBA")
        width, height = source.size
        crop_width = int(width * 0.62)
        crop_height = int(height * 0.62)
        left = max(0, (width - crop_width) // 2)
        top = max(0, (height - crop_height) // 2)
        detail = source.crop((left, top, left + crop_width, top + crop_height))
        detail.thumbnail((1200, 1200), Image.LANCZOS)
        canvas = Image.new("RGBA", (1200, 1200), (255, 255, 255, 255))
        pos = ((1200 - detail.width) // 2, (1200 - detail.height) // 2)
        canvas.paste(detail, pos, detail)
        output = Path(output_path) if output_path else path.parent / (path.stem + "_detail.jpg")
        canvas.convert("RGB").save(output, "JPEG", quality=96)
        logger.info("基于原图生成细节图 | %s -> %s", path.name, output.name)
        return str(output)


def create_dimension_sheet_from_reference(
    image_path: str,
    selling_points: str = "",
    output_path: Optional[str] = None,
) -> str:
    """使用上传原图生成清晰尺寸标注图。"""
    path = Path(image_path)
    if not path.exists():
        raise ProductCardError(f"商品原图不存在: {image_path}")

    with Image.open(path) as img:
        product = img.convert("RGBA")
        canvas_width, canvas_height = 1400, 1200
        canvas = Image.new("RGBA", (canvas_width, canvas_height), (255, 255, 255, 255))
        max_width, max_height = 760, 680
        scale = min(max_width / product.width, max_height / product.height)
        new_size = (max(1, int(product.width * scale)), max(1, int(product.height * scale)))
        product = product.resize(new_size, Image.LANCZOS)
        product_x = 230
        product_y = 260
        canvas.paste(product, (product_x, product_y), product)
        draw = ImageDraw.Draw(canvas)

        title_font, label_font, small_font = _load_fonts()
        line_color = (32, 40, 55, 255)
        muted = (92, 105, 125, 255)
        accent = (181, 125, 61, 255)
        x1, y1 = product_x, product_y
        x2, y2 = product_x + new_size[0], product_y + new_size[1]

        draw.text((70, 56), "Product Size Reference", fill=line_color, font=title_font)
        draw.text((72, 112), "Same uploaded product, visual measurement guide", fill=muted, font=small_font)

        width_y = y2 + 72
        _draw_double_arrow(draw, (x1, width_y), (x2, width_y), line_color)
        draw.text(((x1 + x2) // 2 - 85, width_y + 18), "Width", fill=line_color, font=label_font)

        height_x = x2 + 80
        _draw_double_arrow(draw, (height_x, y1), (height_x, y2), line_color)
        draw.text((height_x + 28, (y1 + y2) // 2 - 20), "Height", fill=line_color, font=label_font)

        depth_start = (x1 + int(new_size[0] * 0.18), y1 + int(new_size[1] * 0.18))
        depth_end = (depth_start[0] + 190, depth_start[1] + 150)
        _draw_double_arrow(draw, depth_start, depth_end, line_color)
        draw.text((depth_end[0] + 18, depth_end[1] - 8), "Depth", fill=line_color, font=label_font)

        ruler_y = canvas_height - 180
        ruler_x = 120
        ruler_width = 800
        draw.rounded_rectangle(
            (ruler_x, ruler_y, ruler_x + ruler_width, ruler_y + 44),
            radius=8,
            outline=muted,
            width=3,
        )
        for tick in range(0, 21):
            tick_x = ruler_x + int(ruler_width * tick / 20)
            tick_height = 38 if tick % 5 == 0 else 24
            draw.line([(tick_x, ruler_y), (tick_x, ruler_y + tick_height)], fill=muted, width=2)
        draw.text((ruler_x, ruler_y + 58), "Scale ruler for visual comparison", fill=muted, font=small_font)

        if selling_points:
            points = [point.strip() for point in selling_points.replace("|", "\n").split("\n") if point.strip()]
            box_x, box_y = 970, 260
            draw.rounded_rectangle(
                (box_x, box_y, 1320, 610),
                radius=24,
                outline=(232, 221, 207, 255),
                fill=(253, 250, 246, 255),
                width=2,
            )
            draw.text((box_x + 28, box_y + 28), "Key Selling Points", fill=accent, font=label_font)
            for index, point in enumerate(points[:5]):
                draw.text((box_x + 32, box_y + 88 + index * 46), f"• {point}", fill=line_color, font=small_font)

        output = Path(output_path) if output_path else path.parent / (path.stem + "_dimension_sheet.jpg")
        canvas.convert("RGB").save(output, "JPEG", quality=96)
        logger.info("基于原图生成尺寸标注图 | %s -> %s", path.name, output.name)
        return str(output)


def _load_fonts() -> Tuple[ImageFont.ImageFont, ImageFont.ImageFont, ImageFont.ImageFont]:
    """加载常用字体，失败时使用默认字体。"""
    try:
        return (
            ImageFont.truetype("arial.ttf", 42),
            ImageFont.truetype("arial.ttf", 30),
            ImageFont.truetype("arial.ttf", 24),
        )
    except Exception:
        fallback = ImageFont.load_default()
        return fallback, fallback, fallback


def _draw_double_arrow(
    draw: ImageDraw.ImageDraw,
    start: Tuple[int, int],
    end: Tuple[int, int],
    color: Tuple[int, int, int, int],
) -> None:
    """绘制双向尺寸箭头。"""
    draw.line([start, end], fill=color, width=4)
    start_x, start_y = start
    end_x, end_y = end
    if abs(end_x - start_x) >= abs(end_y - start_y):
        draw.polygon([(start_x, start_y), (start_x + 18, start_y - 9), (start_x + 18, start_y + 9)], fill=color)
        draw.polygon([(end_x, end_y), (end_x - 18, end_y - 9), (end_x - 18, end_y + 9)], fill=color)
    else:
        draw.polygon([(start_x, start_y), (start_x - 9, start_y + 18), (start_x + 9, start_y + 18)], fill=color)
        draw.polygon([(end_x, end_y), (end_x - 9, end_y - 18), (end_x + 9, end_y - 18)], fill=color)
