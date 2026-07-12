"""
Pydantic 数据模型单元测试
"""
import unittest
from datetime import datetime

from app.models.schemas import (
    PlatformEnum,
    TaskStatusEnum,
    ImageTypeEnum,
    GenerateRequest,
    ComplianceCheckRequest,
    HealthCheckResponse,
    RuleInfo,
    PipelineFormRequest,
)


class TestPlatformEnum(unittest.TestCase):
    """平台枚举测试"""

    def test_valid_platforms(self):
        self.assertEqual(PlatformEnum.AMAZON.value, "amazon")
        self.assertEqual(PlatformEnum.TAOBAO.value, "taobao")
        self.assertEqual(PlatformEnum.ALIEXPRESS.value, "aliexpress")
        self.assertEqual(PlatformEnum.SHOPEE.value, "shopee")

    def test_platform_list(self):
        platforms = [p.value for p in PlatformEnum]
        self.assertIn("amazon", platforms)
        self.assertIn("taobao", platforms)
        self.assertIn("aliexpress", platforms)
        self.assertIn("shopee", platforms)


class TestTaskStatusEnum(unittest.TestCase):
    """任务状态枚举测试"""

    def test_status_flow_order(self):
        expected_order = [
            "pending", "parsing", "generating", "auditing",
            "retrying", "archiving", "completed", "failed",
        ]
        values = [s.value for s in TaskStatusEnum]
        self.assertEqual(values, expected_order)


class TestImageTypeEnum(unittest.TestCase):
    """图片类型枚举测试"""

    def test_image_types(self):
        types = [t.value for t in ImageTypeEnum]
        self.assertIn("white_bg_main", types)
        self.assertIn("scene_lifestyle", types)
        self.assertIn("detail_closeup", types)
        self.assertIn("scale_comparison", types)


class TestGenerateRequest(unittest.TestCase):
    """生图请求模型测试"""

    def test_minimal_request(self):
        req = GenerateRequest(
            platform=PlatformEnum.AMAZON,
            product_desc="红色陶瓷咖啡杯",
        )
        self.assertEqual(req.platform, PlatformEnum.AMAZON)
        self.assertEqual(req.product_desc, "红色陶瓷咖啡杯")
        self.assertIsNone(req.reference_image_url)

    def test_full_request(self):
        req = GenerateRequest(
            platform=PlatformEnum.TAOBAO,
            product_desc="蓝色运动跑鞋，透气网面设计",
            reference_image_url="https://example.com/shoe.jpg",
            max_retries=5,
        )
        self.assertEqual(req.platform, PlatformEnum.TAOBAO)
        self.assertEqual(req.max_retries, 5)
        self.assertIsNotNone(req.reference_image_url)

    def test_empty_product_desc_raises(self):
        with self.assertRaises(Exception):
            GenerateRequest(platform=PlatformEnum.AMAZON, product_desc="   ")


class TestComplianceCheckRequest(unittest.TestCase):
    """合规审核请求测试"""

    def test_request(self):
        req = ComplianceCheckRequest(
            image_url="/path/to/image.png",
            platform=PlatformEnum.AMAZON,
            image_type=ImageTypeEnum.WHITE_BG_MAIN,
        )
        self.assertEqual(req.platform, PlatformEnum.AMAZON)
        self.assertEqual(req.image_type, ImageTypeEnum.WHITE_BG_MAIN)


class TestPipelineFormRequest(unittest.TestCase):
    """Pipeline表单请求测试"""

    def test_valid_request(self):
        req = PipelineFormRequest(
            platform="amazon",
            selling_points="350ml大容量 | 哑光釉面 | 食品级陶瓷",
        )
        self.assertEqual(req.platform, "amazon")
        self.assertIn("陶瓷", req.selling_points)


class TestHealthCheckResponse(unittest.TestCase):
    """健康检查响应测试"""

    def test_version(self):
        resp = HealthCheckResponse(status="healthy")
        self.assertEqual(resp.version, "0.3.0")
        self.assertEqual(resp.status, "healthy")

    def test_fields_exist(self):
        resp = HealthCheckResponse(status="healthy")
        data = resp.model_dump()
        self.assertIn("status", data)
        self.assertIn("version", data)
        self.assertIn("api", data)
        self.assertIn("comfyui", data)
        self.assertIn("knowledge_base", data)


class TestRuleInfo(unittest.TestCase):
    """规则信息模型测试"""

    def test_rule_info(self):
        rule = RuleInfo(
            platform="Amazon（亚马逊）",
            platform_code="amazon",
            filename="amazon_rules.md",
            rules_text="# Amazon 主图规范\n...",
        )
        self.assertIn("亚马逊", rule.platform)
        self.assertEqual(rule.platform_code, "amazon")
        self.assertEqual(rule.filename, "amazon_rules.md")


if __name__ == "__main__":
    unittest.main()
