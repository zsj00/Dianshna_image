"""
合规审核Agent - 对生成的图片进行平台规则合规性审核

核心功能:
- 图片转 base64 编码
- 从 RAG 知识库获取平台规则
- 调用多模态视觉模型进行合规审核
- Chain of Thought 思维链逐步分析
- 支持单图审核、批量审核、修复建议生成
"""
import json
import base64
import logging
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any

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

# 图片类型中文映射
IMAGE_TYPE_LABELS = {
    "white_bg_main": "白底主图",
    "scene_lifestyle": "场景生活图",
    "detail_closeup": "细节特写图",
    "scale_comparison": "尺寸对比图",
}


class ComplianceCheckerError(Exception):
    """合规审核异常基类"""

    pass


class ImageLoadError(ComplianceCheckerError):
    """图片加载异常"""

    pass


class LLMCallError(ComplianceCheckerError):
    """大模型调用异常"""

    pass


class RuleFetchError(ComplianceCheckerError):
    """规则获取异常"""

    pass


class JsonParseError(ComplianceCheckerError):
    """JSON解析异常"""

    pass


class ComplianceCheckerAgent:
    """合规审核Agent，检查生成的图片是否符合平台规则"""

    # 严重程度定义
    SEVERITY_LEVELS = ["critical", "major", "minor", "info"]

    def __init__(self):
        """初始化合规审核Agent"""
        self.rag_service = RAGService()
        self.client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )
        self.chat_model = settings.CHAT_MODEL
        self.vision_model = settings.VISION_MODEL
        logger.info(
            "ComplianceCheckerAgent initialized | vision=%s | chat=%s",
            self.vision_model,
            self.chat_model,
        )

    # ==================== Base64 编码 ====================

    @staticmethod
    def encode_image_to_base64(image_path: str) -> str:
        """
        将图片文件转换为 base64 编码字符串

        Args:
            image_path: 图片文件路径

        Returns:
            str: base64 编码字符串（不含 data URI 前缀）

        Raises:
            ImageLoadError: 图片加载失败
        """
        path = Path(image_path)
        if not path.exists():
            raise ImageLoadError(f"图片文件不存在: {image_path}")

        if not path.is_file():
            raise ImageLoadError(f"路径不是文件: {image_path}")

        # 支持的图片格式
        ext = path.suffix.lower()
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }
        mime_type = mime_map.get(ext, "image/png")

        try:
            with open(path, "rb") as f:
                image_data = f.read()

            if len(image_data) == 0:
                raise ImageLoadError(f"图片文件为空: {image_path}")

            base64_str = base64.b64encode(image_data).decode("utf-8")

            logger.debug(
                "图片编码完成 | path=%s | size=%d | base64_len=%d",
                image_path,
                len(image_data),
                len(base64_str),
            )

            # 返回完整的 data URI
            return f"data:{mime_type};base64,{base64_str}"

        except ImageLoadError:
            raise
        except Exception as e:
            raise ImageLoadError(f"读取图片文件异常: {str(e)}") from e

    # ==================== LLM 调用 ====================

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((LLMCallError,)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _call_vision_llm(
        self,
        system_prompt: str,
        user_content: List[dict],
    ) -> str:
        """
        调用多模态视觉模型（带重试机制）

        Args:
            system_prompt: 系统提示词
            user_content: 用户消息内容（包含文本和图片）

        Returns:
            str: 模型返回的文本

        Raises:
            LLMCallError: 调用失败
        """
        try:
            logger.info("调用 Vision LLM | model=%s", self.vision_model)

            response = await self.client.chat.completions.create(
                model=self.vision_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.2,  # 低温度确保审核一致性
                max_tokens=4096,
                # 注意: 不设置 response_format={"type":"json_object"}
                # 阿里云百炼的部分视觉模型（如 qwen-vl-max）不支持此参数，
                # 改为依赖 prompt 指令 + _parse_json_response 容错解析
            )

            content = response.choices[0].message.content
            if not content:
                raise LLMCallError("模型返回空内容")

            logger.info(
                "Vision LLM 调用成功 | tokens=%s",
                response.usage.total_tokens if response.usage else "unknown",
            )
            return content

        except LLMCallError:
            raise
        except Exception as e:
            logger.warning("Vision LLM 调用失败，准备重试: %s", str(e))
            raise LLMCallError(f"Vision LLM 调用异常: {str(e)}") from e

    # ==================== 单图审核 ====================

    async def check_image(
        self,
        image_path: str,
        platform: str,
        image_type: str = "white_bg_main",
    ) -> dict:
        """
        审核单张图片的合规性

        使用 Chain of Thought 思维链，让模型逐步分析：
        1. 描述图片内容
        2. 逐条对照平台规则
        3. 给出合规/不合规判定
        4. 给出修改建议

        Args:
            image_path: 图片文件路径
            platform: 平台名称 (amazon/aliexpress/taobao/shopee)
            image_type: 图片类型 (white_bg_main/scene_lifestyle/detail_closeup/scale_comparison)

        Returns:
            dict: 结构化的审核结果
            {
                "is_compliant": true/false,
                "confidence": 0.95,
                "violations": [
                    {
                        "rule": "背景必须纯白",
                        "severity": "critical",
                        "description": "背景存在灰色渐变",
                        "suggestion": "将背景替换为纯白 RGB(255,255,255)"
                    }
                ],
                "overall_score": 85,
                "summary": "整体合规，但背景需要调整",
                "cot_analysis": {
                    "step1_content_description": "...",
                    "step2_rule_comparison": [...],
                    "step3_compliance_decision": "...",
                    "step4_fix_suggestions": [...]
                }
            }

        Raises:
            PlatformNotSupportedError: 平台不支持
            ImageLoadError: 图片加载失败
            RuleFetchError: 规则获取失败
            LLMCallError: 大模型调用失败
        """
        # 1. 验证平台
        platform_lower = platform.lower().strip()
        platform_display = PLATFORM_DISPLAY_MAP.get(platform_lower)
        if not platform_display:
            supported = ", ".join(PLATFORM_DISPLAY_MAP.keys())
            raise ComplianceCheckerError(
                f"不支持的平台: '{platform}'。支持的平台: {supported}"
            )

        type_label = IMAGE_TYPE_LABELS.get(image_type, image_type)

        logger.info(
            "开始单图审核 | platform=%s | type=%s | image=%s",
            platform_display,
            type_label,
            Path(image_path).name,
        )

        # 2. 图片转 base64
        try:
            image_base64 = self.encode_image_to_base64(image_path)
        except ImageLoadError:
            raise

        # 3. 获取平台规则（仅获取与当前图片类型相关的规则）
        try:
            rules_text = await asyncio.to_thread(
                self.rag_service.get_all_rules_for_platform, platform_lower
            )
        except Exception as e:
            raise RuleFetchError(f"获取平台规则失败: {str(e)}") from e

        if not rules_text or rules_text.startswith("不支持的平台") or rules_text.startswith("平台"):
            raise RuleFetchError(f"无法获取 {platform_display} 的规则")

        logger.info("平台规则获取成功 | 长度=%d 字符", len(rules_text))

        # 4. 构造 system prompt（Chain of Thought）
        system_prompt = self._build_check_system_prompt()

        # 5. 构造 user 消息（文本 + 图片）
        user_content = self._build_check_user_content(
            platform_display=platform_display,
            image_type=image_type,
            type_label=type_label,
            rules_text=rules_text,
            image_base64=image_base64,
        )

        # 6. 调用 Vision LLM
        try:
            raw_response = await self._call_vision_llm(system_prompt, user_content)
        except LLMCallError:
            raise

        # 7. 解析 JSON
        result = self._parse_json_response(raw_response, "审核结果")

        # 8. 补充元信息
        result["platform"] = platform_display
        result["image_type"] = image_type
        result["image_path"] = image_path

        logger.info(
            "审核完成 | compliant=%s | score=%s | violations=%d",
            result.get("is_compliant"),
            result.get("overall_score"),
            len(result.get("violations", [])),
        )
        return result

    # ==================== 批量审核 ====================

    async def check_image_set(
        self,
        image_paths: List[str],
        platform: str,
        image_type_map: Optional[Dict[str, str]] = None,
    ) -> dict:
        """
        批量审核一套图片（通常4张）

        对每张图分别审核，然后综合评分。

        Args:
            image_paths: 图片路径列表
            platform: 平台名称
            image_type_map: 图片路径到类型的映射
                {"path/to/white_bg.png": "white_bg_main", ...}

        Returns:
            dict: 批量审核结果
            {
                "platform": "Amazon（亚马逊）",
                "total_images": 4,
                "compliant_count": 3,
                "non_compliant_count": 1,
                "overall_score": 87.5,
                "overall_compliant": false,
                "per_image_results": [
                    { ... check_image 的单图结果 ... }
                ],
                "summary": "4张图中3张合规，1张存在背景问题需要调整"
            }
        """
        if not image_paths:
            raise ComplianceCheckerError("图片路径列表为空")

        platform_lower = platform.lower().strip()
        platform_display = PLATFORM_DISPLAY_MAP.get(platform_lower, platform)

        logger.info(
            "开始批量审核 | platform=%s | images=%d",
            platform_display,
            len(image_paths),
        )

        # 逐张审核（可并发）
        tasks = []
        for img_path in image_paths:
            # 确定图片类型
            img_type = "white_bg_main"
            if image_type_map and img_path in image_type_map:
                img_type = image_type_map[img_path]

            tasks.append(self.check_image(img_path, platform, img_type))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 汇总结果
        per_image_results = []
        compliant_count = 0
        non_compliant_count = 0
        total_score = 0
        valid_count = 0

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                per_image_results.append({
                    "image_path": image_paths[i],
                    "error": str(result),
                    "is_compliant": None,
                    "overall_score": 0,
                })
                non_compliant_count += 1
            else:
                per_image_results.append(result)
                total_score += result.get("overall_score", 0)
                valid_count += 1
                if result.get("is_compliant"):
                    compliant_count += 1
                else:
                    non_compliant_count += 1

        overall_score = (total_score / valid_count) if valid_count > 0 else 0
        overall_compliant = non_compliant_count == 0

        # 生成汇总摘要
        summary = self._generate_set_summary(
            per_image_results,
            compliant_count,
            non_compliant_count,
            overall_score,
        )

        batch_result = {
            "platform": platform_display,
            "total_images": len(image_paths),
            "compliant_count": compliant_count,
            "non_compliant_count": non_compliant_count,
            "overall_score": round(overall_score, 1),
            "overall_compliant": overall_compliant,
            "per_image_results": per_image_results,
            "summary": summary,
        }

        logger.info(
            "批量审核完成 | compliant=%d/%d | score=%.1f",
            compliant_count,
            len(image_paths),
            overall_score,
        )
        return batch_result

    # ==================== 修复建议生成 ====================

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((LLMCallError,)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def _call_chat_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> str:
        """
        调用文本 LLM（带重试机制），用于修复 prompt 生成等纯文本任务

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            temperature: 温度
            max_tokens: 最大 token 数

        Returns:
            str: 模型返回的文本

        Raises:
            LLMCallError: 调用失败
        """
        try:
            response = await self.client.chat.completions.create(
                model=self.chat_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )

            content = response.choices[0].message.content
            if not content:
                raise LLMCallError("Chat LLM 返回空内容")

            logger.info(
                "Chat LLM 调用成功 | tokens=%s",
                response.usage.total_tokens if response.usage else "unknown",
            )
            return content

        except LLMCallError:
            raise
        except Exception as e:
            logger.warning("Chat LLM 调用失败，准备重试: %s", str(e))
            raise LLMCallError(f"Chat LLM 调用异常: {str(e)}") from e

    async def generate_fix_suggestions(
        self,
        violations: List[dict],
        original_prompt: str,
    ) -> str:
        """
        根据违规项生成修改后的生图 prompt（用于自动重绘闭环）

        Args:
            violations: 违规项列表，每项包含 rule, description, suggestion 字段
            original_prompt: 原始生图 prompt

        Returns:
            str: 修改后的英文生图 prompt
        """
        if not violations:
            return original_prompt

        logger.info(
            "生成修复 prompt | violations=%d",
            len(violations),
        )

        violations_text = json.dumps(violations, ensure_ascii=False, indent=2)

        system_prompt = """你是一名 **资深电商视觉设计专家** 和 **Stable Diffusion Prompt 工程师**。

你的任务是：根据图片合规审核中发现的违规项，修改原始的生图 prompt，使其修正所有违规问题。

## 修改规则
- 保留原始 prompt 中好的部分
- 针对每一条违规项，在 prompt 中添加或修改相应的描述
- 确保修改后的 prompt 在视觉上更符合平台合规要求

## 输出格式
直接返回修改后的英文 prompt 文本（不是 JSON），一行或一个段落即可。"""

        user_prompt = f"""## 原始 Prompt
{original_prompt}

## 审核发现的违规项
{violations_text}

## 任务
请根据上述违规项，修改原始 prompt，生成一个新的、合规的英文生图 prompt。
直接输出修改后的 prompt 文本，不要包含任何额外说明。"""

        try:
            fixed_prompt = await self._call_chat_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            )

            if fixed_prompt:
                fixed_prompt = fixed_prompt.strip().strip('"').strip("'")
                logger.info(
                    "修复 prompt 生成完成 | length=%d",
                    len(fixed_prompt),
                )
                return fixed_prompt
            else:
                logger.warning("修复 prompt 生成返回空内容，返回原始 prompt")
                return original_prompt

        except Exception as e:
            logger.error("修复 prompt 生成失败: %s", str(e))
            return original_prompt

    # ==================== Prompt 构造 ====================

    def _build_check_system_prompt(self) -> str:
        """构造系统提示词 — Chain of Thought 审核"""
        return """你是一名 **跨境电商平台图片合规审核专家**，拥有5年以上Amazon、速卖通、淘宝、Shopee等平台的图片审核经验。

## 审核流程（Chain of Thought）

你必须按照以下4个步骤逐步分析，并将分析过程记录在 `cot_analysis` 字段中：

### 第一步：描述图片内容  
仔细观察并描述图片中：
- 商品是什么、外观特征
- 背景颜色和状态
- 图片中是否包含文字、Logo、水印、促销信息
- 商品的占比和位置
- 图片的整体质量

### 第二步：逐条对照平台规则
逐条阅读提供的平台规则，检查每一项规则是否被满足：
- 背景要求
- 禁止元素检查
- 商品展示要求
- 尺寸/分辨率要求
- 其他特殊规定

### 第三步：合规/不合规判定
基于第二步的逐条对照，给出最终判定：
- 如果所有规则都满足 → is_compliant = true
- 如果存在任何违规 → is_compliant = false
- 给出置信度（0.0-1.0）
- 给出综合评分（0-100）

### 第四步：修改建议
对于每一条违规项，给出具体的修改建议：
- 需要修改什么
- 如何修改
- 严重程度（critical / major / minor / info）

## 严重程度定义
- **critical**：会导致商品被下架或封禁的严重违规（如主图非白底、含Logo水印）
- **major**：影响搜索排名和曝光的重要违规（如商品占比不足、分辨率低）
- **minor**：轻微的视觉优化建议（如构图可优化、光线可调整）
- **info**：信息提示（如建议添加某类图片）

## 输出格式

必须返回严格有效的 JSON（不要包含 markdown 标记）：

```json
{
  "is_compliant": true,
  "confidence": 0.95,
  "violations": [
    {
      "rule": "违规的规则名称",
      "severity": "critical",
      "description": "具体的违规描述",
      "suggestion": "修改建议"
    }
  ],
  "overall_score": 85,
  "summary": "整体审核总结（中文，1-3句话）",
  "cot_analysis": {
    "step1_content_description": "第一步：详细的图片内容描述",
    "step2_rule_comparison": [
      "规则1：背景要求 — 通过/不通过 — 原因",
      "规则2：禁止元素 — 通过/不通过 — 原因"
    ],
    "step3_compliance_decision": "第三步：综合判定说明",
    "step4_fix_suggestions": [
      "修改建议1",
      "修改建议2"
    ]
  }
}
```"""

    def _build_check_user_content(
        self,
        platform_display: str,
        image_type: str,
        type_label: str,
        rules_text: str,
        image_base64: str,
    ) -> List[dict]:
        """构造用户消息内容（文本 + 图片）"""
        text_content = "\n".join([
            f"## 审核任务",
            f"- 平台：{platform_display}",
            f"- 图片类型：{type_label}（{image_type}）",
            "",
            f"## 平台图片规则（必须严格对照）",
            rules_text,
            "",
            "## 审核要求",
            f"请审核下图中这张{type_label}的合规性。",
            "按照4步思维链逐步分析，给出结构化的审核结果。",
        ])

        return [
            {"type": "text", "text": text_content},
            {
                "type": "image_url",
                "image_url": {
                    "url": image_base64,
                    "detail": "high",  # 高细节模式，仔细检查图片
                },
            },
        ]

    # ==================== 工具方法 ====================

    @staticmethod
    def _parse_json_response(raw_response: str, context: str = "") -> dict:
        """
        解析 LLM 返回的 JSON，带容错处理

        Args:
            raw_response: 原始响应文本
            context: 上下文描述（用于日志）

        Returns:
            dict: 解析后的字典
        """
        try:
            return json.loads(raw_response)
        except json.JSONDecodeError:
            # 尝试去除 markdown 包裹
            text = raw_response.strip()
            if text.startswith("```"):
                first_newline = text.find("\n")
                if first_newline != -1:
                    text = text[first_newline + 1:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                text = text[start:end + 1]

            try:
                return json.loads(text)
            except json.JSONDecodeError as e:
                logger.error(
                    "%s JSON 解析失败 | raw=%s",
                    context,
                    raw_response[:500],
                )
                raise JsonParseError(
                    f"{context} JSON 解析失败: {str(e)}"
                ) from e

    @staticmethod
    def _generate_set_summary(
        per_image_results: List[dict],
        compliant_count: int,
        non_compliant_count: int,
        overall_score: float,
    ) -> str:
        """生成整套图片的汇总摘要"""
        total = compliant_count + non_compliant_count

        if non_compliant_count == 0:
            return f"全部{total}张图片均通过合规审核，综合评分 {overall_score:.1f} 分，可以直接发布。"

        # 收集所有违规项
        all_violations = []
        for result in per_image_results:
            if result.get("violations"):
                for v in result["violations"]:
                    all_violations.append(v.get("rule", "未知规则"))

        # 统计最常见的违规
        from collections import Counter
        violation_counter = Counter(all_violations)
        top_violations = violation_counter.most_common(3)

        summary_parts = [
            f"{total}张图片中，{compliant_count}张合规、{non_compliant_count}张不合规，综合评分 {overall_score:.1f} 分。"
        ]

        if top_violations:
            issues = "、".join([item[0] for item in top_violations])
            summary_parts.append(f"主要问题集中在：{issues}。")

        return "".join(summary_parts)

    async def close(self):
        """关闭资源"""
        await self.client.close()
        logger.info("ComplianceCheckerAgent 已关闭")
