"""
图片处理工具函数

功能:
- 图片格式与尺寸验证
- 图片缩放（保持长宽比）
- 图片转Base64编码
"""
import base64
import logging
from pathlib import Path
from typing import Optional, Tuple
from io import BytesIO

from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

# 支持的图片格式
SUPPORTED_FORMATS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}
MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
}

# 最大文件大小 (20MB)
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024


class ImageUtilsError(Exception):
    """图片处理异常"""

    pass


def validate_image(
    image_path: str,
    min_width: int = 512,
    min_height: int = 512,
) -> bool:
    """
    验证图片尺寸和格式是否符合要求

    验证内容:
    - 文件是否存在
    - 是否为支持的图片格式
    - 文件大小是否在允许范围内（最大20MB）
    - 图片尺寸是否达到最小值
    - 图片能否被正常打开

    Args:
        image_path: 图片文件路径
        min_width: 最小宽度要求（默认512）
        min_height: 最小高度要求（默认512）

    Returns:
        bool: True 表示验证通过

    Raises:
        ImageUtilsError: 验证失败时抛出详细错误信息
    """
    path = Path(image_path)

    # 1. 检查文件存在
    if not path.exists():
        raise ImageUtilsError(f"图片文件不存在: {image_path}")

    if not path.is_file():
        raise ImageUtilsError(f"路径不是文件: {image_path}")

    # 2. 检查文件扩展名
    ext = path.suffix.lower()
    if ext not in SUPPORTED_FORMATS:
        raise ImageUtilsError(
            f"不支持的图片格式: {ext}。支持的格式: {', '.join(sorted(SUPPORTED_FORMATS))}"
        )

    # 3. 检查文件大小
    file_size = path.stat().st_size
    if file_size == 0:
        raise ImageUtilsError(f"图片文件为空: {image_path}")
    if file_size > MAX_FILE_SIZE_BYTES:
        raise ImageUtilsError(
            f"图片文件过大: {file_size / (1024 * 1024):.1f}MB (最大 {MAX_FILE_SIZE_BYTES / (1024 * 1024):.0f}MB)"
        )

    # 4. 打开图片并检查尺寸
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            mode = img.mode
            img_format = img.format

            if width < min_width or height < min_height:
                raise ImageUtilsError(
                    f"图片尺寸不满足要求: {width}x{height} "
                    f"(最小要求 {min_width}x{min_height})"
                )

            logger.debug(
                "图片验证通过 | %s | %dx%d | %s | %s | %.1f KB",
                path.name,
                width, height,
                mode, img_format,
                file_size / 1024,
            )
            return True

    except ImageUtilsError:
        raise
    except UnidentifiedImageError:
        raise ImageUtilsError(f"无法识别图片格式或文件损坏: {image_path}")
    except Exception as e:
        raise ImageUtilsError(f"读取图片异常: {str(e)}") from e


def get_image_info(image_path: str) -> dict:
    """
    获取图片详细信息

    Args:
        image_path: 图片文件路径

    Returns:
        dict: {
            "path": "...",
            "filename": "...",
            "format": "PNG",
            "mode": "RGB",
            "width": 1024,
            "height": 1024,
            "size_kb": 256.5,
            "aspect_ratio": "1:1"
        }
    """
    path = Path(image_path)

    with Image.open(image_path) as img:
        width, height = img.size
        file_size = path.stat().st_size

        # 计算长宽比
        from math import gcd
        g = gcd(width, height)
        ratio = f"{width // g}:{height // g}"

        return {
            "path": str(path.absolute()),
            "filename": path.name,
            "format": img.format or "UNKNOWN",
            "mode": img.mode,
            "width": width,
            "height": height,
            "size_kb": round(file_size / 1024, 1),
            "aspect_ratio": ratio,
        }


