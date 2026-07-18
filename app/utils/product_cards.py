"""基于上传原图生成确定性交付图，避免云端模型重画商品。"""
import logging
import re
from collections import deque
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
        product = _prepare_reference_product(img)
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
        source = _prepare_reference_product(img)
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
        product = _prepare_reference_product(img)
        product = _resize_to_fit(product, 560, 760)
        canvas = Image.new("RGBA", (1200, 1200), (255, 255, 255, 255))
        draw = ImageDraw.Draw(canvas)
        title_font, label_font, value_font, small_font = _load_fonts()

        line_color = (33, 37, 41, 255)
        muted = (108, 117, 125, 255)
        accent = (180, 126, 65, 255)
        soft = (246, 242, 236, 255)

        draw.text((76, 58), "Product Dimensions", fill=line_color, font=title_font)
        draw.text((78, 112), "Same uploaded product. Measurements supplied by seller (mm).", fill=muted, font=small_font)
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
        draw.text((104, 1062), "Values shown are the seller-provided actual measurements.", fill=muted, font=small_font)

        output = Path(output_path) if output_path else path.parent / (path.stem + "_dimension_sheet.jpg")
        canvas.convert("RGB").save(output, "JPEG", quality=96)
        logger.info("基于原图生成电商尺寸图 | %s -> %s", path.name, output.name)
        return str(output)


def create_scale_comparison_from_reference(
    image_path: str,
    selling_points: str = "",
    output_path: Optional[str] = None,
) -> str:
    """生成无文字、无尺寸线的比例参照图。"""
    path = _ensure_image_exists(image_path)

    with Image.open(path) as img:
        product = _prepare_reference_product(img)
        product = _resize_to_fit(product, 620, 760)
        dimensions = _estimate_dimensions(product.width, product.height, selling_points)
        canvas = Image.new("RGBA", (1200, 1200), (248, 247, 244, 255))

        product_x = 300 + (560 - product.width) // 2
        product_y = 220 + (760 - product.height) // 2
        _paste_with_soft_shadow(canvas, product, product_x, product_y)

        width_mm = _dimension_value_as_mm(dimensions.get("width", ""))
        coin_diameter = max(52, min(260, round(product.width * 24.26 / max(width_mm, 1))))
        coin_x, coin_y = 875, 820
        draw = ImageDraw.Draw(canvas)
        card_width = 260
        card_height = 164
        card_x, card_y = 820, 570
        draw.rounded_rectangle(
            (card_x, card_y, card_x + card_width, card_y + card_height),
            radius=18,
            fill=(235, 238, 240, 255),
            outline=(183, 189, 194, 255),
            width=4,
        )
        draw.rounded_rectangle(
            (card_x + 26, card_y + 32, card_x + 90, card_y + 72),
            radius=8,
            fill=(202, 208, 212, 255),
        )
        draw.line((card_x + 28, card_y + 112, card_x + 200, card_y + 112), fill=(193, 199, 204, 255), width=8)
        draw.ellipse(
            (coin_x, coin_y, coin_x + coin_diameter, coin_y + coin_diameter),
            fill=(190, 194, 198, 255),
            outline=(128, 134, 140, 255),
            width=8,
        )
        inset = max(10, coin_diameter // 10)
        draw.ellipse(
            (coin_x + inset, coin_y + inset, coin_x + coin_diameter - inset, coin_y + coin_diameter - inset),
            outline=(225, 227, 230, 255),
            width=4,
        )

        output = Path(output_path) if output_path else path.parent / (path.stem + "_scale_comparison.jpg")
        canvas.convert("RGB").save(output, "JPEG", quality=96)
        logger.info("基于原图生成无标注比例参照图 | %s -> %s", path.name, output.name)
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


def prepare_product_cutout(image: Image.Image) -> Image.Image:
    """保留透明原图；对烘焙棋盘格背景的图片自动去除边缘中性色背景。"""
    product = image.convert("RGBA")
    max_edge = max(product.size)
    if max_edge > 960:
        scale = 960 / max_edge
        product = product.resize(
            (max(1, round(product.width * scale)), max(1, round(product.height * scale))),
            Image.LANCZOS,
        )
        logger.info("原图已缩放后进行前景分离 | max_edge=%d -> 960", max_edge)

    alpha = product.getchannel("A")
    if alpha.getextrema()[0] < 250:
        return _trim_transparent_border(product)

    if not _has_light_neutral_corners(product):
        foreground = _extract_foreground_with_grabcut(product)
        if foreground is not None:
            return foreground

    width, height = product.size
    pixels = product.load()
    queue = deque()
    visited = set()

    for x in range(width):
        queue.append((x, 0))
        queue.append((x, height - 1))
    for y in range(1, height - 1):
        queue.append((0, y))
        queue.append((width - 1, y))

    while queue:
        x, y = queue.popleft()
        if (x, y) in visited:
            continue
        visited.add((x, y))
        red, green, blue, alpha_value = pixels[x, y]
        if alpha_value == 0 or min(red, green, blue) < 220 or max(red, green, blue) - min(red, green, blue) > 12:
            continue
        pixels[x, y] = (red, green, blue, 0)
        for next_x, next_y in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= next_x < width and 0 <= next_y < height and (next_x, next_y) not in visited:
                queue.append((next_x, next_y))

    return _trim_transparent_border(product)


def _has_light_neutral_corners(image: Image.Image) -> bool:
    """判断是否为白底/浅色中性背景，避免对其执行高成本 GrabCut。"""
    width, height = image.size
    points = ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1))
    for x, y in points:
        red, green, blue, _ = image.getpixel((x, y))
        if min(red, green, blue) < 220 or max(red, green, blue) - min(red, green, blue) > 12:
            return False
    return True


