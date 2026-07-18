"""
Agent系统总调度器

负责串联所有Agent并实现"生成→审核→不合规则重绘"的闭环。

流程:
  1. RuleParserAgent.parse()         → 结构化生图prompt
  2. ImageGeneratorAgent.generate_image_set() → 生成4张图片
  3. ComplianceCheckerAgent.check_image_set() → 审核所有图片
  4. 不合规图片 → 修复prompt → 重绘 → 重审（最多max_retries轮）
  5. 自动归档 + 生成审核报告
"""
import json
import uuid
import shutil
import logging
import asyncio
from enum import Enum
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any

from app.config import settings
from app.utils.file_utils import (
    create_task_dir, copy_to_task_dir, save_report,
    create_output_directory, save_images,
)
from app.agents.rule_parser import RuleParserAgent, RuleParserError
from app.agents.image_generator import (
    ImageGeneratorAgent,
    ImageGeneratorError,
    IMAGE_TYPE_WORKFLOW_MAP,
)
from app.agents.compliance_checker import (
    ComplianceCheckerAgent,
    ComplianceCheckerError,
    IMAGE_TYPE_LABELS,
)

# 配置日志
logger = logging.getLogger(__name__)


class PipelineStatus(str, Enum):
    """管道状态枚举"""

    PENDING = "pending"
    PARSING = "parsing"
    GENERATING = "generating"
    AUDITING = "auditing"
    RETRYING = "retrying"
    ARCHIVING = "archiving"
    COMPLETED = "completed"
    FAILED = "failed"


class PipelineError(Exception):
    """管道异常基类"""

    pass


