"""
生图调度Agent - 负责根据解析后的规则调度图片生成流程

核心功能:
- 接收 rule_parser 生成的 prompts
- 加载 workflows/ 目录下的工作流JSON
- 将 prompt 注入工作流的 CLIPTextEncode 节点
- 调度 ComfyUI 生图任务
- 任务状态跟踪（pending / generating / completed / failed）
- 支持并发生成
"""
import os
import json
import uuid
import logging
import asyncio
from enum import Enum
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Any

from app.config import settings
from app.services.comfyui_service import ComfyUIClient, ComfyUIError

# 配置日志
logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """任务状态枚举"""

    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class ImageGeneratorError(Exception):
    """生图异常基类"""

    pass


class WorkflowLoadError(ImageGeneratorError):
    """工作流加载异常"""

    pass


class PromptInjectError(ImageGeneratorError):
    """Prompt注入异常"""

    pass


class GenerationError(ImageGeneratorError):
    """生图异常"""

    pass


# 图片类型到工作流文件的映射
IMAGE_TYPE_WORKFLOW_MAP = {
    "white_bg_main": "workflow_white_bg.json",
    "scene_lifestyle": "workflow_scene_txt2img.json",  # txt2img 生成场景背景，后处理时合成产品
    "detail_closeup": "workflow_detail.json",
    "scale_comparison": "workflow_white_bg.json",
    # 默认工作流（回退到白底主图工作流）
    "_default": "workflow_white_bg.json",
}


