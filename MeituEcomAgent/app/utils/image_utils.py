"""图片处理工具函数"""
import logging
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image

logger = logging.getLogger(__name__)


class ImageUtilsError(Exception):
    """图片处理异常"""
    pass


def ensure_white_background(image_path: str, output_path: Optional[str] = None) -> str:
    """确保图片有纯白背景（处理PNG透明问题）"""
    path = Path(image_path)
    if not path.exists():
        raise ImageUtilsError("图片文件不存在: " + image_path)
    try:
        with Image.open(image_path) as img:
            if img.mode == "RGB":
                logger.debug("图片已是RGB模式，无需处理白底")
                return str(path)
            background = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            if img.mode in ("RGBA", "LA"):
                background.paste(img, mask=img.split()[-1])
            else:
                img_rgb = img.convert("RGB")
                background.paste(img_rgb)
            output = Path(output_path) if output_path else path.parent / (path.stem + "_whitebg.jpg")
            background.save(output, "JPEG", quality=95)
            logger.info("白底填充完成 | %s -> %s", path.name, output.name)
            return str(output)
    except Exception as e:
        raise ImageUtilsError("白底处理异常: " + str(e)) from e


def crop_center(image_path: str, crop_ratio: float = 0.6, output_path: Optional[str] = None) -> str:
    """中心裁剪图片（用于细节特写）"""
    path = Path(image_path)
    if not path.exists():
        raise ImageUtilsError("图片文件不存在: " + image_path)
    try:
        with Image.open(image_path) as img:
            w, h = img.size
            new_w, new_h = int(w * crop_ratio), int(h * crop_ratio)
            left, top = (w - new_w) // 2, (h - new_h) // 2
            cropped = img.crop((left, top, left + new_w, top + new_h))
            output = Path(output_path) if output_path else path.parent / (path.stem + "_crop.jpg")
            if cropped.mode in ("RGBA", "P"):
                bg = Image.new("RGB", cropped.size, (255, 255, 255))
                mask = cropped.split()[-1] if cropped.mode in ("RGBA", "LA") else None
                bg.paste(cropped.convert("RGBA"), mask=mask)
                bg.save(output, "JPEG", quality=95)
            else:
                cropped.convert("RGB").save(output, "JPEG", quality=95)
            logger.info("中心裁剪完成 | %s -> %s | ratio=%.0f%%", path.name, output.name, crop_ratio * 100)
            return str(output)
    except Exception as e:
        raise ImageUtilsError("裁剪异常: " + str(e)) from e