def resize_image(
    image_path: str,
    target_size: Tuple[int, int],
    keep_aspect_ratio: bool = True,
    output_path: Optional[str] = None,
) -> str:
    """
    调整图片尺寸

    默认保持原始长宽比（缩放到 target_size 内最大的适配尺寸）。
    如果 keep_aspect_ratio=False，则直接缩放到指定尺寸（会拉伸变形）。

    Args:
        image_path: 原始图片路径
        target_size: 目标尺寸 (width, height)
        keep_aspect_ratio: 是否保持长宽比，默认 True
        output_path: 输出路径（可选，默认在原文件名后缀加 _resized）

    Returns:
        str: 缩放后的图片路径

    Raises:
        ImageUtilsError: 处理失败
    """
    path = Path(image_path)
    if not path.exists():
        raise ImageUtilsError(f"图片文件不存在: {image_path}")

    target_width, target_height = target_size

    try:
        with Image.open(image_path) as img:
            original_size = img.size

            if keep_aspect_ratio:
                # 计算等比例缩放尺寸
                img.thumbnail(target_size, Image.Resampling.LANCZOS)
                new_size = img.size
            else:
                # 直接缩放到目标尺寸
                img = img.resize(target_size, Image.Resampling.LANCZOS)
                new_size = target_size

            # 确定输出路径
            if output_path:
                output = Path(output_path)
            else:
                stem = path.stem
                ext = path.suffix
                output = path.parent / f"{stem}_resized{ext}"

            output.parent.mkdir(parents=True, exist_ok=True)

            # 保存（保持原格式）
            save_format = img.format or "PNG"
            img.save(output, format=save_format)

            logger.info(
                "图片缩放完成 | %s | %s → %s | ratio=%.2f",
                path.name,
                f"{original_size[0]}x{original_size[1]}",
                f"{new_size[0]}x{new_size[1]}",
                new_size[0] / original_size[0] if original_size[0] > 0 else 1,
            )
            return str(output)

    except ImageUtilsError:
        raise
    except Exception as e:
        raise ImageUtilsError(f"图片缩放异常: {str(e)}") from e


def convert_to_base64(image_path: str, include_prefix: bool = True) -> str:
    """
    将图片文件转换为 Base64 编码字符串

    Args:
        image_path: 图片文件路径
        include_prefix: 是否包含 data URI 前缀（如 "data:image/png;base64,"）

    Returns:
        str: Base64 编码字符串

    Raises:
        ImageUtilsError: 转换失败
    """
    path = Path(image_path)

    if not path.exists():
        raise ImageUtilsError(f"图片文件不存在: {image_path}")

    # 获取 MIME 类型
    ext = path.suffix.lower()
    mime_type = MIME_MAP.get(ext, "image/png")

    try:
        with open(path, "rb") as f:
            image_data = f.read()

        if len(image_data) == 0:
            raise ImageUtilsError(f"图片文件为空: {image_path}")

        base64_str = base64.b64encode(image_data).decode("utf-8")

        if include_prefix:
            result = f"data:{mime_type};base64,{base64_str}"
        else:
            result = base64_str

        logger.debug(
            "Base64 编码完成 | %s | size=%d bytes | base64_len=%d",
            path.name,
            len(image_data),
            len(result),
        )
        return result

    except ImageUtilsError:
        raise
    except Exception as e:
        raise ImageUtilsError(f"Base64 编码异常: {str(e)}") from e


def compress_image(
    image_path: str,
    quality: int = 85,
    max_size_kb: int = 500,
    output_path: Optional[str] = None,
) -> str:
    """
    压缩图片到指定质量/大小

    Args:
        image_path: 原始图片路径
        quality: JPEG 质量 (1-100)，默认85
        max_size_kb: 目标最大文件大小（KB），默认500KB
        output_path: 输出路径（可选）

    Returns:
        str: 压缩后的图片路径
    """
    path = Path(image_path)
    if not path.exists():
        raise ImageUtilsError(f"图片文件不存在: {image_path}")

    try:
        with Image.open(image_path) as img:
            # 转 RGB（JPEG 不支持 RGBA）
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            if output_path:
                output = Path(output_path)
            else:
                output = path.parent / f"{path.stem}_compressed.jpg"

            output.parent.mkdir(parents=True, exist_ok=True)

            # 保存为 JPEG 并逐渐降低质量直到满足大小要求
            current_quality = quality
            while current_quality >= 10:
                img.save(output, format="JPEG", quality=current_quality)
                file_size_kb = output.stat().st_size / 1024
                if file_size_kb <= max_size_kb:
                    break
                current_quality -= 10

            logger.info(
                "图片压缩完成 | %s | %d KB → %d KB | quality=%d",
                path.name,
                path.stat().st_size / 1024 if path.exists() else 0,
                output.stat().st_size / 1024,
                current_quality,
            )
            return str(output)

    except Exception as e:
        raise ImageUtilsError(f"图片压缩异常: {str(e)}") from e