class ImageGeneratorAgent:
    """生图调度Agent，协调规则解析结果与 ComfyUI 生图流程"""

    def __init__(self, server_address: Optional[str] = None):
        """
        初始化生图调度Agent

        Args:
            server_address: ComfyUI 服务地址（可选，默认从配置读取）
        """
        self.comfyui = ComfyUIClient(server_address=server_address)

        # 工作流目录和输出目录（使用绝对路径）
        base_dir = Path(__file__).resolve().parent.parent.parent
        self.workflow_dir = base_dir / settings.WORKFLOW_DIR
        self.output_dir = base_dir / settings.OUTPUT_DIR

        # 确 保输出目录存在
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # 任务状态跟踪
        self._tasks: Dict[str, dict] = {}

        logger.info(
            "ImageGeneratorAgent initialized | workflow_dir=%s | output_dir=%s",
            self.workflow_dir,
            self.output_dir,
        )

    # ==================== 任务状态管理 ====================

    def _create_task(self, image_type: str) -> str:
        """
        创建任务并返回 task_id

        Args:
            image_type: 图片类型

        Returns:
            str: task_id
        """
        task_id = str(uuid.uuid4())[:12]
        self._tasks[task_id] = {
            "task_id": task_id,
            "image_type": image_type,
            "status": TaskStatus.PENDING,
            "created_at": datetime.now().isoformat(),
            "prompt_id": None,
            "output_paths": [],
            "error": None,
        }
        return task_id

    def _update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        prompt_id: Optional[str] = None,
        output_paths: Optional[List[str]] = None,
        error: Optional[str] = None,
    ) -> None:
        """更新任务状态"""
        if task_id not in self._tasks:
            return

        task = self._tasks[task_id]
        if status:
            task["status"] = status
            logger.info("任务状态更新 | task_id=%s | status=%s", task_id, status.value)
        if prompt_id:
            task["prompt_id"] = prompt_id
        if output_paths:
            task["output_paths"] = output_paths
        if error:
            task["error"] = error

    def get_task_status(self, task_id: str) -> Optional[dict]:
        """
        获取任务状态

        Args:
            task_id: 任务ID

        Returns:
            Optional[dict]: 任务状态字典
        """
        return self._tasks.get(task_id)

    # ==================== 工作流加载 ====================

    @staticmethod
    def _convert_gui_to_api(workflow: dict) -> dict:
        """
        将 ComfyUI GUI 格式的工作流转换为 API 格式

        GUI 格式（保存的JSON文件）:
        {
            "nodes": [{"id": 3, "type": "CLIPTextEncode", "inputs": [...], "widgets_values": [...]}],
            "links": [[link_id, from_node, from_slot, to_node, to_slot, type]]
        }

        API 格式（/prompt 端点需要的格式）:
        {
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "...", "clip": ["2", 1]}}
        }
        """
        links = workflow.get("links", [])
        nodes = workflow.get("nodes", [])

        if not nodes:
            return workflow

        # 构建 link 索引: link_id → (from_node, from_slot)
        link_map = {}
        for link in links:
            link_id = link[0]
            link_map[link_id] = (link[1], link[2])

        api_workflow = {}
        for node in nodes:
            node_id = str(node["id"])
            api_workflow[node_id] = {
                "class_type": node["type"],
                "inputs": {},
            }

            widget_idx = 0
            widgets_values = node.get("widgets_values", [])
            control_after_generate_opts = {"randomize", "fixed", "increment", "decrement"}

            # 节点没有 inputs 数组时的回退处理
            # 某些 ComfyUI 内置节点（如 CheckpointLoaderSimple）的 GUI JSON 不包含 inputs
            inputs = node.get("inputs", [])
            if not inputs and widgets_values:
                node_type = node["type"]
                if node_type == "CheckpointLoaderSimple":
                    inputs = [{"name": "ckpt_name", "widget": {"name": "ckpt_name"}}]
                elif node_type == "LoadImage":
                    inputs = [{"name": "image", "widget": {"name": "image"}}]
                elif node_type == "EmptyLatentImage":
                    inputs = [
                        {"name": "width", "widget": {"name": "width"}},
                        {"name": "height", "widget": {"name": "height"}},
                        {"name": "batch_size", "widget": {"name": "batch_size"}},
                    ]
                elif node_type == "LoraLoader":
                    inputs = [
                        {"name": "lora_name", "widget": {"name": "lora_name"}},
                        {"name": "strength_model", "widget": {"name": "strength_model"}},
                        {"name": "strength_clip", "widget": {"name": "strength_clip"}},
                    ]

            for inp in inputs:
                input_name = inp["name"]

                if inp.get("link") is not None:
                    # 链接输入：解析链接 → [from_node_id, from_slot]
                    src = link_map[inp["link"]]
                    api_workflow[node_id]["inputs"][input_name] = [
                        str(src[0]),
                        src[1],
                    ]
                elif "widget" in inp and inp["widget"] is not None:
                    # Widget 输入：从 widgets_values 取值
                    if widget_idx < len(widgets_values):
                        api_workflow[node_id]["inputs"][input_name] = (
                            widgets_values[widget_idx]
                        )
                        widget_idx += 1

                        # KSampler 等节点的 seed widget 在 GUI 格式中会额外序列化
                        # control_after_generate 选项（"randomize"/"fixed"/"increment"/"decrement"）
                        # 该值不是 API 输入，需跳过以避免后续 widget 值错位
                        if (
                            input_name == "seed"
                            and widget_idx < len(widgets_values)
                        ):
                            next_val = widgets_values[widget_idx]
                            if isinstance(next_val, str) and next_val in control_after_generate_opts:
                                widget_idx += 1
                    else:
                        # 防御：缺少 widget 值
                        api_workflow[node_id]["inputs"][input_name] = ""

        return api_workflow

    def load_workflow(self, workflow_name: str) -> dict:
        """
        从 workflows/ 目录加载工作流JSON文件

        Args:
            workflow_name: 工作流文件名（如 "product_white_bg.json"）

        Returns:
            dict: 工作流字典

        Raises:
            WorkflowLoadError: 加载失败
        """
        workflow_path = self.workflow_dir / workflow_name

        if not workflow_path.exists():
            raise WorkflowLoadError(
                f"工作流文件不存在: {workflow_path}\n"
                f"可用的工作流文件: {list(self.workflow_dir.glob('*.json'))}"
            )

        try:
            with open(workflow_path, "r", encoding="utf-8-sig") as f:
                workflow = json.load(f)

            # 转换 GUI 格式 → API 格式
            if "nodes" in workflow and isinstance(workflow.get("nodes"), list):
                workflow = self._convert_gui_to_api(workflow)

            logger.info(
                "工作流加载成功 | name=%s | nodes=%d",
                workflow_name,
                len(workflow),
            )
            return workflow

        except json.JSONDecodeError as e:
            raise WorkflowLoadError(f"工作流JSON解析失败: {str(e)}") from e
        except Exception as e:
            raise WorkflowLoadError(f"加载工作流失�: {str(e)}") from e

    # ==================== Prompt 注入 ====================

    def inject_prompt(
        self,
        workflow: dict,
        positive: str,
        negative: str,
    ) -> dict:
        """
        将 positive/negative prompt 注入到工作流的 CLIPTextEncode 节点中

        自动检测工作流中所有 CLIPTextEncode 节点：
        - 节点ID最小的 → 注入 positive prompt
        - 节点ID最大的 → 注入 negative prompt

        Args:
            workflow: ComfyUI 工作流字典（API格式）
            positive: 正向提示词
            negative: 负向提示词

        Returns:
            dict: 注入后的工作流字典（深拷贝，不修改原始数据）

        Raises:
            PromptInjectError: 未找到 CLIPTextEncode 节点
        """
        import copy
        workflow = copy.deepcopy(workflow)

        # 查找所有 CLIPTextEncode 节点
        clip_nodes = []
        for node_id, node_data in workflow.items():
            class_type = node_data.get("class_type", "")
            if class_type == "CLIPTextEncode":
                clip_nodes.append((int(node_id), node_id))

        if not clip_nodes:
            raise PromptInjectError(
                "工作流中未找到 CLIPTextEncode 节点，无法注入 prompt"
            )

        # 按节点ID排序
        clip_nodes.sort(key=lambda x: x[0])

        if len(clip_nodes) >= 2:
            # 两个节点：较小的注入 positive，较大的注入 negative
            _, positive_node_id = clip_nodes[0]
            _, negative_node_id = clip_nodes[1]
        else:
            # 只有一个节点：注入 positive
            positive_node_id = clip_nodes[0][1]
            negative_node_id = None

        # 注入 positive prompt
        workflow[positive_node_id]["inputs"]["text"] = positive
        logger.debug("Positive prompt 注入 | node=%s", positive_node_id)

        # 注入 negative prompt
        if negative_node_id:
            workflow[negative_node_id]["inputs"]["text"] = negative
            logger.debug("Negative prompt 注入 | node=%s", negative_node_id)
        else:
            logger.warning("工作流中只有一个 CLIPTextEncode 节点，无法注入 negative prompt")

        return workflow

    def inject_resolution(
        self,
        workflow: dict,
        width: int,
        height: int,
    ) -> dict:
        """
        将分辨率注入到工作流的 EmptyLatentImage 节点

        Args:
            workflow: 工作流字典
            width: 宽度
            height: 高度

        Returns:
            dict: 注入后的工作流
        """
        import copy
        workflow = copy.deepcopy(workflow)

        injected = False
        for node_id, node_data in workflow.items():
            class_type = node_data.get("class_type", "")
            if class_type in ("EmptyLatentImage", "EmptyImage"):
                workflow[node_id]["inputs"]["width"] = width
                workflow[node_id]["inputs"]["height"] = height
                injected = True
                logger.debug(
                    "分辨率注入 | node=%s | %dx%d",
                    node_id, width, height,
                )

        if not injected:
            logger.warning("工作流中未找到 EmptyLatentImage 节点，无法注入分辨率")

        return workflow

    def randomize_seed(self, workflow: dict) -> dict:
        """
        随机化 KSampler 节点的 seed（每次生图使用不同种子）

        Args:
            workflow: 工作流字典

        Returns:
            dict: 随机化 seed 后的工作流
        """
        import copy
        import random
        workflow = copy.deepcopy(workflow)

        for node_id, node_data in workflow.items():
            class_type = node_data.get("class_type", "")
            if class_type == "KSampler":
                if "seed" in node_data.get("inputs", {}):
                    workflow[node_id]["inputs"]["seed"] = random.randint(0, 2**31 - 1)
                    logger.debug("Seed 随机化 | node=%s | seed=%d", node_id, workflow[node_id]["inputs"]["seed"])

        return workflow

    # ==================== 解析分辨率 ====================

    @staticmethod
    def parse_resolution(resolution: str) -> Tuple[int, int]:
        """
        解析分辨率字符串，并限制最大分辨率（CPU 模式优化）

        Args:
            resolution: 如 "1024x1024" 或 "1600x1600"

        Returns:
            Tuple[int, int]: (width, height)，最大不超过 512
        """
        MAX_DIM = 512
        try:
            parts = resolution.lower().replace("x", " ").split()
            width = int(parts[0])
            height = int(parts[1]) if len(parts) > 1 else width
            # 限制最大分辨率（CPU 模式性能优化）
            width = min(width, MAX_DIM)
            height = min(height, MAX_DIM)
            return width, height
        except (ValueError, IndexError):
            logger.warning("无法解析分辨率 '%s'，使用默认值 512x512", resolution)
            return MAX_DIM, MAX_DIM

    # ==================== 单图生成 ====================

    async def generate_single_image(
        self,
        workflow: dict,
        positive_prompt: str,
        negative_prompt: str,
        resolution: Tuple[int, int],
        timeout: int = 300,
        reference_image_name: str = "",
        selling_points: str = "",
    ) -> str:
        """
        提交单个生图任务，等待完成并下载图片

        Args:
            workflow: 工作流字典
            positive_prompt: 正向提示词
            negative_prompt: 负向提示词
            resolution: 分辨率 (width, height)
            timeout: 超时时间（秒）

        Returns:
            str: 生成的图片本地保存路径

        Raises:
            GenerationError: 生图失败
        """
        width, height = resolution

        # 1. 注入 prompt
        workflow = self.inject_prompt(workflow, positive_prompt, negative_prompt)

        # 2. 注入分辨率
        workflow = self.inject_resolution(workflow, width, height)

        # 3. 随机化 seed
        workflow = self.randomize_seed(workflow)

        # 4. 注入参考图（img2img）
        if reference_image_name:
            workflow = self.inject_loadimage(workflow, reference_image_name)

        # 5. 提交任务
        try:
            prompt_id = await self.comfyui.queue_prompt(workflow)
        except ComfyUIError as e:
            raise GenerationError(f"提交生图任务失败: {str(e)}") from e

        # 6. 等待完成
        try:
            history = await self.comfyui.wait_for_completion(
                prompt_id=prompt_id,
                timeout=timeout,
            )
        except ComfyUIError as e:
            raise GenerationError(f"等待生图完成失败: {str(e)}") from e

        # 7. 提取输出图片信息
        outputs = history.get("outputs", {})
        if not outputs:
            raise GenerationError(f"任务完成但无输出: prompt_id={prompt_id}")

        # 获取第一个输出节点的图片
        images = []
        for node_id, node_output in outputs.items():
            if "images" in node_output:
                for img_info in node_output["images"]:
                    images.append(img_info)

        if not images:
            raise GenerationError(f"未找到生成的图片: prompt_id={prompt_id}")

        # 8. 下载第一张图片
        img_info = images[0]
        filename = img_info["filename"]
        subfolder = img_info.get("subfolder", "")
        folder_type = img_info.get("type", "output")

        try:
            image_bytes = await self.comfyui.get_image(
                filename=filename,
                subfolder=subfolder,
                folder_type=folder_type,
            )
        except ComfyUIError as e:
            raise GenerationError(f"下载图片失败: {str(e)}") from e

        # 8. 保存到本地
        output_filename = self._save_image(image_bytes, filename)
        logger.info("单图生成完成 | output=%s", output_filename)

        return output_filename

    # ==================== 套装生图 ====================

    async def generate_image_set(
        self,
        prompts: dict,
        workflow_dir: Optional[str] = None,
        concurrent: bool = False,  # MX450 2GB显存下串行避免OOM
        timeout_per_image: int = 300,  # MX450 2GB 实测~2分钟/张，需宽松超时
        reference_image_name: str = "",
        selling_points: str = "",
    ) -> List[str]:
        white_bg_path = ""  # 用于场景合成
        """
        根据 rule_parser 生成的 prompts 批量生成图片套装

        接收格式：
        {
            "white_bg_main": {
                "prompt_en": "...",
                "negative_prompt": "...",
                "aspect_ratio": "1:1",
                "resolution": "800x800",
                "style_notes": "..."
            },
            "scene_lifestyle": { ... },
            "detail_closeup": { ... },
            "scale_comparison": { ... }
        }

        Args:
            prompts: rule_parser 生成的 prompts 字典
            workflow_dir: 工作流目录（可选，默认使用配置中的目录）
            concurrent: 是否并发生成，默认 True
            timeout_per_image: 每张图片的超时时间（秒）

        Returns:
            List[str]: 生成的图片本地路径列表
        """
        if not prompts:
            raise GenerationError("prompts 字典为空")

        # 检查 ComfyUI 连接
        connected = await self.comfyui.check_connection()
        if not connected:
            raise GenerationError(
                f"ComfyUI 服务不可用: {self.comfyui.server_address}"
            )

        image_types = list(prompts.keys())
        logger.info(
            "开始批量生图 | types=%s | concurrent=%s",
            image_types,
            concurrent,
        )

        if concurrent:
            # 并发生成：ComfyUI 串行处理 GPU 任务，
            # 每张图都必须等前面所有图完成才开始，因此总超时 = 单图超时 × 图片数量
            effective_timeout = timeout_per_image * len(image_types) * 2  # 最多2个并发
            logger.info(
                "并发模式 | 图片数=%d | 单图超时=%ds | 有效超时=%ds",
                len(image_types),
                timeout_per_image,
                effective_timeout,
            )
            tasks = []
            for image_type in image_types:
                prompt_data = prompts[image_type]
                workflow_name = IMAGE_TYPE_WORKFLOW_MAP.get(image_type, IMAGE_TYPE_WORKFLOW_MAP["_default"])
                ref_img = "" if "txt2img" in workflow_name else reference_image_name
                task_id = self._create_task(image_type)
                coro = self._generate_one_with_tracking(
                    task_id=task_id,
                    image_type=image_type,
                    prompt_data=prompt_data,
                    timeout=effective_timeout,
                    reference_image_name=ref_img,
                    selling_points=selling_points,
                    white_bg_path=white_bg_path,
                )
                tasks.append(coro)

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 收集结果
            output_paths = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(
                        "生图失败 | type=%s | error=%s",
                        image_types[i],
                        str(result),
                    )
                else:
                    output_paths.append(result)

        else:
            # 顺序生成
            output_paths = []
            white_bg_path = ""  # 用于场景合成
            for image_type in image_types:
                prompt_data = prompts[image_type]
                workflow_name = IMAGE_TYPE_WORKFLOW_MAP.get(image_type, IMAGE_TYPE_WORKFLOW_MAP["_default"])
                ref_img = "" if "txt2img" in workflow_name else reference_image_name
                task_id = self._create_task(image_type)
                try:
                    path = await self._generate_one_with_tracking(
                        task_id=task_id,
                        image_type=image_type,
                        prompt_data=prompt_data,
                        timeout=timeout_per_image,
                        reference_image_name=ref_img,
                        selling_points=selling_points,
                        white_bg_path=white_bg_path,
                    )
                    if image_type == "white_bg_main":
                        white_bg_path = path
                    output_paths.append(path)
                except Exception as e:
                    logger.error(
                        "生图失败 | type=%s | error=%s",
                        image_type,
                        str(e),
                    )

        logger.info(
            "批量生图完成 | 成功=%d/%d",
            len(output_paths),
            len(image_types),
        )
        return output_paths

    async def _generate_one_with_tracking(
        self,
        task_id: str,
        image_type: str,
        prompt_data: dict,
        timeout: int = 300,
        reference_image_name: str = "",
        selling_points: str = "",
        white_bg_path: str = "",
    ) -> str:
        """
        带状态跟踪的单图生成

        Args:
            task_id: 任务ID
            image_type: 图片类型
            prompt_data: prompt 数据
            timeout: 超时时间

        Returns:
            str: 生成的图片路径
        """
        self._update_task(task_id, status=TaskStatus.GENERATING)

        try:
            # 确定工作流文件
            workflow_name = IMAGE_TYPE_WORKFLOW_MAP.get(
                image_type,
                IMAGE_TYPE_WORKFLOW_MAP["_default"],
            )

            # 加载工作流
            try:
                workflow = self.load_workflow(workflow_name)
            except WorkflowLoadError:
                # 回退到默认工作流
                logger.warning(
                    "工作流 '%s' 不存在，使用默认工作流",
                    workflow_name,
                )
                workflow_name = IMAGE_TYPE_WORKFLOW_MAP["_default"]
                workflow = self.load_workflow(workflow_name)

            # 解析参数（兼容 prompt_data 为纯字符串的情况）
            if isinstance(prompt_data, str):
                positive = prompt_data
                negative = ""
                resolution_str = "1024x1024"
            else:
                positive = prompt_data.get("prompt_en", "")
                negative = prompt_data.get("negative_prompt", "")
                resolution_str = prompt_data.get("resolution", "1024x1024")
            resolution = self.parse_resolution(resolution_str)

            # 生成
            output_path = await self.generate_single_image(
                workflow=workflow,
                positive_prompt=positive,
                negative_prompt=negative,
                resolution=resolution,
                timeout=timeout,
                reference_image_name=reference_image_name,
            )

            # 后处理：根据图片类型优化输出
            output_path = self._post_process(output_path, image_type, selling_points, white_bg_path)

            self._update_task(
                task_id,
                status=TaskStatus.COMPLETED,
                output_paths=[output_path],
            )
            return output_path

        except Exception as e:
            self._update_task(
                task_id,
                status=TaskStatus.FAILED,
                error=str(e),
            )
            raise

    # ==================== 后处理 ====================

    @staticmethod
    def _post_process(image_path: str, image_type: str, selling_points: str = "", white_bg_path: str = "") -> str:
        """
        对生成图片进行后处理
        
        - white_bg_main: 确保纯白背景（消除PNG透明度）
        - detail_closeup: 中心裁剪（突出细节），保留原始背景
        - scale_comparison: 添加专业尺寸标注线（长宽高cm）
        - scene_lifestyle: 保留原始场景背景，不做白底处理
        """
        from app.utils.image_utils import (
            ensure_white_background,
            crop_center,
            add_size_label,
        )
        
        try:
            if image_type == "white_bg_main":
                image_path = ensure_white_background(image_path)
                logger.info("后处理[white_bg]: 白底填充完成")
                # 叠加商品卖点文案
                if selling_points:
                    from app.utils.image_utils import overlay_selling_points
                    image_path = overlay_selling_points(image_path, selling_points)
                    logger.info("后处理[white_bg]: 商品文案叠加完成")
            elif image_type == "detail_closeup":
                image_path = crop_center(image_path, crop_ratio=0.4)
                logger.info("后处理[detail]: 中心裁剪完成（40%区域）")
            elif image_type == "scale_comparison":
                image_path = add_size_label(image_path)
                logger.info("后处理[comparison]: 专业尺寸标注完成")
            elif image_type == "scene_lifestyle":
                logger.info("后处理[scene]: 执行产品+场景合成")
                if white_bg_path:
                    from app.utils.image_utils import composite_product_to_scene
                    image_path = composite_product_to_scene(white_bg_path, image_path)
                else:
                    logger.warning("后处理[scene]: 无白底图路径，跳过合成")
            else:
                logger.info("后处理[%s]: 无特殊处理", image_type)
        except Exception as e:
            logger.warning("后处理失败（使用原图）: %s", str(e))
        return image_path
    def _save_image(self, image_bytes: bytes, original_filename: str = "") -> str:
        """
        保存图片到 output/ 目录

        Args:
            image_bytes: 图片二进制数据
            original_filename: 原始文件名（用于提取扩展名）

        Returns:
            str: 保存的文件路径
        """
        # 生成带时间戳的文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:18]
        ext = Path(original_filename).suffix if original_filename else ".png"
        filename = f"generated_{timestamp}{ext}"
        filepath = self.output_dir / filename

        with open(filepath, "wb") as f:
            f.write(image_bytes)

        logger.info("图片已保存 | path=%s | size=%d", filepath, len(image_bytes))
        return str(filepath)

    # ==================== 参考图上传 ====================

    async def upload_reference_image(self, image_path: str) -> str:
        """
        将商品原图上传到 ComfyUI input 目录

        Args:
            image_path: 本地图片路径

        Returns:
            str: ComfyUI 中的文件名（如 "ref_abc123.png"）

        Raises:
            GenerationError: 上传失败
        """
        src = Path(image_path)
        if not src.exists():
            raise GenerationError(f"商品原图不存在: {image_path}")

        try:
            image_bytes = src.read_bytes()
            comfyui_filename = f"ref_{uuid.uuid4().hex[:8]}{src.suffix}"
            result = await self.comfyui.upload_image(image_bytes, comfyui_filename)
            logger.info(
                "商品原图已上传到 ComfyUI | filename=%s", result.get("name", comfyui_filename)
            )
            return result.get("name", comfyui_filename)
        except ComfyUIError as e:
            raise GenerationError(f"上传商品原图到 ComfyUI 失败: {str(e)}") from e

    def inject_loadimage(self, workflow: dict, image_name: str) -> dict:
        """
        将参考图文件名注入工作流的 LoadImage 节点

        Args:
            workflow: 工作流字典
            image_name: ComfyUI input 目录中的图片文件名

        Returns:
            dict: 注入后的工作流（深拷贝）
        """
        import copy
        workflow = copy.deepcopy(workflow)

        injected = False
        for node_id, node_data in workflow.items():
            class_type = node_data.get("class_type", "")
            if class_type == "LoadImage":
                workflow[node_id]["inputs"]["image"] = image_name
                injected = True
                logger.debug("LoadImage 节点注入 | node=%s | image=%s", node_id, image_name)

        if not injected:
            logger.info("工作流中无 LoadImage 节点，跳过参考图注入（纯 txt2img 模式）")

        return workflow

    # ==================== 资源管理 ====================

    async def close(self) -> None:
        """关闭资源"""
        await self.comfyui.close()
        logger.info("ImageGeneratorAgent 已关闭")