class AgentOrchestrator:
    """Agent系统总调度器"""

    def __init__(self):
        """初始化调度器"""
        self.rule_parser = RuleParserAgent()
        self.image_generator = ImageGeneratorAgent()
        self.compliance_checker = ComplianceCheckerAgent()

        # 任务存储
        self._tasks: Dict[str, dict] = {}

        # 输出根目录
        base_dir = Path(__file__).resolve().parent.parent.parent
        self.output_base_dir = base_dir / settings.OUTPUT_DIR

        logger.info("AgentOrchestrator initialized")

    # ==================== 主流程 ====================

    async def run_pipeline(
        self,
        platform: str,
        product_desc: str,
        reference_image: Optional[str] = None,
        selling_points: Optional[str] = None,
        max_retries: int = 3,
        task_id: Optional[str] = None,
    ) -> dict:
        """
        执行完整的"生成→审核→修复→重绘"闭环

        Args:
            platform: 平台名称 (amazon/aliexpress/taobao/shopee)
            product_desc: 商品描述
            reference_image: 参考图片路径（可选）
            max_retries: 最大重试次数，默认3
            task_id: 预创建的任务ID（可选，不传则自动生成）

        Returns:
            dict: 完整的管道执行结果
            {
                "task_id": "...",
                "platform": "...",
                "product": "...",
                "status": "completed",
                "images": [
                    {
                        "type": "white_bg_main",
                        "path": "output/xxx/xxx.png",
                        "compliant": true,
                        "retry_count": 0,
                        "audit_result": { ... }
                    },
                    ...
                ],
                "final_report_path": "output/xxx/report.json",
                "total_retries": 0,
                "created_at": "...",
                "pipeline_log": [...]
            }
        """
        if task_id is None:
            task_id = str(uuid.uuid4())[:12]
        pipeline_log: List[str] = []

        # 初始化任务（仅当任务不存在时创建，避免覆盖预创建的任务）
        if task_id in self._tasks:
            task = self._tasks[task_id]
        else:
            task = self._init_task(task_id, platform, product_desc)
        logger.info("=" * 60)
        logger.info("管道启动 | task_id=%s | platform=%s", task_id, platform)
        logger.info("=" * 60)

        try:
            # =================================================================
            # 第一步：规则解析
            # =================================================================
            self._update_task_status(task_id, PipelineStatus.PARSING)
            step_msg = "▶ 第一步：规则解析 — 调用 RuleParserAgent"
            logger.info(step_msg)
            pipeline_log.append(step_msg)

            try:
                parse_result = await self.rule_parser.parse(
                    platform=platform,
                    product_desc=product_desc,
                    reference_image_url=reference_image,
                    selling_points=selling_points,
                )
            except RuleParserError as e:
                self._fail_task(task_id, f"规则解析失败: {str(e)}")
                raise PipelineError(f"规则解析失败: {str(e)}") from e

            product_name = parse_result.get("product_name", product_desc)
            image_set = parse_result.get("image_set", {})

            task["product"] = product_name
            task["parse_result"] = parse_result

            logger.info("✓ 规则解析完成 | product=%s | image_types=%s",
                product_name, list(image_set.keys()))
            pipeline_log.append(
                f"✓ 解析完成，生成 {len(image_set)} 种图片类型的 prompt"
            )

            if not image_set:
                self._fail_task(task_id, "规则解析未生成任何图片 prompt")
                raise PipelineError("规则解析未生成任何图片 prompt (image_set 为空)")

            # =================================================================
            # 第二步：批量生图
            # =================================================================
            self._update_task_status(task_id, PipelineStatus.GENERATING)
            step_msg = "▶ 第二步：批量生图 — 调用 ImageGeneratorAgent"
            logger.info(step_msg)
            pipeline_log.append(step_msg)

            # 上传参考图到 ComfyUI（用于 img2img）
            reference_image_name = ""
            if reference_image:
                try:
                    reference_image_name = await self.image_generator.upload_reference_image(reference_image)
                    logger.info("参考图已上传到 ComfyUI | name=%s", reference_image_name)
                except Exception as e:
                    logger.warning("上传参考图失败（将继续使用纯txt2img）: %s", str(e))

            try:
                generated_paths = await self.image_generator.generate_image_set(
                    prompts=image_set,
                    reference_image_name=reference_image_name,
                    selling_points=selling_points,
                )
            except ImageGeneratorError as e:
                self._fail_task(task_id, f"生图失败: {str(e)}")
                raise PipelineError(f"生图失败: {str(e)}") from e

            if not generated_paths:
                self._fail_task(task_id, "生图未产生任何图片")
                raise PipelineError("生图未产生任何图片")

            logger.info("✓ 生图完成 | 成功=%d 张", len(generated_paths))
            pipeline_log.append(f"✓ 生图完成，生成 {len(generated_paths)} 张图片")

            # 建立图片类型→路径的映射
            image_types = list(image_set.keys())
            type_path_map: Dict[str, str] = {}
            for i, img_type in enumerate(image_types):
                if i < len(generated_paths):
                    type_path_map[img_type] = generated_paths[i]

            # =================================================================
            # 第三步：合规审核
            # =================================================================
            all_paths = list(type_path_map.values())

            audit_results, total_retries = await self._audit_and_retry(
                task_id=task_id,
                platform=platform,
                image_set=image_set,
                type_path_map=type_path_map,
                max_retries=max_retries,
                pipeline_log=pipeline_log,
                reference_image_name=reference_image_name,
            )

            # =================================================================
            # 第四步：归档
            # =================================================================
            self._update_task_status(task_id, PipelineStatus.ARCHIVING)
            step_msg = "▶ 第四步：自动归档"
            logger.info(step_msg)
            pipeline_log.append(step_msg)

            # 使用结构化归档: output/{platform}/{product_name}_{timestamp}/
            structured_dir = create_output_directory(platform, product_name)
            task_dir = create_task_dir(task_id)

            # 复制所有图片到结构化目录和任务目录
            current_paths = [info["path"] for info in audit_results if info["path"]]
            archived_paths = copy_to_task_dir(task_dir, current_paths)
            _ = save_images([{"path": p} for p in archived_paths], structured_dir)

            # 更新路径为归档后的路径
            for info, new_path in zip(audit_results, archived_paths):
                info["path"] = new_path

            logger.info("✓ 归档完成 | task_dir=%s | structured_dir=%s", task_dir, structured_dir)
            pipeline_log.append(f"✓ 已归档到 {structured_dir}")

            # =================================================================
            # 第五步：生成最终报告
            # =================================================================
            step_msg = "▶ 第五步：生成审核报告"
            logger.info(step_msg)
            pipeline_log.append(step_msg)

            final_result = self._build_final_report(
                task_id=task_id,
                platform=platform,
                product_name=product_name,
                audit_results=audit_results,
                total_retries=total_retries,
                pipeline_log=pipeline_log,
            )

            # 保存报告 JSON
            report_path = save_report(task_dir, final_result)
            final_result["final_report_path"] = report_path

            logger.info("✓ 报告已保存 | path=%s", report_path)
            pipeline_log.append(f"✓ 报告已保存")

            # 完成
            self._update_task_status(task_id, PipelineStatus.COMPLETED)
            task["report"] = final_result

            logger.info("=" * 60)
            logger.info("管道完成 | task_id=%s | compliant=%s/%s",
                task_id,
                sum(1 for r in audit_results if r.get("compliant")),
                len(audit_results))
            logger.info("=" * 60)

            return final_result

        except PipelineError:
            raise
        except Exception as e:
            logger.exception("管道执行异常: %s", str(e))
            self._fail_task(task_id, str(e))
            return self._build_error_report(
                task_id=task_id,
                platform=platform,
                product_desc=product_desc,
                error=str(e),
                pipeline_log=pipeline_log,
            )

    # ==================== 审核 + 重试闭环 ====================

    async def _audit_and_retry(
        self,
        task_id: str,
        platform: str,
        image_set: dict,
        type_path_map: Dict[str, str],
        max_retries: int,
        pipeline_log: List[str],
        reference_image_name: str = "",
    ) -> tuple:
        """
        审核图片并在不合规时自动重试

        Returns:
            tuple: (audit_results_list, total_retries_count)
        """
        self._update_task_status(task_id, PipelineStatus.AUDITING)

        step_msg = "▶ 第三步：合规审核 — 调用 ComplianceCheckerAgent"
        logger.info(step_msg)
        pipeline_log.append(step_msg)

        # 图片类型→路径的反向映射
        path_type_map = {v: k for k, v in type_path_map.items()}
        all_paths = list(type_path_map.values())

        # 初始审核
        try:
            batch_result = await self.compliance_checker.check_image_set(
                image_paths=all_paths,
                platform=platform,
                image_type_map=path_type_map,
            )
        except ComplianceCheckerError as e:
            raise PipelineError(f"合规审核失败: {str(e)}") from e

        per_image = batch_result.get("per_image_results", [])

        # 建立审核结果（按图片路径索引）
        audit_map: Dict[str, dict] = {}
        for result in per_image:
            img_path = result.get("image_path", "")
            if img_path:
                audit_map[img_path] = result

        total_retries = 0

        logger.info(
            "✓ 初始审核完成 | compliant=%d/%d | score=%.1f",
            batch_result.get("compliant_count", 0),
            len(all_paths),
            batch_result.get("overall_score", 0),
        )
        pipeline_log.append(
            f"✓ 初始审核: {batch_result.get('compliant_count', 0)}/{len(all_paths)} 合规"
        )

        # =================================================================
        # 第四步：对不合规图片进行重试
        # =================================================================
        retry_candidates = [
            r for r in per_image
            if r.get("is_compliant") is False
        ]

        if retry_candidates:
            step_msg = f"▶ 第四步：自动修复重绘 — {len(retry_candidates)} 张图不合规"
            logger.info(step_msg)
            pipeline_log.append(step_msg)
            self._update_task_status(task_id, PipelineStatus.RETRYING)

            for noncompliant in retry_candidates:
                img_path = noncompliant.get("image_path", "")
                img_type = path_type_map.get(img_path, "white_bg_main")
                violations = noncompliant.get("violations", [])

                if not violations:
                    continue

                # 获取原始 prompt
                original = image_set.get(img_type, {})
                original_prompt = original.get("prompt_en", "")

                retry_count = 0
                current_path = img_path
                current_audit = noncompliant

                while retry_count < max_retries and current_audit.get("is_compliant") is False:
                    retry_count += 1
                    total_retries += 1

                    logger.info(
                        "重试 %d/%d | type=%s | path=%s",
                        retry_count, max_retries, img_type, Path(current_path).name,
                    )
                    pipeline_log.append(
                        f"  ↻ 重试 {retry_count}/{max_retries}: {IMAGE_TYPE_LABELS.get(img_type, img_type)}"
                    )

                    # a) 生成修复 prompt
                    fixed_prompt = await self.compliance_checker.generate_fix_suggestions(
                        violations=violations,
                        original_prompt=original_prompt,
                    )

                    pipeline_log.append(
                        f"    → 修复 prompt 长度: {len(fixed_prompt)}"
                    )

                    # b) 用修复后的 prompt 重绘
                    try:
                        new_path = await self.image_generator.generate_single_image(
                            workflow=self.image_generator.load_workflow(
                                IMAGE_TYPE_WORKFLOW_MAP.get(
                                    img_type, IMAGE_TYPE_WORKFLOW_MAP["_default"]
                                )
                            ),
                            positive_prompt=fixed_prompt,
                            negative_prompt=original.get("negative_prompt", ""),
                            resolution=self.image_generator.parse_resolution(
                                original.get("resolution", "1024x1024")
                            ),
                            reference_image_name=reference_image_name,
                        )
                    except ImageGeneratorError as e:
                        logger.error("重绘失败: %s", str(e))
                        pipeline_log.append(f"    ✗ 重绘失败: {str(e)}")
                        break

                    # 后处理：根据图片类型优化
                    new_path = self.image_generator._post_process(
                        new_path, img_type
                    )
                    pipeline_log.append(f"    ✓ 新图: {Path(new_path).name}")

                    # c) 重新审核
                    try:
                        new_audit = await self.compliance_checker.check_image(
                            image_path=new_path,
                            platform=platform,
                            image_type=img_type,
                        )
                    except ComplianceCheckerError as e:
                        logger.error("重审失败: %s", str(e))
                        break

                    is_now_compliant = new_audit.get("is_compliant", False)
                    logger.info(
                        "  重审结果 | compliant=%s | score=%s",
                        is_now_compliant,
                        new_audit.get("overall_score"),
                    )

                    if is_now_compliant:
                        pipeline_log.append(
                            f"    ✓ 第{retry_count}次重试后合规通过！"
                        )
                        current_path = new_path
                        current_audit = new_audit
                        # 更新映射
                        type_path_map[img_type] = new_path
                        if img_path in path_type_map:
                            del path_type_map[img_path]
                        path_type_map[new_path] = img_type
                        break
                    else:
                        pipeline_log.append(
                            f"    ✗ 第{retry_count}次重试仍不合规"
                        )
                        # 用新审核结果继续下一轮
                        violations = new_audit.get("violations", [])
                        current_path = new_path
                        current_audit = new_audit
                        if img_path in path_type_map:
                            del path_type_map[img_path]
                        path_type_map[new_path] = img_type

                # 更新 audit_map
                audit_map[current_path] = current_audit
                # 更新 type_path_map
                type_path_map[img_type] = current_path

        # 构建最终结果列表
        audit_results = []
        for img_type, img_path in type_path_map.items():
            audit = audit_map.get(img_path, {})
            retry_count_val = 0
            # 计算实际重试次数
            original_paths = [
                p for p in all_paths
                if path_type_map.get(p) == img_type
            ]
            if len(original_paths) > 1 or img_path not in original_paths:
                retry_count_val = 1  # 简化：如果有重试至少1次

            audit_results.append({
                "type": img_type,
                "type_label": IMAGE_TYPE_LABELS.get(img_type, img_type),
                "path": img_path,
                "compliant": audit.get("is_compliant", False),
                "retry_count": retry_count_val,
                "audit_result": audit,
            })

        return audit_results, total_retries

    # ==================== 任务管理 ====================

    def _init_task(
        self,
        task_id: str,
        platform: str,
        product_desc: str,
    ) -> dict:
        """初始化任务"""
        task = {
            "task_id": task_id,
            "platform": platform,
            "product": product_desc,
            "status": PipelineStatus.PENDING,
            "created_at": datetime.now().isoformat(),
            "parse_result": None,
            "report": None,
            "error": None,
        }
        self._tasks[task_id] = task
        return task

    def _update_task_status(self, task_id: str, status: PipelineStatus) -> None:
        """更新任务状态"""
        if task_id in self._tasks:
            self._tasks[task_id]["status"] = status
            logger.info("管道状态: %s → %s", task_id, status.value)

    def _fail_task(self, task_id: str, error: str) -> None:
        """标记任务失败"""
        if task_id in self._tasks:
            self._tasks[task_id]["status"] = PipelineStatus.FAILED
            self._tasks[task_id]["error"] = error
            logger.error("管道失败: %s → %s", task_id, error)

    async def get_task_status(self, task_id: str) -> dict:
        """
        查询任务状态

        Args:
            task_id: 任务ID

        Returns:
            dict: 任务状态信息
        """
        task = self._tasks.get(task_id)
        if not task:
            return {
                "task_id": task_id,
                "exists": False,
                "message": "任务不存在",
            }

        return {
            "task_id": task_id,
            "exists": True,
            "platform": task.get("platform"),
            "product": task.get("product"),
            "status": task["status"].value if task.get("status") else "unknown",
            "created_at": task.get("created_at"),
            "error": task.get("error"),
        }

    # ==================== 报告生成 ====================

    def _build_final_report(
        self,
        task_id: str,
        platform: str,
        product_name: str,
        audit_results: List[dict],
        total_retries: int,
        pipeline_log: List[str],
    ) -> dict:
        """构建最终审核报告"""
        compliant_count = sum(1 for r in audit_results if r.get("compliant"))
        total_count = len(audit_results)
        scores = [r.get("audit_result", {}).get("overall_score", 0) for r in audit_results]
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0

        return {
            "task_id": task_id,
            "platform": platform,
            "product": product_name,
            "status": PipelineStatus.COMPLETED.value,
            "summary": f"共生成{total_count}张图片，{compliant_count}张合规，"
                       f"综合评分 {avg_score}，重试 {total_retries} 次",
            "images": audit_results,
            "compliance_stats": {
                "total": total_count,
                "compliant": compliant_count,
                "non_compliant": total_count - compliant_count,
                "compliance_rate": f"{compliant_count}/{total_count}",
                "average_score": avg_score,
            },
            "total_retries": total_retries,
            "created_at": datetime.now().isoformat(),
            "pipeline_log": pipeline_log,
        }

    def _build_error_report(
        self,
        task_id: str,
        platform: str,
        product_desc: str,
        error: str,
        pipeline_log: List[str],
    ) -> dict:
        """构建失败报告"""
        return {
            "task_id": task_id,
            "platform": platform,
            "product": product_desc,
            "status": PipelineStatus.FAILED.value,
            "error": error,
            "created_at": datetime.now().isoformat(),
            "pipeline_log": pipeline_log,
        }

    # ==================== 资源管理 ====================

    async def close(self) -> None:
        """关闭所有子Agent"""
        await self.rule_parser.close()
        await self.image_generator.close()
        await self.compliance_checker.close()
        logger.info("AgentOrchestrator 已关闭")