def _extract_foreground_with_grabcut(image: Image.Image) -> Optional[Image.Image]:
    """使用传统 GrabCut 从带背景原图中提取中心商品，不依赖本地模型。"""
    try:
        import cv2
        import numpy as np
    except ImportError:
        logger.warning("OpenCV 未安装，跳过 GrabCut 前景分离")
        return None

    width, height = image.size
    if width < 32 or height < 32:
        return None

    rgb_image = image.convert("RGB")
    source = cv2.cvtColor(np.array(rgb_image), cv2.COLOR_RGB2BGR)
    mask = np.zeros((height, width), np.uint8)
    margin_x = max(2, int(width * 0.06))
    margin_y = max(2, int(height * 0.06))
    rectangle = (margin_x, margin_y, width - margin_x * 2, height - margin_y * 2)
    background_model = np.zeros((1, 65), np.float64)
    foreground_model = np.zeros((1, 65), np.float64)

    cv2.grabCut(
        source,
        mask,
        rectangle,
        background_model,
        foreground_model,
        1,
        cv2.GC_INIT_WITH_RECT,
    )
    foreground_mask = np.where(
        (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0
    ).astype("uint8")
    foreground_ratio = float(np.count_nonzero(foreground_mask)) / float(width * height)
    coordinates = cv2.findNonZero(foreground_mask)
    if coordinates is None or not 0.02 <= foreground_ratio <= 0.78:
        return None

    _, _, box_width, box_height = cv2.boundingRect(coordinates)
    if box_width >= width * 0.97 and box_height >= height * 0.97:
        return None

    foreground_mask = cv2.GaussianBlur(foreground_mask, (0, 0), 0.8)
    result = image.convert("RGBA")
    result.putalpha(Image.fromarray(foreground_mask))
    logger.info(
        "GrabCut 前景分离完成 | size=%dx%d | ratio=%.2f | bbox=%dx%d",
        width,
        height,
        foreground_ratio,
        box_width,
        box_height,
    )
    return _trim_transparent_border(result)


def _prepare_reference_product(image: Image.Image) -> Image.Image:
    """兼容旧调用，返回适合合成的商品透明前景。"""
    return prepare_product_cutout(image)


def _resize_to_fit(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    """等比缩放图片到目标框内。"""
    width, height = image.size
    scale = min(max_width / max(width, 1), max_height / max(height, 1))
    target_size = (
        max(1, round(width * scale)),
        max(1, round(height * scale)),
    )
    return image.resize(target_size, Image.LANCZOS)


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
    height = extracted.get("height") or "Not provided"
    width = extracted.get("width") or "Not provided"
    depth = extracted.get("depth") or "Not provided"
    dimensions = {"height": height, "width": width, "depth": depth}
    if extracted.get("volume"):
        dimensions["volume"] = extracted["volume"]
    return dimensions


def _dimension_value_as_mm(value: str) -> float:
    """将已解析尺寸转换为毫米，用于比例参照物缩放。"""
    match = re.match(r"(\d+(?:\.\d+)?)\s*(mm|cm)", value or "", re.IGNORECASE)
    if not match:
        return 50.0
    number = float(match.group(1))
    return number * 10 if match.group(2).lower() == "cm" else number


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
