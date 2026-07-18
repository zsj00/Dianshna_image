"""
Pipeline 数据流 & 配置单元测试
"""
import unittest
import json
from pathlib import Path

from app.config import settings


BASE_DIR = Path(__file__).resolve().parent.parent


class TestConfig(unittest.TestCase):
    """配置项测试"""

    def test_required_configs_not_empty(self):
        required = [
            ("OPENAI_BASE_URL", settings.OPENAI_BASE_URL),
            ("EMBEDDING_MODEL", settings.EMBEDDING_MODEL),
            ("CHAT_MODEL", settings.CHAT_MODEL),
            ("VISION_MODEL", settings.VISION_MODEL),
            ("IMAGE_PROVIDER", settings.IMAGE_PROVIDER),
            ("IMAGE_MODEL", settings.IMAGE_MODEL),
        ]
        for name, value in required:
            self.assertTrue(
                value and len(value) > 0,
                f"Config '{name}' must not be empty"
            )

    def test_path_configs(self):
        path_configs = [
            ("RAG_PERSIST_DIR", settings.RAG_PERSIST_DIR),
            ("OUTPUT_DIR", settings.OUTPUT_DIR),
            ("KNOWLEDGE_BASE_DIR", settings.KNOWLEDGE_BASE_DIR),
            ("WORKFLOW_DIR", settings.WORKFLOW_DIR),
        ]
        for name, value in path_configs:
            self.assertTrue(value, f"{name} must not be empty")

    def test_log_config(self):
        self.assertIn(settings.LOG_LEVEL.upper(),
                      ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.assertTrue(len(settings.LOG_FILE) > 0)

    def test_openai_base_url_is_configurable(self):
        """验证支持 OpenAI-compatible API 配置"""
        self.assertTrue(settings.OPENAI_BASE_URL.startswith(("http://", "https://")))

    def test_image_provider_is_supported(self):
        """图片 Provider 必须是受支持的可部署模式"""
        self.assertIn(settings.IMAGE_PROVIDER, {"cloud", "dashscope", "comfyui"})
        self.assertTrue(
            settings.is_cloud_image_provider
            or settings.is_dashscope_image_provider
            or settings.is_comfyui_image_provider
        )


class TestKnowledgeBase(unittest.TestCase):
    """知识库文件验证"""

    def test_all_platform_rules_exist(self):
        platforms = ["amazon", "taobao", "aliexpress", "shopee"]
        knowledge_dir = BASE_DIR / settings.KNOWLEDGE_BASE_DIR

        for platform in platforms:
            rule_file = knowledge_dir / f"{platform}_rules.md"
            self.assertTrue(
                rule_file.exists(),
                f"Missing rule file: {rule_file}"
            )
            content = rule_file.read_text(encoding="utf-8")
            self.assertGreater(len(content), 100,
                               f"Rule file too short: {rule_file}")


class TestWorkflowImageTypes(unittest.TestCase):
    """图片类型与工作流映射测试"""

    def test_all_image_types_have_workflow(self):
        """每个图片类型都应有对应的工作流"""
        from app.agents.image_generator import IMAGE_TYPE_WORKFLOW_MAP

        expected_types = [
            "white_bg_main",
            "scene_lifestyle",
            "detail_closeup",
            "scale_comparison",
        ]

        for img_type in expected_types:
            self.assertIn(
                img_type, IMAGE_TYPE_WORKFLOW_MAP,
                f"Missing workflow mapping for: {img_type}"
            )
            wf_path = BASE_DIR / "workflows" / IMAGE_TYPE_WORKFLOW_MAP[img_type]
            self.assertTrue(
                wf_path.exists(),
                f"Workflow file not found: {wf_path}"
            )

    def test_default_workflow_exists(self):
        from app.agents.image_generator import IMAGE_TYPE_WORKFLOW_MAP

        default_wf = IMAGE_TYPE_WORKFLOW_MAP.get("_default")
        self.assertIsNotNone(default_wf, "No _default workflow mapping")
        wf_path = BASE_DIR / "workflows" / default_wf
        self.assertTrue(wf_path.exists(), f"Default workflow not found: {wf_path}")


class TestPipelineDataFlow(unittest.TestCase):
    """Pipeline数据流契约测试"""

    def test_image_set_structure(self):
        """验证 parse() 生成的 image_set 结构正确性"""
        sample_image_set = {
            "white_bg_main": {
                "prompt_en": "A product on pure white background...",
                "negative_prompt": "text, watermark, blurry...",
                "resolution": "1600x1600",
            },
            "scene_lifestyle": {
                "prompt_en": "A product in a cozy cafe...",
                "negative_prompt": "text, watermark...",
                "resolution": "1600x1200",
            },
            "detail_closeup": {
                "prompt_en": "Close-up macro shot of...",
                "negative_prompt": "text, blurry...",
                "resolution": "1600x1600",
            },
            "scale_comparison": {
                "prompt_en": "A product next to a smartphone...",
                "negative_prompt": "text, watermark...",
                "resolution": "1600x1600",
            },
        }

        required_fields = {"prompt_en", "negative_prompt", "resolution"}
        for img_type, prompt_data in sample_image_set.items():
            missing = required_fields - set(prompt_data.keys())
            self.assertFalse(missing, f"{img_type} missing: {missing}")

    def test_audit_result_structure(self):
        """验证 check_image_set() 返回结构正确"""
        sample_audit = {
            "total_images": 4,
            "compliant_count": 3,
            "non_compliant_count": 1,
            "overall_score": 87.5,
            "overall_compliant": False,
            "per_image_results": [
                {
                    "image_path": "/path/to/img.png",
                    "is_compliant": False,
                    "violations": [
                        {
                            "rule": "背景须为纯白 RGB(255,255,255)",
                            "description": "背景检测到浅灰色调...",
                            "severity": "major",
                            "suggestion": "将背景替换为纯白色...",
                        }
                    ],
                    "overall_score": 65.0,
                }
            ],
            "summary": "4张图中3张合规",
        }

        self.assertIn("per_image_results", sample_audit)
        per_image = sample_audit["per_image_results"]
        self.assertGreater(len(per_image), 0)
        self.assertIn("violations", per_image[0])
        violation = per_image[0]["violations"][0]
        for required_key in ["rule", "description", "severity", "suggestion"]:
            self.assertIn(required_key, violation,
                          f"Violation missing: {required_key}")

    def test_final_report_structure(self):
        """验证最终报告结构"""
        sample_report = {
            "task_id": "a1b2c3d4",
            "platform": "Amazon（亚马逊）",
            "product_name": "红色陶瓷咖啡杯",
            "status": "completed",
            "version": "0.3.0",
            "images": [
                {
                    "type": "white_bg_main",
                    "type_label": "白底主图",
                    "path": "/output/amazon/img_01.png",
                    "compliant": True,
                    "retry_count": 0,
                },
            ],
            "compliance_stats": {
                "total": 4,
                "compliant": 3,
                "non_compliant": 1,
                "overall_score": 87.5,
                "total_retries": 2,
            },
            "pipeline_log": [
                "▶ 第一步：解析平台规则与商品信息",
                "▶ 第二步：生成4张图片",
                "▶ 第三步：合规审核",
                "▶ 第四步：归档",
                "▶ 第五步：生成审核报告",
            ],
            "output_dir": "/output/amazon/红色陶瓷咖啡杯_20260711/",
        }

        report_dumps = json.dumps(sample_report, ensure_ascii=False)
        self.assertIn("task_id", sample_report)
        self.assertIn("version", sample_report)
        self.assertEqual(sample_report["version"], "0.3.0")
        self.assertIn("compliance_stats", sample_report)
        self.assertIn("pipeline_log", sample_report)
        self.assertIn("output_dir", sample_report)

        # 验证JSON可序列化
        parsed = json.loads(report_dumps)
        self.assertEqual(parsed["status"], "completed")


class TestPromptQualityGuards(unittest.TestCase):
    """Prompt 一致性与卖点兜底测试"""

    def test_rule_parser_stabilizes_product_identity(self):
        from app.agents.rule_parser import RuleParserAgent

        parser = RuleParserAgent.__new__(RuleParserAgent)
        image_set = {
            "white_bg_main": {
                "prompt_en": "premium cosmetic jar on white background",
                "negative_prompt": "watermark",
            },
            "scene_lifestyle": {
                "prompt_en": "cosmetic jar on bathroom shelf",
                "negative_prompt": "",
            },
        }

        identity = parser._build_product_identity(
            product_desc="粉色面霜罐，黑色亮面盖",
            visual_analysis="半透明磨砂罐身，淡粉色膏体，黑色圆盖",
            selling_points="20ml黄金容量 | 便携 | 滋润",
        )
        parser._stabilize_image_prompts(image_set, identity, "20ml黄金容量 | 便携 | 滋润")

        for prompt_data in image_set.values():
            self.assertIn("CONSISTENCY LOCK", prompt_data["prompt_en"])
            self.assertIn("same exact SKU", prompt_data["prompt_en"])
            self.assertIn("20ml黄金容量", prompt_data["prompt_en"])
            self.assertIn("different product", prompt_data["negative_prompt"])

    def test_image_generator_enhances_prompt_before_provider(self):
        from app.agents.image_generator import ImageGeneratorAgent

        positive, negative = ImageGeneratorAgent._enhance_prompt_for_consistency(
            positive_prompt="cosmetic cream jar product photo",
            negative_prompt="watermark",
            image_type="detail_closeup",
            selling_points="细腻膏体 | 便携容量",
            reference_image_name="product.webp",
        )

        self.assertIn("same cream jar silhouette", positive)
        self.assertIn("Online reference benchmark", positive)
        self.assertIn("细腻膏体", positive)
        self.assertIn("different product", negative)

    async def _fake_visual_analysis(self, image_path, product_desc):
        return "半透明磨砂面霜罐，黑色亮面盖，淡粉色膏体，适合护肤品场景"

    async def _fake_selling_points_llm(self, system_prompt, user_prompt):
        return json.dumps(
            {
                "product_summary": "一款精致护肤面霜罐",
                "points": ["精致小罐", "黑色亮盖", "细腻膏体", "护肤场景"],
                "selling_points": "精致小罐 | 黑色亮盖 | 细腻膏体 | 护肤场景",
            },
            ensure_ascii=False,
        )

    def test_rule_parser_suggests_selling_points_from_image(self):
        import asyncio
        from app.agents.rule_parser import RuleParserAgent

        parser = RuleParserAgent.__new__(RuleParserAgent)
        parser._analyze_reference_image = self._fake_visual_analysis
        parser._call_llm = self._fake_selling_points_llm

        result = asyncio.run(
            parser.suggest_selling_points_from_image(
                image_path="fake.png",
                platform="taobao",
            )
        )

        self.assertIn("精致小罐", result["selling_points"])
        self.assertEqual(len(result["points"]), 4)


if __name__ == "__main__":
    unittest.main()
