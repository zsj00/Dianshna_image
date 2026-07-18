"""
ComfyUI 工作流JSON验证单元测试
"""
import unittest
import json
import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = BASE_DIR / "workflows"

EXPECTED_WORKFLOWS = [
    "workflow_white_bg.json",
    "workflow_scene.json",
    "workflow_detail.json",
    "workflow_comparison.json",
]

REQUIRED_NODE_TYPES = ["CLIPTextEncode", "KSampler", "VAEDecode", "CheckpointLoaderSimple"]


class TestWorkflowFiles(unittest.TestCase):
    """工作流文件完整性测试"""

    def test_all_workflows_exist(self):
        for wf_name in EXPECTED_WORKFLOWS:
            wf_path = WORKFLOW_DIR / wf_name
            self.assertTrue(wf_path.exists(), f"Missing: {wf_name}")

    def test_valid_json(self):
        for wf_name in EXPECTED_WORKFLOWS:
            wf_path = WORKFLOW_DIR / wf_name
            with open(wf_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            self.assertIsInstance(data, dict, f"Not a dict: {wf_name}")
            self.assertIn("nodes", data, f"{wf_name}: missing 'nodes'")
            self.assertIn("links", data, f"{wf_name}: missing 'links'")

    def test_required_nodes_present(self):
        for wf_name in EXPECTED_WORKFLOWS:
            wf_path = WORKFLOW_DIR / wf_name
            with open(wf_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)

            class_types = [n["type"] for n in data.get("nodes", [])]

            for required in REQUIRED_NODE_TYPES:
                self.assertIn(
                    required, class_types,
                    f"{wf_name}: missing {required}"
                )

    def test_has_clip_text_encode_nodes(self):
        """每个工作流必须至少有1个CLIPTextEncode节点"""
        for wf_name in EXPECTED_WORKFLOWS:
            wf_path = WORKFLOW_DIR / wf_name
            with open(wf_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)

            clip_nodes = [
                n for n in data.get("nodes", [])
                if n.get("type") == "CLIPTextEncode"
            ]
            self.assertGreaterEqual(
                len(clip_nodes), 1,
                f"{wf_name}: need at least 1 CLIPTextEncode node"
            )

    def test_white_bg_has_correct_prefix(self):
        """白色背景工作流应有正确的输出前缀"""
        wf_path = WORKFLOW_DIR / "workflow_white_bg.json"
        with open(wf_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)

        save_nodes = [
            n for n in data.get("nodes", [])
            if "SaveImage" in n.get("type", "")
        ]
        self.assertGreater(len(save_nodes), 0, "No SaveImage node found")

        prefix = save_nodes[0].get("widgets_values", [""])[0]
        self.assertIn("white_bg", prefix.lower(),
                      f"Expected white_bg in prefix, got: {prefix}")

    def test_scene_workflow_prefix(self):
        """场景工作流应有scene前缀"""
        wf_path = WORKFLOW_DIR / "workflow_scene.json"
        with open(wf_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)

        save_nodes = [
            n for n in data.get("nodes", [])
            if "SaveImage" in n.get("type", "")
        ]
        prefix = save_nodes[0].get("widgets_values", [""])[0]
        self.assertIn("scene", prefix.lower(),
                      f"Expected scene in prefix, got: {prefix}")


class TestWorkflowContent(unittest.TestCase):
    """工作流内容质量测试"""

    def test_no_empty_prompts_in_production(self):
        """生产环境工作流的默认prompt不应为空"""
        for wf_name in ["workflow_scene.json", "workflow_detail.json", "workflow_comparison.json"]:
            wf_path = WORKFLOW_DIR / wf_name
            with open(wf_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)

            clip_nodes = [
                n for n in data.get("nodes", [])
                if n.get("type") == "CLIPTextEncode"
            ]

            for node in clip_nodes:
                text = node.get("widgets_values", [""])[0]
                self.assertTrue(
                    isinstance(text, str) and len(text.strip()) > 0,
                    f"{wf_name}: CLIPTextEncode node {node.get('id')} has empty prompt"
                )

    def test_checkpoint_model_consistent(self):
        """所有工作流应使用同一checkpoint"""
        models = set()
        for wf_name in EXPECTED_WORKFLOWS:
            wf_path = WORKFLOW_DIR / wf_name
            with open(wf_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)

            for node in data.get("nodes", []):
                if node.get("type") == "CheckpointLoaderSimple":
                    models.add(tuple(node.get("widgets_values", [])))

        self.assertGreater(len(models), 0, "No checkpoint found in workflows")

    def test_scene_negative_prompt_is_negative(self):
        """场景工作流的负面prompt应包含负面关键词"""
        wf_path = WORKFLOW_DIR / "workflow_scene.json"
        with open(wf_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)

        clip_nodes = [
            n for n in data.get("nodes", [])
            if n.get("type") == "CLIPTextEncode"
        ]

        # 按节点ID排序：较小的=正面，较大的=负面
        clip_nodes.sort(key=lambda n: n["id"])

        self.assertGreaterEqual(len(clip_nodes), 2,
                                "Scene workflow needs at least 2 CLIPTextEncode nodes")

        negative_text = clip_nodes[-1].get("widgets_values", [""])[0].lower()
        # 负面prompt应包含典型的负面关键词
        negative_keywords = ["blurry", "watermark", "text", "low quality", "deformed"]
        has_negative = any(kw in negative_text for kw in negative_keywords)
        self.assertTrue(has_negative,
                        f"Negative prompt does not contain expected keywords. Got: {negative_text[:100]}")


if __name__ == "__main__":
    unittest.main()
