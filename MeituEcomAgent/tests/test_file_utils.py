"""
文件工具函数单元测试
"""
import unittest
import os
import tempfile
import shutil
import json
from pathlib import Path

from app.utils.file_utils import (
    create_output_directory,
    create_task_dir,
    copy_to_task_dir,
    save_report,
)


class TestFileUtils(unittest.TestCase):
    """文件工具测试"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_output_directory(self):
        result = create_output_directory("amazon", "红色陶瓷咖啡杯")
        self.assertTrue(os.path.exists(result))
        self.assertIn("amazon", result)
        # 清理
        shutil.rmtree(result, ignore_errors=True)

    def test_create_output_directory_cleans_name(self):
        result = create_output_directory("taobao", "test/product*na:me?")
        self.assertTrue(os.path.exists(result))
        basename = os.path.basename(result)
        self.assertNotIn("/", basename)
        self.assertNotIn("*", basename)
        # 清理
        parent = os.path.dirname(result)
        shutil.rmtree(parent, ignore_errors=True)

    def test_create_task_dir(self):
        task_dir = create_task_dir("test-task-123")
        self.assertTrue(os.path.exists(task_dir))
        self.assertIn("test-task-123", str(task_dir))
        # 清理
        parent = task_dir.parent
        shutil.rmtree(task_dir, ignore_errors=True)

    def test_copy_to_task_dir(self):
        # 创建临时源文件
        src_file = os.path.join(self.temp_dir, "test_image.png")
        with open(src_file, "w") as f:
            f.write("fake image data")

        task_dir = create_task_dir("copy-test")
        result = copy_to_task_dir(task_dir, [src_file])
        self.assertEqual(len(result), 1)
        self.assertTrue(os.path.exists(result[0]))
        # 清理
        parent = task_dir.parent
        shutil.rmtree(task_dir, ignore_errors=True)

    def test_copy_to_task_dir_nonexistent(self):
        """复制不存在的文件应跳过"""
        task_dir = create_task_dir("skip-test")
        result = copy_to_task_dir(task_dir, ["/nonexistent/path.png"])
        self.assertEqual(len(result), 0)
        # 清理
        parent = task_dir.parent
        shutil.rmtree(task_dir, ignore_errors=True)

    def test_save_report(self):
        task_dir = create_task_dir("report-test")
        report_path = save_report(task_dir, {"status": "completed", "score": 95.5})
        self.assertTrue(os.path.exists(report_path))
        with open(report_path, "r") as f:
            data = json.load(f)
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["score"], 95.5)
        # 清理
        parent = task_dir.parent
        shutil.rmtree(task_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
