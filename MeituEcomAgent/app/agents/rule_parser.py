"""
规则解析Agent - 负责解析输入的规则文本，提取结构化信息

核心功能:
- 接收平台名称和商品描述
- 调用RAG知识库获取平台规则
- 使用大模型将规则+商品描述解析为结构化的生图指令
"""
import json
import logging
import asyncio
from typing import Optional

from openai import AsyncOpenAI
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from app.config import settings
from app.services.rag_service import RAGService

# 配置日志
logger = logging.getLogger(__name__)

# 平台名称映射
PLATFORM_DISPLAY_MAP = {
    "amazon": "Amazon（亚马逊）",
    "aliexpress": "AliExpress（速卖通）",
    "taobao": "淘宝/天猫",
    "shopee": "Shopee（虾皮）",
}


class RuleParserError(Exception):
    """规则解析异常基类"""

    pass


class PlatformNotSupportedError(RuleParserError):
    """平台不支持异常"""

    pass


class RuleFetchError(RuleParserError):
    """规则获取失败异常"""

    pass


class LLMCallError(RuleParserError):
    """大模型调用失败异常"""

    pass


class JsonParseError(RuleParserError):
    """JSON解析失败异常"""

    pass


class RuleParserAgent:
    """规则解析Agent，将平台规则和商品描述解析为结构化的生图指令"""

    # 支持的图片类型
    IMAGE_TYPES = [
        "white_bg_main",       # 白底主图
        "scene_lifestyle",     # 场景生活图
        "detail_closeup",      # 细节特写图
        "scale_comparison",    # 尺寸对比图
    ]

    def __init__(self):
        """初始化规则解析Agent"""
        self.rag_service = RAGService()
        self.client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )
        self.chat_model = settings.CHAT_MODEL
        logger.info(
            "RuleParserAgent initialized | model=%s | base_url=%s",
            self.chat_model,
            settings.OPENAI_BASE_URL,
        )

    # ==================== 核心方法 ====================

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((LLMCallError,)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """
        调用大模型（带重试机制）

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词

        Returns:
            str: 模型返回的文本内容

        Raises:
            LLMCallError: 大模型调用失败
        """
        try:
            logger.info("调用 LLM | model=%s", self.chat_model)
            logger.debug("System prompt (前200字): %s...", system_prompt[:200])
            logger.debug("User prompt (前200字): %s...", user_prompt[:200])

            response = await self.client.chat.completions.create(
                model=self.chat_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,  # 较低温度以确保输出稳定
                max_tokens=4096,
                response_format={"type": "json_object"},  # 强制JSON输出
            )

            content = response.choices[0].message.content
            if not content:
                raise LLMCallError("LLM 返回空内容")

            logger.info(
                "LLM 调用成功 | tokens_used=%s",
                response.usage.total_tokens if response.usage else "unknown",
            )
            return content

        except LLMCallError:
            raise
        except Exception as e:
            logger.warning("LLM 调用失败，准备重试: %s", str(e))
            raise LLMCallError(f"LLM 调用异常: {str(e)}") from e

    async def parse(
        self,
        platform: str,
        product_desc: str,
        reference_image_url: Optional[str] = None,
        selling_points: Optional[str] = None,
    ) -> dict:
        """
        核心方法：解析平台规则和商品描述，生成结构化的生图指令

        Args:
            platform: 平台名称 (amazon/aliexpress/taobao/shopee)
            product_desc: 商品描述
            reference_image_url: 参考图片URL（可选）

        Returns:
            dict: 结构化的生图指令，格式如下：
            {
                "platform": "Amazon（亚马逊）",
                "product_name": "红色陶瓷咖啡杯",
                "image_set": {
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
                },
                "compliance_checklist": ["背景纯白", "无文字水印", ...]
            }

        Raises:
            PlatformNotSupportedError: 平台不支持
            RuleFetchError: 规则获取失败
            LLMCallError: 大模型调用失败
            JsonParseError: JSON解析失败
        """
        # 1. 验证平台
        platform_lower = platform.lower().strip()
        platform_display = PLATFORM_DISPLAY_MAP.get(platform_lower)
        if not platform_display:
            supported = ", ".join(PLATFORM_DISPLAY_MAP.keys())
            raise PlatformNotSupportedError(
                f"不支持的平台: '{platform}'。支持的平台: {supported}"
            )

        logger.info(
            "开始解析 | platform=%s | product=%s",
            platform_display,
            product_desc[:80],
        )

        # 2. 获取平台完整规则
        try:
            rules_text = await asyncio.to_thread(
                self.rag_service.get_all_rules_for_platform, platform_lower
            )
        except Exception as e:
            raise RuleFetchError(f"获取平台规则失败: {str(e)}") from e

        if not rules_text or rules_text.startswith("不支持的平台") or rules_text.startswith("平台"):
            raise RuleFetchError(f"无法获取 {platform_display} 的规则: {rules_text}")

        logger.info("平台规则获取成功 | 长度=%d 字符", len(rules_text))

        # 3. 构造 system prompt
        system_prompt = self._build_system_prompt()

        # 4. 视觉分析参考图（如有）
        visual_analysis = ""
        if reference_image_url:
            visual_analysis = await self._analyze_reference_image(
                reference_image_url, product_desc
            )

        # 5. 构造 user prompt
        user_prompt = self._build_user_prompt(
            platform_display=platform_display,
            product_desc=product_desc,
            rules_text=rules_text,
            reference_image_url=reference_image_url,
            visual_analysis=visual_analysis,
            selling_points=selling_points,
        )

        # 6. 调用 LLM
        try:
            raw_response = await self._call_llm(system_prompt, user_prompt)
        except LLMCallError:
            raise

        # 6. 解析 JSON
        try:
            result = json.loads(raw_response)
        except json.JSONDecodeError as e:
            # 尝试提取 JSON 内容（有时模型会在 JSON 外面包裹 markdown code block）
            raw_response = self._extract_json_from_text(raw_response)
            try:
                result = json.loads(raw_response)
            except json.JSONDecodeError:
                logger.error("JSON 解析失败，原始响应: %s", raw_response[:500])
                raise JsonParseError(
                    f"无法将 LLM 响应解析为 JSON: {str(e)}"
                ) from e

        # 8. 后处理：补充平台名称
        if "platform" not in result:
            result["platform"] = platform_display

        # 7.5. 规范化 image_set：将字符串值转换为标准 dict 格式
        # （某些 LLM 可能返回简化的 prompt 字符串，而非嵌套对象）
        image_set = result.get("image_set", {})
        if isinstance(image_set, dict):
            for img_type, prompt_data in image_set.items():
                if isinstance(prompt_data, str):
                    # LLM 返回了纯 prompt 字符串 → 包装为标准格式
                    image_set[img_type] = {
                        "prompt_en": prompt_data,
                        "negative_prompt": "",
                        "resolution": "1024x1024",
                        "style_notes": "",
                    }
                    logger.info(
                        "image_set[%s] 为纯字符串，已自动包装为标准 dict 格式",
                        img_type,
                    )
            product_identity = self._build_product_identity(
                product_desc=product_desc,
                visual_analysis=visual_analysis,
                selling_points=selling_points,
            )
            self._stabilize_image_prompts(
                image_set=image_set,
                product_identity=product_identity,
                selling_points=selling_points,
            )

        logger.info(
            "解析完成 | platform=%s | image_types=%s | checklist_items=%d",
            platform_display,
            list(result.get("image_set", {}).keys()),
            len(result.get("compliance_checklist", [])),
        )
        return result

    def _build_product_identity(
        self,
        product_desc: str,
        visual_analysis: str = "",
        selling_points: Optional[str] = None,
    ) -> str:
        """构造跨图片共用的商品身份锚点。"""
        identity_parts = [
            f"source product identity: {product_desc.strip()}",
            "same exact SKU in every image, identical jar shape, identical lid, identical cream color, identical label placement, identical product scale",
        ]
        if visual_analysis:
            identity_parts.append(f"visual identity from uploaded reference image: {visual_analysis.strip()}")
        if selling_points:
            identity_parts.append(f"core selling points to express visually: {selling_points.strip()}")
        identity_parts.append(f"online reference style benchmark: {settings.ONLINE_REFERENCE_STYLE}")
        return "; ".join(part for part in identity_parts if part)

    def _stabilize_image_prompts(
        self,
        image_set: dict,
        product_identity: str,
        selling_points: Optional[str] = None,
    ) -> None:
        """统一增强四张图的商品一致性和卖点表达。"""
        common_negative = (
            "different product, changed container shape, changed lid shape, changed color, "
            "wrong label, random brand, unreadable fake text, extra products, watermark, logo mismatch, "
            "deformed object, low quality, blurry, overexposed, cluttered background"
        )
        for image_type, prompt_data in image_set.items():
            if not isinstance(prompt_data, dict):
                continue
            prompt = prompt_data.get("prompt_en", "")
            selling_point_text = f"visualize selling points: {selling_points}. " if selling_points else ""
            prompt_data["prompt_en"] = (
                f"{prompt}\n\n"
                f"CONSISTENCY LOCK: {product_identity}. "
                "The product must remain the same object across the full image set; only camera angle, crop, and background may change. "
                f"{selling_point_text}"
                f"Image role: {image_type}."
            ).strip()
            negative = prompt_data.get("negative_prompt", "")
            prompt_data["negative_prompt"] = ", ".join(
                part for part in [negative, common_negative] if part
            )

    async def generate_single_prompt(
        self,
        platform: str,
        product_desc: str,
        image_type: str,
    ) -> dict:
        """
        针对单张图片类型生成 prompt

        Args:
            platform: 平台名称
            product_desc: 商品描述
            image_type: 图片类型 (white_bg_main / scene_lifestyle / detail_closeup / scale_comparison)

        Returns:
            dict: 单张图片的 prompt 信息，格式：
            {
                "image_type": "white_bg_main",
                "type_label": "白底主图",
                "prompt_en": "...",
                "negative_prompt": "...",
                "aspect_ratio": "1:1",
                "resolution": "800x800",
                "style_notes": "..."
            }
        """
        # 验证图片类型
        if image_type not in self.IMAGE_TYPES:
            supported = ", ".join(self.IMAGE_TYPES)
            raise ValueError(
                f"不支持的图片类型: '{image_type}'。支持的类型: {supported}"
            )

        platform_lower = platform.lower().strip()
        platform_display = PLATFORM_DISPLAY_MAP.get(platform_lower, platform)

        # 图片类型中文映射
        type_labels = {
            "white_bg_main": "白底主图",
            "scene_lifestyle": "场景生活图",
            "detail_closeup": "细节特写图",
            "scale_comparison": "尺寸对比图",
        }
        type_label = type_labels[image_type]

        logger.info(
            "生成单图 prompt | platform=%s | image_type=%s",
            platform_display,
            type_label,
        )

        # 获取平台规则
        try:
            rules_text = await asyncio.to_thread(
                self.rag_service.get_all_rules_for_platform, platform_lower
            )
        except Exception as e:
            raise RuleFetchError(f"获取平台规则失败: {str(e)}") from e

        # 构造 single-image 专用 system prompt
        system_prompt = self._build_single_image_system_prompt(image_type, type_label)

        # 构造 user prompt
        user_prompt = self._build_single_image_user_prompt(
            platform_display=platform_display,
            product_desc=product_desc,
            rules_text=rules_text,
            image_type=image_type,
            type_label=type_label,
        )

        # 调用 LLM
        try:
            raw_response = await self._call_llm(system_prompt, user_prompt)
        except LLMCallError:
            raise

        # 解析 JSON
        try:
            result = json.loads(raw_response)
        except json.JSONDecodeError:
            raw_response = self._extract_json_from_text(raw_response)
            try:
                result = json.loads(raw_response)
            except json.JSONDecodeError as e:
                logger.error("单图 prompt JSON 解析失败: %s", raw_response[:500])
                raise JsonParseError(
                    f"无法将 LLM 响应解析为 JSON: {str(e)}"
                ) from e

        # 补充元信息
        result["image_type"] = image_type
        if "type_label" not in result:
            result["type_label"] = type_label

        logger.info("单图 prompt 生成完成 | type=%s", type_label)
        return result

    # ==================== 视觉分析 ====================

    async def _analyze_reference_image(self, image_path: str, product_desc: str) -> str:
        """
        使用视觉模型分析商品参考图，提取外观特征描述

        Args:
            image_path: 本地图片路径
            product_desc: 商品文字描述

        Returns:
            str: 基于视觉分析的商品外观描述（中文）
        """
        import base64
        from pathlib import Path

        img_path = Path(image_path)
        if not img_path.exists():
            logger.warning("参考图不存在，跳过视觉分析: %s", image_path)
            return ""

        ext = img_path.suffix.lower()
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
        mime_type = mime_map.get(ext, "image/png")

        try:
            image_bytes = img_path.read_bytes()
            if len(image_bytes) > 5 * 1024 * 1024:
                logger.warning("参考图过大（%.1fMB），跳过视觉分析", len(image_bytes) / 1024 / 1024)
                return ""
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        except Exception as e:
            logger.warning("读取参考图失败: %s", str(e))
            return ""

        vision_model = settings.VISION_MODEL
        logger.info("调用视觉模型分析商品图 | model=%s | path=%s", vision_model, str(img_path)[:80])

        try:
            response = await self.client.chat.completions.create(
                model=vision_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一个专业的电商商品视觉分析专家。请仔细观察商品图片，"
                            "提取商品的外观特征，用于后续AI图像生成。"
                            "描述需包含：商品类型、形状、颜色、材质、关键设计元素、"
                            "品牌标识位置（如有）、包装特征等。"
                            "输出简洁但信息密度高的中文描述，不超过300字。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"请分析这张商品图片的外观特征。商品文字描述供参考：{product_desc}",
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{image_b64}",
                                    "detail": "high",
                                },
                            },
                        ],
                    },
                ],
                temperature=0.3,
                max_tokens=1000,
            )

            analysis = response.choices[0].message.content or ""
            logger.info(
                "视觉分析完成 | tokens=%s | analysis_len=%d",
                response.usage.total_tokens if response.usage else "unknown",
                len(analysis),
            )
            return analysis

        except Exception as e:
            logger.warning("视觉模型调用失败（将仅用文字描述生成prompt）: %s", str(e))
            return ""

    # ==================== Prompt 构造方法 ====================

    def _build_system_prompt(self) -> str:
        """构造系统提示词 - 全量生图场景"""
        return """你是一名 **资深电商视觉设计专家**，拥有10年以上跨境电商平台的图片设计经验。

你的任务是根据用户提供的商品描述和平台图片规则，为每一类图片生成精确的 **英文图像生成提示词（prompt）** 和 **合规检查清单**。

## 你需要输出的图片类型

根据平台规则，为以下4种图片类型分别生成prompt：

1. **white_bg_main（白底主图）**：
   - 纯白/浅色背景上的商品正面展示
   - 商品居中、清晰、占比符合平台要求
   - 严格遵循平台的"无牛皮癣"规则
   
2. **scene_lifestyle（场景生活图）**：
   - 商品本身与白底主图完全一致（形态、颜色、细节均不变）
   - 仅背景替换为真实使用场景（家居、桌面、厨房、客厅等）
   - prompt 中必须强调 "same product, identical object, only background changed"
   - negative_prompt 必须包含 "white background, plain background, studio, isolated"
3. **detail_closeup（细节特写图）**：
   - 商品的关键细节大特写
   - 展示材质纹理、做工工艺
   - 高清晰度微距效果
   
4. **scale_comparison（尺寸对比图）**：
   - 通过参照物展示商品实际大小
   - 清晰直观的尺寸示意

## 生成规则

- 所有 prompt 必须使用 **英文**
- prompt 要具体、详细，包含：商品特征、材质、颜色、光照、构图、风格
- negative_prompt 要列出平台明确禁止的元素（水印、Logo、文字、促销信息等）
- aspect_ratio 和 resolution 要符合对应平台的具体数值要求
- style_notes 用中文描述这张图的风格定位和设计思路
- compliance_checklist 用中文列出生成这张图时需要检查的合规要点

## 输出格式

你必须返回严格有效的 JSON 格式，不能包含任何 markdown 标记或额外说明：

```json
{
  "platform": "平台中文名称",
  "product_name": "商品名称（中文）",
  "image_set": {
    "white_bg_main": {
      "prompt_en": "英文正向提示词",
      "negative_prompt": "英文负向提示词",
      "aspect_ratio": "宽高比",
      "resolution": "分辨率",
      "style_notes": "中文风格说明"
    },
    "scene_lifestyle": {
      "prompt_en": "...",
      "negative_prompt": "...",
      "aspect_ratio": "...",
      "resolution": "...",
      "style_notes": "..."
    },
    "detail_closeup": {
      "prompt_en": "...",
      "negative_prompt": "...",
      "aspect_ratio": "...",
      "resolution": "...",
      "style_notes": "..."
    },
    "scale_comparison": {
      "prompt_en": "...",
      "negative_prompt": "...",
      "aspect_ratio": "...",
      "resolution": "...",
      "style_notes": "..."
    }
  },
  "compliance_checklist": [
    "中文合规检查项1",
    "中文合规检查项2",
    "..."
  ]
}
```"""

    def _build_user_prompt(
        self,
        platform_display: str,
        product_desc: str,
        rules_text: str,
        reference_image_url: Optional[str] = None,
        visual_analysis: str = "",
        selling_points: Optional[str] = None,
    ) -> str:
        """构造用户提示词 - 全量生图场景"""
        prompt_parts = [
            f"## 目标平台\n{platform_display}",
            "",
            f"## 商品描述\n{product_desc}",
        ]

        # 卖点文案（融入 prompt 以增强生成质量）
        if selling_points:
            prompt_parts.extend([
                "",
                f"## 商品卖点（必须在图中体现）\n{selling_points}",
                "请根据卖点文案在生成的图片 prompt 中体现核心卖点特征。",
                "同时检查卖点内容是否符合平台规则（例如是否涉及禁用词或违规宣传）。",
            ])

        prompt_parts.extend([
            "",
            f"## 平台图片规则（必须严格遵守）\n{rules_text}",
        ])

        if visual_analysis:
            prompt_parts.extend([
                "",
                "## 商品外观视觉分析（基于用户上传的商品原图）",
                visual_analysis,
                "请严格基于以上视觉分析的商品外观特征，生成各类型图片的 prompt。",
            ])
        elif reference_image_url:
            prompt_parts.extend([
                "",
                "## 参考图片",
                "用户已提供商品参考图片（已进行AI抠图+白底处理）。",
                "请基于该商品的外观特征生成各类型图片的 prompt。",
            ])

        prompt_parts.extend([
            "",
            "## 任务要求",
            "请根据以上平台规则和商品描述，为该商品生成4种类型的图片prompt和合规检查清单。",
            "严格按照平台规则中的数值要求设置 resolution 和 aspect_ratio。",
            "直接输出JSON，不要包含任何markdown标记或额外说明文字。",
        ])

        return "\n".join(prompt_parts)

    def _build_single_image_system_prompt(
        self, image_type: str, type_label: str
    ) -> str:
        """构造单图模式系统提示词"""
        type_descriptions = {
            "white_bg_main": "纯白/浅色背景上的商品正面展示，商品居中、清晰，严格遵循'无牛皮癣'规则",
            "scene_lifestyle": "商品与白底主图完全一致，仅背景替换为真实生活场景（家居/桌面/厨房等），自然光影，温馨氛围",
            "detail_closeup": "商品关键细节的超大特写，展示材质纹理、做工工艺，高清晰度微距效果",
            "scale_comparison": "通过参照物（如硬币、手掌）展示商品实际大小，清晰直观的尺寸对比",
        }

        return f"""你是一名 **资深电商视觉设计专家**。

请为以下图片类型生成精确的英文图像生成提示词：

**图片类型**：{type_label}（{image_type}）
**类型说明**：{type_descriptions.get(image_type, "")}

## 输出格式

直接返回以下 JSON，不要包含 markdown 标记：

```json
{{
  "image_type": "{image_type}",
  "type_label": "{type_label}",
  "prompt_en": "英文正向提示词",
  "negative_prompt": "英文负向提示词",
  "aspect_ratio": "宽高比",
  "resolution": "分辨率",
  "style_notes": "中文风格说明"
}}
```"""

    def _build_single_image_user_prompt(
        self,
        platform_display: str,
        product_desc: str,
        rules_text: str,
        image_type: str,
        type_label: str,
    ) -> str:
        """构造单图模式用户提示词"""
        return "\n".join([
            f"## 目标平台\n{platform_display}",
            "",
            f"## 商品描述\n{product_desc}",
            "",
            f"## 平台图片规则\n{rules_text}",
            "",
            f"## 任务",
            f"请为「{type_label}」这一种图片类型生成 prompt。",
            "根据平台规则确定 aspect_ratio 和 resolution 的具体数值。",
            "直接输出JSON，不要包含任何额外内容。",
        ])

    # ==================== 工具方法 ====================

    @staticmethod
    def _extract_json_from_text(text: str) -> str:
        """
        从文本中提取 JSON 内容（处理模型在 JSON 外包裹 markdown 的情况）

        Args:
            text: 原始文本

        Returns:
            str: 提取后的 JSON 字符串
        """
        text = text.strip()

        # 尝试去除 markdown code block 包裹
        if text.startswith("```"):
            # 找到第一个换行后的内容
            first_newline = text.find("\n")
            if first_newline != -1:
                text = text[first_newline + 1:]
            # 去除末尾的 ```
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        # 尝试找到第一个 { 和最后一个 }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]

        return text

    async def close(self):
        """关闭资源"""
        if hasattr(self, "client") and self.client:
            await self.client.close()
