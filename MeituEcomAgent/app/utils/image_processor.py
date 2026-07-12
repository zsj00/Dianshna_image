"""
图片预处理工具 — AI抠图、白底合成、尺寸调整

依赖: rembg + Pillow
"""
import io
import logging
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image

logger = logging.getLogger(__name__)


class ImageProcessorError(Exception):
    """图片处理异常"""

    pass


class ImagePreprocessor:
    """图片预处理器，负责抠图去背景和白底合成"""

    @staticmethod
    def remove_background(image_path: str) -> bytes:
        """
        AI 自动去除图片背景

        使用 rembg（基于 U²-Net）进行背景移除，输出 RGBA PNG 字节。

        Args:
            image_path: 输入图片路径

        Returns:
            bytes: 去背景后的 RGBA PNG 图片字节

        Raises:
            ImageProcessorError: 处理失败
        """
        try:
            from rembg import remove
        except ImportError:
            raise ImageProcessorError("请安装 rembg: pip install rembg")

        src = Path(image_path)
        if not src.exists():
            raise ImageProcessorError(f"图片不存在: {image_path}")

        try:
            input_bytes = src.read_bytes()
            output_bytes = remove(input_bytes, model_name="u2netp")
            logger.info("去背景完成 | input=%s | output_size=%d bytes", src.name, len(output_bytes))
            return output_bytes
        except Exception as e:
            raise ImageProcessorError(f"去背景失败: {str(e)}") from e

    @staticmethod
    def make_white_background(
        image_path: str,
        target_size: Tuple[int, int] = (1600, 1600),
        product_ratio_min: float = 0.75,
    ) -> bytes:
        """
        去背景后合成纯白底商品图

        步骤:
        1. AI 自动去背景
        2. 创建纯白 (255,255,255) 画布
        3. 将前景商品居中放置，保持商品占比 ≥ product_ratio_min
        4. 输出 RGB JPEG

        Args:
            image_path: 输入图片路径
            target_size: 目标画布尺寸 (width, height)
            product_ratio_min: 商品在画布中的最小占比（0~1）

        Returns:
            bytes: 白底合成后的 JPEG 图片字节

        Raises:
            ImageProcessorError: 处理失败
        """
        try:
            from rembg import remove
        except ImportError:
            raise ImageProcessorError("请安装 rembg: pip install rembg")

        src = Path(image_path)
        if not src.exists():
            raise ImageProcessorError(f"图片不存在: {image_path}")

        try:
            # 1. 去背景（使用轻量 u2netp 模型 ~4MB，比 u2net 快 10 倍）
            input_bytes = src.read_bytes()
            foreground_bytes = remove(input_bytes, model_name="u2netp")
            foreground = Image.open(io.BytesIO(foreground_bytes)).convert("RGBA")

            # 2. 创建目标画布
            canvas = Image.new("RGBA", target_size, (255, 255, 255, 255))

            # 3. 缩放前景以适应画布
            fg_w, fg_h = foreground.size
            canvas_w, canvas_h = target_size

            # 计算缩放比例，让商品占比符合要求
            max_fg_area = canvas_w * canvas_h * 1.0  # 商品最大占画布 100%
            min_fg_area = canvas_w * canvas_h * product_ratio_min
            fg_area = fg_w * fg_h

            if fg_area > max_fg_area:
                scale = (max_fg_area / fg_area) ** 0.5
            elif fg_area < min_fg_area:
                scale = (min_fg_area / fg_area) ** 0.5
            else:
                scale = 1.0

            new_w = int(fg_w * scale)
            new_h = int(fg_h * scale)

            # 安全限制：缩略尺寸不超过画布
            if new_w > canvas_w or new_h > canvas_h:
                scale_factor = min(canvas_w / new_w, canvas_h / new_h)
                new_w = int(new_w * scale_factor)
                new_h = int(new_h * scale_factor)

            foreground_resized = foreground.resize((new_w, new_h), Image.LANCZOS)

            # 4. 居中放置
            paste_x = (canvas_w - new_w) // 2
            paste_y = (canvas_h - new_h) // 2
            canvas.paste(foreground_resized, (paste_x, paste_y), foreground_resized)

            # 5. 转为 RGB JPEG
            rgb_image = canvas.convert("RGB")
            output_buffer = io.BytesIO()
            rgb_image.save(output_buffer, format="JPEG", quality=95)
            output_bytes = output_buffer.getvalue()

            logger.info(
                "白底合成完成 | input=%s | target=%dx%d | output_size=%d bytes",
                src.name, canvas_w, canvas_h, len(output_bytes),
            )
            return output_bytes

        except Exception as e:
            raise ImageProcessorError(f"白底合成失败: {str(e)}") from e

    @staticmethod
    def save_image(image_bytes: bytes, output_path: str) -> str:
        """
        保存处理后的图片

        Args:
            image_bytes: 图片字节数据
            output_path: 输出路径

        Returns:
            str: 保存后的文件路径
        """
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "wb") as f:
            f.write(image_bytes)
        logger.info("图片已保存 | path=%s | size=%d bytes", output_path, len(image_bytes))
        return str(out)
