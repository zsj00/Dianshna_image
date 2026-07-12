"""
文件归档等工具函数
"""
import os
import json
import shutil
import zipfile
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from app.config import settings

logger = logging.getLogger(__name__)


def ensure_directory(dir_path: str) -> Path:
    """
    确保目录存在，不存在则创建

    Args:
        dir_path: 目录路径

    Returns:
        Path: 目录Path对象
    """
    path = Path(dir_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def generate_output_filename(prefix: str = "image", extension: str = "png") -> str:
    """
    生成带时间戳的输出文件名

    Args:
        prefix: 文件名前缀
        extension: 文件扩展名

    Returns:
        str: 生成的文件名
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{timestamp}.{extension}"


def save_generated_image(image_data: bytes, filename: Optional[str] = None) -> str:
    """
    保存生成的图片到输出目录

    Args:
        image_data: 图片二进制数据
        filename: 文件名（可选）

    Returns:
        str: 保存后的文件路径
    """
    base_dir = Path(__file__).resolve().parent.parent
    output_dir = base_dir / settings.OUTPUT_DIR
    ensure_directory(str(output_dir))

    if not filename:
        filename = generate_output_filename()

    filepath = output_dir / filename
    with open(filepath, "wb") as f:
        f.write(image_data)

    return str(filepath)


def create_task_dir(task_id: str) -> Path:
    """
    为任务创建独立的输出目录

    Args:
        task_id: 任务ID

    Returns:
        Path: 任务目录路径
    """
    base_dir = Path(__file__).resolve().parent.parent
    task_dir = base_dir / settings.OUTPUT_DIR / task_id
    ensure_directory(str(task_dir))
    return task_dir


def copy_to_task_dir(task_dir: Path, file_paths: List[str]) -> List[str]:
    """
    将生成的文件复制到任务目录中

    Args:
        task_dir: 目标任务目录
        file_paths: 源文件路径列表

    Returns:
        List[str]: 复制后的文件路径列表
    """
    copied = []
    for src_path in file_paths:
        src = Path(src_path)
        if not src.exists():
            continue

        # 根据图片类型重命名
        dst = task_dir / src.name
        shutil.copy2(src, dst)
        copied.append(str(dst))

    return copied


def archive_task(task_id: str, file_paths: List[str]) -> str:
    """
    将任务相关的文件归档到任务目录

    Args:
        task_id: 任务ID
        file_paths: 文件路径列表

    Returns:
        str: 归档目录路径
    """
    task_dir = create_task_dir(task_id)
    copy_to_task_dir(task_dir, file_paths)
    return str(task_dir)


def save_report(task_dir: Path, report_data: Dict[str, Any]) -> str:
    """
    保存审核报告为 JSON 文件

    Args:
        task_dir: 任务目录
        report_data: 报告数据

    Returns:
        str: 报告文件路径
    """
    report_path = task_dir / "report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2, default=str)
    return str(report_path)


def clean_output_dir(max_age_days: int = 7) -> int:
    """
    清理超过指定天数的输出文件

    Args:
        max_age_days: 最大保留天数

    Returns:
        int: 清理的文件数量
    """
    base_dir = Path(__file__).resolve().parent.parent
    output_dir = base_dir / settings.OUTPUT_DIR

    if not output_dir.exists():
        return 0

    cleaned = 0
    cutoff = datetime.now().timestamp() - (max_age_days * 86400)

    for item in output_dir.iterdir():
        if item.is_dir():
            # 检查目录修改时间
            if item.stat().st_mtime < cutoff:
                shutil.rmtree(item, ignore_errors=True)
                cleaned += 1
        elif item.is_file():
            if item.stat().st_mtime < cutoff:
                item.unlink()
                cleaned += 1

    return cleaned


# ==================== 新增强化函数 ====================

def create_output_directory(platform: str, product_name: str) -> str:
    """
    在 output/ 目录下创建结构化的子目录

    目录结构: output/{platform}/{product_name}_{timestamp}/

    Args:
        platform: 平台名称（如 amazon, taobao）
        product_name: 商品名称（将做安全处理替换特殊字符）

    Returns:
        str: 创建的目录路径
    """
    # 安全处理商品名称中的特殊字符
    safe_product = _sanitize_filename(product_name)
    safe_product = safe_product[:50] if len(safe_product) > 50 else safe_product

    # 生成时间戳
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 构建目录名
    dir_name = f"{safe_product}_{timestamp}"

    # 构建完整路径
    base_dir = Path(__file__).resolve().parent.parent
    output_path = base_dir / settings.OUTPUT_DIR / platform / dir_name
    ensure_directory(str(output_path))

    logger.info("创建输出目录 | %s", output_path)
    return str(output_path)


def save_images(images: List[dict], output_dir: str) -> List[str]:
    """
    将生成的图片保存到指定目录

    支持两种输入格式:
    - list of dict: [{"data": bytes, "filename": "xxx.png", "type": "white_bg_main"}, ...]
    - list of str: ["path/to/img1.png", "path/to/img2.png", ...]

    返回保存后的文件路径列表

    Args:
        images: 图片列表（dict列表 或 路径字符串列表）
        output_dir: 目标输出目录

    Returns:
        List[str]: 保存后的文件路径列表
    """
    saved_paths = []

    target_dir = ensure_directory(output_dir)

    for img in images:
        if isinstance(img, dict):
            # 字典格式：包含 data(二进制) 或 path(路径)
            if "data" in img and isinstance(img["data"], bytes):
                filename = img.get("filename", generate_output_filename())
                img_type = img.get("type", "")
                if img_type and not filename.startswith(img_type):
                    filename = f"{img_type}_{filename}"

                filepath = target_dir / filename
                with open(filepath, "wb") as f:
                    f.write(img["data"])
                saved_paths.append(str(filepath))
                logger.debug("图片已保存 | %s", filepath.name)

            elif "path" in img and isinstance(img["path"], str):
                src = Path(img["path"])
                if src.exists():
                    img_type = img.get("type", "")
                    dest_name = f"{img_type}_{src.name}" if img_type else src.name
                    dest = target_dir / dest_name
                    shutil.copy2(src, dest)
                    saved_paths.append(str(dest))
                    logger.debug("图片已复制 | %s → %s", src.name, dest.name)
                else:
                    logger.warning("源图片不存在 | %s", img["path"])

        elif isinstance(img, str):
            # 字符串格式：直接作为文件路径复制
            src = Path(img)
            if src.exists():
                dest = target_dir / src.name
                shutil.copy2(src, dest)
                saved_paths.append(str(dest))
            else:
                logger.warning("源图片不存在 | %s", img)

        else:
            logger.warning("不支持的图片格式: %s", type(img))

    logger.info(
        "图片保存完成 | 总计=%d | 成功=%d | 目录=%s",
        len(images),
        len(saved_paths),
        output_dir,
    )
    return saved_paths


def generate_report(task_result: dict, output_dir: str) -> str:
    """
    将任务结果保存为 JSON 格式的审核报告

    报告包含:
    - 任务信息（task_id, platform, product, status, created_at）
    - 使用的 prompts（每种图片类型的 prompt）
    - 图片列表（路径、类型、合规状态、审核结果）
    - 审核统计（合规率、平均分）
    - 重试记录（每轮重试的 prompt 变化）

    Args:
        task_result: 完整的任务结果字典
        output_dir: 输出目录

    Returns:
        str: 报告文件路径
    """
    ensure_directory(output_dir)

    # 构建结构化报告
    report = {
        "report_version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "task_info": {
            "task_id": task_result.get("task_id", ""),
            "platform": task_result.get("platform", ""),
            "product": task_result.get("product", ""),
            "status": task_result.get("status", ""),
            "created_at": task_result.get("created_at", ""),
        },
        "prompts": task_result.get("parse_result", {}).get("image_set", {}),
        "compliance_checklist": task_result.get("parse_result", {}).get(
            "compliance_checklist", []
        ),
        "images": task_result.get("images", []),
        "compliance_stats": task_result.get("compliance_stats", {}),
        "total_retries": task_result.get("total_retries", 0),
        "summary": task_result.get("summary", ""),
        "pipeline_log": task_result.get("pipeline_log", []),
    }

    report_path = Path(output_dir) / "report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    logger.info("审核报告已生成 | %s", report_path)
    return str(report_path)


def archive_results(task_id: str, output_dir: str) -> str:
    """
    将所有结果打包为 zip 文件

    打包 output_dir 下所有文件到 zip 中，
    zip 文件保存在 output_dir 的上级目录。

    Args:
        task_id: 任务ID
        output_dir: 要打包的输出目录

    Returns:
        str: zip 文件路径

    Raises:
        FileNotFoundError: 输出目录不存在
        ValueError: 目录为空
    """
    src_dir = Path(output_dir)
    if not src_dir.exists():
        raise FileNotFoundError(f"输出目录不存在: {output_dir}")

    # 收集所有文件
    files_to_archive = list(src_dir.rglob("*"))
    file_items = [f for f in files_to_archive if f.is_file()]

    if not file_items:
        raise ValueError(f"输出目录为空: {output_dir}")

    # zip 保存在上级目录
    zip_filename = f"{task_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    zip_path = src_dir.parent / zip_filename

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in file_items:
            # 使用相对于 src_dir 的路径作为 zip 内部路径
            arcname = file_path.relative_to(src_dir.parent)
            zf.write(file_path, arcname)

    zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
    logger.info(
        "结果已打包 | zip=%s | files=%d | size=%.2f MB",
        zip_path.name,
        len(file_items),
        zip_size_mb,
    )
    return str(zip_path)


def cleanup_old_outputs(days: int = 30) -> dict:
    """
    清理指定天数前的旧输出文件

    扫描 output/ 目录，删除超过 days 天的目录和文件。
    保留 .gitkeep 文件。

    Args:
        days: 保留天数，默认30天

    Returns:
        dict: 清理统计
        {
            "directories_removed": 3,
            "files_removed": 12,
            "total_size_freed_mb": 45.2
        }
    """
    base_dir = Path(__file__).resolve().parent.parent
    output_dir = base_dir / settings.OUTPUT_DIR

    if not output_dir.exists():
        logger.info("output 目录不存在，无需清理")
        return {"directories_removed": 0, "files_removed": 0, "total_size_freed_mb": 0}

    cutoff = datetime.now().timestamp() - (days * 86400)

    dirs_removed = 0
    files_removed = 0
    total_size_freed = 0

    for item in output_dir.iterdir():
        # 跳过 .gitkeep
        if item.name == ".gitkeep":
            continue

        try:
            item_mtime = item.stat().st_mtime
        except OSError:
            continue

        if item_mtime < cutoff:
            if item.is_dir():
                # 计算目录大小
                dir_size = sum(
                    f.stat().st_size
                    for f in item.rglob("*")
                    if f.is_file()
                )
                total_size_freed += dir_size
                shutil.rmtree(item, ignore_errors=True)
                dirs_removed += 1
                logger.debug("清理目录 | %s", item.name)
            elif item.is_file():
                total_size_freed += item.stat().st_size
                item.unlink()
                files_removed += 1
                logger.debug("清理文件 | %s", item.name)

    size_mb = total_size_freed / (1024 * 1024)
    logger.info(
        "清理完成 | 目录=%d | 文件=%d | 释放空间=%.2f MB",
        dirs_removed,
        files_removed,
        size_mb,
    )
    return {
        "directories_removed": dirs_removed,
        "files_removed": files_removed,
        "total_size_freed_mb": round(size_mb, 2),
    }


# ==================== 内部工具 ====================

def _sanitize_filename(name: str) -> str:
    """
    清理文件名中的非法字符

    Args:
        name: 原始名称

    Returns:
        str: 清理后的安全文件名
    """
    # 替换非法字符为下划线
    illegal_chars = '<>:"/\\|?*'
    for char in illegal_chars:
        name = name.replace(char, "_")
    # 截去首尾空白和多余下划线
    name = name.strip().strip("._")
    # 压缩连续下划线
    while "__" in name:
        name = name.replace("__", "_")
    return name if name else "untitled"