def add_size_label(image_path: str, size_text: str = "", output_path: Optional[str] = None) -> str:
    """
    添加专业尺寸标注线（长W、宽H、深D，单位cm）
    标注线在图片外围白色扩展区域，产品图本身不变
    """
    path = Path(image_path)
    if not path.exists():
        raise ImageUtilsError("图片文件不存在: " + image_path)
    try:
        from PIL import ImageDraw, ImageFont
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            orig_w, orig_h = img.size
            margin = max(60, int(orig_w * 0.15))
            new_w = orig_w + margin * 2
            new_h = orig_h + margin * 2
            canvas = Image.new("RGB", (new_w, new_h), (255, 255, 255))
            canvas.paste(img, (margin, margin))
            draw = ImageDraw.Draw(canvas)
            # 估算尺寸
            product_w_cm = round(orig_w / 800 * 12, 1)
            product_h_cm = round(orig_h / 800 * 12, 1)
            product_d_cm = round(min(orig_w, orig_h) / 800 * 6, 1)
            try:
                font_num = ImageFont.truetype("arial.ttf", 20)
            except Exception:
                font_num = ImageFont.load_default()
            line_color = (60, 60, 60)
            arrow_color = (80, 80, 80)
            # W标注 (下方)
            y_w = orig_h + margin + 20
            x_left = margin
            x_right = margin + orig_w
            y_arrow_w = y_w + 5
            draw.line([(x_left, y_w), (x_right, y_w)], fill=line_color, width=2)
            draw.polygon([(x_left, y_arrow_w), (x_left + 10, y_arrow_w - 5), (x_left + 10, y_arrow_w + 5)], fill=arrow_color)
            draw.polygon([(x_right, y_arrow_w), (x_right - 10, y_arrow_w - 5), (x_right - 10, y_arrow_w + 5)], fill=arrow_color)
            w_text = "W: " + str(product_w_cm) + " cm"
            bbox_w = draw.textbbox((0, 0), w_text, font=font_num)
            tw_w = bbox_w[2] - bbox_w[0]
            draw.text(((x_left + x_right - tw_w) // 2, y_w + 10), w_text, fill=line_color, font=font_num)
            # H标注 (右侧)
            x_h = orig_w + margin + 20
            y_top = margin
            y_bottom = margin + orig_h
            x_arrow_h = x_h + 5
            draw.line([(x_h, y_top), (x_h, y_bottom)], fill=line_color, width=2)
            draw.polygon([(x_h, y_top), (x_arrow_h - 5, y_top + 10), (x_arrow_h + 5, y_top + 10)], fill=arrow_color)
            draw.polygon([(x_h, y_bottom), (x_arrow_h - 5, y_bottom - 10), (x_arrow_h + 5, y_bottom - 10)], fill=arrow_color)
            h_text = "H: " + str(product_h_cm) + " cm"
            # 竖排文字
            txt_img = Image.new("RGBA", (draw.textbbox((0, 0), h_text, font=font_num)[2] + 10, 30), (255, 255, 255, 0))
            txt_draw = ImageDraw.Draw(txt_img)
            txt_draw.text((5, 2), h_text, fill=line_color, font=font_num)
            txt_img = txt_img.rotate(90, expand=True)
            th = draw.textbbox((0, 0), h_text, font=font_num)[2]
            canvas.paste(txt_img, (x_h + 10, (y_top + y_bottom - th) // 2), txt_img)
            # D标注 (左上方斜向)
            diag_x1 = margin + int(orig_w * 0.15)
            diag_y1 = margin + int(orig_h * 0.15)
            diag_x2 = diag_x1 + int(orig_w * 0.25)
            diag_y2 = diag_y1 + int(orig_h * 0.25)
            offset = 45
            line_x1 = diag_x1 - offset
            line_y1 = diag_y1
            line_x2 = diag_x2 - offset
            line_y2 = diag_y2
            draw.line([(line_x1, line_y1), (line_x2, line_y2)], fill=line_color, width=2)
            half = offset // 2
            draw.line([(line_x1, line_y1), (line_x1 + half, line_y1 - half)], fill=line_color, width=2)
            draw.line([(line_x1, line_y1), (line_x1 + half, line_y1 + half)], fill=line_color, width=2)
            draw.line([(line_x2, line_y2), (line_x2 - half, line_y2 - half)], fill=line_color, width=2)
            draw.line([(line_x2, line_y2), (line_x2 - half, line_y2 + half)], fill=line_color, width=2)
            d_text = "D: " + str(product_d_cm)
            mid_x = (line_x1 + line_x2) // 2 - 40
            mid_y = (line_y1 + line_y2) // 2 + 5
            draw.text((mid_x, mid_y), d_text, fill=line_color, font=font_num)
            # 标题
            try:
                font_title = ImageFont.truetype("arial.ttf", 28)
            except Exception:
                font_title = ImageFont.load_default()
            title = "Product Dimensions"
            bbox_t = draw.textbbox((0, 0), title, font=font_title)
            tw_t = bbox_t[2] - bbox_t[0]
            draw.text(((new_w - tw_t) // 2, 8), title, fill=(100, 100, 100), font=font_title)
            output = Path(output_path) if output_path else path.parent / (path.stem + "_dimension.jpg")
            canvas.save(output, "JPEG", quality=95)
            logger.info("尺寸标注完成 | %s | W=%.1f H=%.1f D=%.1f cm", output.name, product_w_cm, product_h_cm, product_d_cm)
            return str(output)
    except Exception as e:
        raise ImageUtilsError("标注异常: " + str(e)) from e


def composite_product_to_scene(
    product_path: str,
    scene_background_path: str,
    output_path: Optional[str] = None,
) -> str:
    """
    从白底产品图提取产品，合成到场景背景上。
    
    使用颜色阈值从白底图抠出产品（非白色像素=产品），
    然后按比例缩放并居中放置到场景背景上。
    
    Args:
        product_path: 白底产品图路径（white_bg_main 输出）
        scene_background_path: 场景背景图路径（txt2img 输出）
        output_path: 输出路径
    
    Returns:
        str: 合成图路径
    """
    product_file = Path(product_path)
    scene_file = Path(scene_background_path)
    
    if not product_file.exists():
        logger.warning("产品图不存在，跳过合成: %s", product_path)
        return scene_background_path
    if not scene_file.exists():
        logger.warning("场景背景不存在，跳过合成: %s", scene_background_path)
        return product_path
    
    try:
        with Image.open(product_file) as product_img:
            product_img = product_img.convert("RGBA")
            pw, ph = product_img.size
            
            # 创建遮罩：白色/接近白色的像素视为背景（透明），其余为产品
            # 阈值：RGB各通道 > 240 且 alpha > 0 视为白色背景
            data = product_img.getdata()
            new_data = []
            for item in data:
                r, g, b, a = item
                # 白色或接近白色 + 有透明度 = 背景，设为透明
                if r > 235 and g > 235 and b > 235:
                    new_data.append((r, g, b, 0))
                elif a < 30:
                    new_data.append((r, g, b, 0))
                else:
                    new_data.append((r, g, b, 255))
            
            product_img.putdata(new_data)
            
            with Image.open(scene_file) as scene_img:
                scene_img = scene_img.convert("RGBA")
                sw, sh = scene_img.size
                
                # 缩放产品到场景的60-70%大小，保持比例
                scale_w = sw * 0.65 / pw
                scale_h = sh * 0.7 / ph
                scale = min(scale_w, scale_h)
                
                new_pw = int(pw * scale)
                new_ph = int(ph * scale)
                product_resized = product_img.resize((new_pw, new_ph), Image.LANCZOS)
                
                # 居中放置产品
                pos_x = (sw - new_pw) // 2
                pos_y = (sh - new_ph) // 2 - int(sh * 0.05)  # 略微偏上
                
                # 合成
                scene_img.paste(product_resized, (pos_x, pos_y), product_resized)
                
                # 保存
                output = Path(output_path) if output_path else scene_file.parent / (scene_file.stem + "_composite.jpg")
                scene_img.convert("RGB").save(output, "JPEG", quality=95)
                
                logger.info(
                    "场景合成完成 | product=%s(%dx%d) scene=%s(%dx%d) -> %s(%dx%d)",
                    product_file.name, pw, ph,
                    scene_file.name, sw, sh,
                    output.name, sw, sh,
                )
                return str(output)
    except Exception as e:
        logger.warning("场景合成失败，使用原场景图: %s", str(e))
        return scene_background_path



def overlay_selling_points(image_path: str, selling_points: str, output_path: Optional[str] = None) -> str:
    """在图片底部叠加商品卖点文案"""
    if not selling_points:
        return image_path
    path = Path(image_path)
    if not path.exists():
        return image_path
    try:
        from PIL import ImageDraw, ImageFont
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            w, h = img.size
            bar_h = int(h * 0.18)
            overlay_bg = Image.new("RGBA", (w, bar_h), (255, 255, 255, 220))
            img_rgba = img.convert("RGBA")
            img_rgba.paste(overlay_bg, (0, h - bar_h), overlay_bg)
            draw = ImageDraw.Draw(img_rgba)
            points = [p.strip() for p in selling_points.replace("|", "\n").split("\n") if p.strip()]
            if not points:
                return image_path
            try:
                font = ImageFont.truetype("arial.ttf", max(14, int(bar_h / (len(points) + 1) * 0.7)))
            except Exception:
                font = ImageFont.load_default()
            y_start = h - bar_h + 8
            for i, point in enumerate(points[:5]):
                y = y_start + i * (bar_h // max(len(points), 3))
                if y > h - 10:
                    break
                draw.text((12, y), "  " + point, fill=(40, 40, 40), font=font)
            output = Path(output_path) if output_path else path.parent / (path.stem + "_overlay.jpg")
            img_rgba.convert("RGB").save(output, "JPEG", quality=95)
            logger.info("文案叠加完成 | %s | points=%d", output.name, len(points))
            return str(output)
    except Exception as e:
        logger.warning("文案叠加失败: %s", str(e))
        return image_path
