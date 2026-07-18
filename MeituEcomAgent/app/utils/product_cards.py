"""基于上传原图生成确定性交付图，避免云端模型重画商品。"""
import logging
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger(__name__)


class ProductCardError(Exception):
    """商品卡片生成异常。"""

    pass


def create_white_main_from_reference(image_path: str, output_path: Optional[str] = None) -> str:
    """使用上传原图生成平台白底主图。"""
    path = _ensure_image_exists(image_path)

    with Image.open(path) as img:
        product = _trim_transparent_border(img.convert("RGBA"))
        product = _resize_to_fit(product, 1030, 1030)
        canvas = Image.new("RGBA", (1200, 1200), (255, 255, 255, 255))
        pos = ((1200 - product.width) // 2, (1200 - product.height) // 2)
        canvas.paste(product, pos, product)
        output = Path(output_path) if output_path else path.parent / (path.stem + "_main_white.jpg")
        canvas.convert("RGB").save(output, "JPEG", quality=96)
        logger.info("基于原图生成白底主图 | %s -> %s", path.name, output.name)
        return str(output)


def create_detail_from_reference(image_path: str, output_path: Optional[str] = None) -> str:
    """使用上传原图生成细节特写。"""
    path = _ensure_image_exists(image_path)

    with Image.open(path) as img:
        source = _trim_transparent_border(img.convert("RGBA"))
        width, height = source.size
        crop_width = max(1, int(width * 0.64))
        crop_height = max(1, int(height * 0.64))
        left = max(0, (width - crop_width) // 2)
        top = max(0, (height - crop_height) // 2)
        detail = source.crop((left, top, left + crop_width, top + crop_height))
        detail = _resize_to_fit(detail, 1120, 1120)
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
    """使用上传原图生成电商风格尺寸标注图。"""
    path = _ensure_image_exists(image_path)

    with Image.open(path) as img:
        product = _trim_transparent_border(img.convert("RGBA"))
        product = _resize_to_fit(product, 560, 760)
        canvas = Image.new("RGBA", (1200, 1200), (255, 255, 255, 255))
        draw = ImageDraw.Draw(canvas)
        title_font, label_font, value_font, small_font = _load_fonts()

        line_color = (33, 37, 41, 255)
        muted = (108, 117, 125, 255)
        accent = (180, 126, 65, 255)
        soft = (246, 242, 236, 255)

        draw.text((76, 58), "Product Dimensions", fill=line_color, font=title_font)
        draw.text((78, 112), "Same uploaded product. Measurements are visual references.", fill=muted, font=small_font)
        draw.line((76, 158, 1124, 158), fill=(232, 235, 239, 255), width=2)

        product_x = 250 + (420 - product.width) // 2
        product_y = 250 + (720 - product.height) // 2
        _paste_with_soft_shadow(canvas, product, product_x, product_y)

        x1, y1 = product_x, product_y
        x2, y2 = product_x + product.width, product_y + product.height
        dimensions = _estimate_dimensions(product.width, product.height, selling_points)

        width_y = min(1015, y2 + 78)
        _draw_measure_line(draw, (x1, width_y), (x2, width_y), line_color)
        _draw_center_label(draw, f"W  {dimensions['width']}", (x1 + x2) // 2, width_y + 24, value_font, accent)

        height_x = min(720, x2 + 86)
        _draw_measure_line(draw, (height_x, y1), (height_x, y2), line_color)

        depth_y = max(220, y1 - 58)
        depth_x1 = x1 + max(12, int(product.width * 0.16))
        depth_x2 = x2 - max(12, int(product.width * 0.16))
        if depth_x2 - depth_x1 > 80:
            _draw_measure_line(draw, (depth_x1, depth_y), (depth_x2, depth_y), line_color)
            _draw_center_label(draw, f"D  {dimensions['depth']}", (depth_x1 + depth_x2) // 2, depth_y - 44, small_font, muted)

        panel_x, panel_y = 790, 276
        draw.text((height_x + 18, max(178, y1 - 46)), f"H  {dimensions['height']}", fill=accent, font=small_font)
        draw.rounded_rectangle((panel_x, panel_y, 1108, 810), radius=26, fill=soft, outline=(229, 220, 209, 255), width=2)
        draw.text((panel_x + 36, panel_y + 36), "SIZE INFO", fill=accent, font=label_font)
        _draw_size_item(draw, panel_x + 36, panel_y + 116, "Height", dimensions["height"], value_font, small_font)
        _draw_size_item(draw, panel_x + 36, panel_y + 220, "Width", dimensions["width"], value_font, small_font)
        _draw_size_item(draw, panel_x + 36, panel_y + 324, "Diameter / Depth", dimensions["depth"], value_font, small_font)
        if dimensions.get("volume"):
            _draw_size_item(draw, panel_x + 36, panel_y + 428, "Capacity", dimensions["volume"], value_font, small_font)

        draw.rounded_rectangle((76, 1040, 1124, 1110), radius=18, fill=(250, 250, 250, 255), outline=(235, 238, 242, 255), width=1)
        draw.text((104, 1062), "Tip: add exact values like H 12cm / W 4cm / D 4cm / 30ml in selling points.", fill=muted, font=small_font)

        output = Path(output_path) if output_path else path.parent / (path.stem + "_dimension_sheet.jpg")
        canvas.convert("RGB").save(output, "JPEG", quality=96)
        logger.info("基于原图生成电商尺寸图 | %s -> %s", path.name, output.name)
        return str(output)


def _ensure_image_exists(image_path: str) -> Path:
    """检查商品原图是否存在。"""
    path = Path(image_path)
    if not path.exists():
        raise ProductCardError(f"商品原图不存在: {image_path}")
    return path


def _trim_transparent_border(image: Image.Image) -> Image.Image:
    """裁掉透明边缘，保留原商品像素。"""
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox:
        return image.crop(bbox)
    return image


def _resize_to_fit(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    """等比缩放图片到目标框内。"""
    result = image.copy()
    result.thumbnail((max_width, max_height), Image.LANCZOS)
    return result


def _paste_with_soft_shadow(canvas: Image.Image, product: Image.Image, x: int, y: int) -> None:
    """粘贴商品并添加轻微自然投影。"""
    shadow = Image.new("RGBA", product.size, (0, 0, 0, 0))
    alpha = product.getchannel("A").filter(ImageFilter.GaussianBlur(16))
    shadow.putalpha(alpha.point(lambda value: int(value * 0.16)))
    canvas.alpha_composite(shadow, (x + 18, y + 24))
    canvas.alpha_composite(product, (x, y))


def _estimate_dimensions(width_px: int, height_px: int, selling_points: str) -> Dict[str, str]:
    """从卖点中提取尺寸；缺失时给出视觉参考值。"""
    extracted = _extract_dimensions(selling_points)
    aspect = height_px / max(width_px, 1)
    height = extracted.get("height") or ("12.0 cm" if aspect > 1.8 else "8.0 cm")
    width = extracted.get("width") or f"{max(2.8, min(9.8, float(height.split()[0]) / aspect)):.1f} cm"
    depth = extracted.get("depth") or width
    dimensions = {"height": height, "width": width, "depth": depth}
    if extracted.get("volume"):
        dimensions["volume"] = extracted["volume"]
    return dimensions


def _extract_dimensions(text: str) -> Dict[str, str]:
    """从用户卖点文案中解析常见尺寸表达。"""
    result: Dict[str, str] = {}
    patterns = {
        "height": r"(?:高|高度|H)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(cm|厘米|mm|毫米)",
        "width": r"(?:宽|宽度|W)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(cm|厘米|mm|毫米)",
        "depth": r"(?:厚|深|直径|口径|D)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*(cm|厘米|mm|毫米)",
        "volume": r"(\d+(?:\.\d+)?)\s*(ml|mL|ML|毫升|L|升)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text or "", re.IGNORECASE)
        if match:
            value, unit = match.group(1), match.group(2)
            normalized_unit = "cm" if unit in {"厘米"} else "mm" if unit in {"毫米"} else unit.lower()
            if key == "volume":
                normalized_unit = "ml" if normalized_unit in {"毫升"} else normalized_unit
            result[key] = f"{value} {normalized_unit}"
    return result


def _load_fonts() -> Tuple[ImageFont.ImageFont, ImageFont.ImageFont, ImageFont.ImageFont, ImageFont.ImageFont]:
    """加载常用字体，失败时使用默认字体。"""
    candidates = ["msyh.ttc", "simhei.ttf", "arial.ttf"]
    for font_name in candidates:
        try:
            return (
                ImageFont.truetype(font_name, 42),
                ImageFont.truetype(font_name, 30),
                ImageFont.truetype(font_name, 34),
                ImageFont.truetype(font_name, 22),
            )
        except Exception:
            continue
    fallback = ImageFont.load_default()
    return fallback, fallback, fallback, fallback


def _draw_measure_line(
    draw: ImageDraw.ImageDraw,
    start: Tuple[int, int],
    end: Tuple[int, int],
    color: Tuple[int, int, int, int],
) -> None:
    """绘制电商尺寸标注线。"""
    draw.line([start, end], fill=color, width=3)
    start_x, start_y = start
    end_x, end_y = end
    if abs(end_x - start_x) >= abs(end_y - start_y):
        draw.line((start_x, start_y - 16, start_x, start_y + 16), fill=color, width=3)
        draw.line((end_x, end_y - 16, end_x, end_y + 16), fill=color, width=3)
    else:
        draw.line((start_x - 16, start_y, start_x + 16, start_y), fill=color, width=3)
        draw.line((end_x - 16, end_y, end_x + 16, end_y), fill=color, width=3)


def _draw_center_label(
    draw: ImageDraw.ImageDraw,
    text: str,
    center_x: int,
    y: int,
    font: ImageFont.ImageFont,
    color: Tuple[int, int, int, int],
) -> None:
    """绘制居中文案。"""
    bbox = draw.textbbox((0, 0), text, font=font)
    draw.text((center_x - (bbox[2] - bbox[0]) // 2, y), text, fill=color, font=font)


def _draw_size_item(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    value: str,
    value_font: ImageFont.ImageFont,
    small_font: ImageFont.ImageFont,
) -> None:
    """绘制右侧参数项。"""
    draw.text((x, y), label, fill=(108, 117, 125, 255), font=small_font)
    draw.text((x, y + 34), value, fill=(33, 37, 41, 255), font=value_font)
