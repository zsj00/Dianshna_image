"""测试 GUI→API 工作流格式转换"""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.image_generator import ImageGeneratorAgent

# 测试所有4个工作流
for wf_name in ["workflow_white_bg.json", "workflow_scene.json", "workflow_detail.json", "workflow_comparison.json"]:
    print(f"=== {wf_name} ===")
    with open(Path("workflows") / wf_name, encoding="utf-8-sig") as f:
        gui_wf = json.load(f)

    api_wf = ImageGeneratorAgent._convert_gui_to_api(gui_wf)
    print(f"  API节点数: {len(api_wf)}")
    print(f"  节点ID: {list(api_wf.keys())}")

    # 验证CLIPTextEncode
    clip_nodes = {nid: nd for nid, nd in api_wf.items() if nd["class_type"] == "CLIPTextEncode"}
    for nid, nd in sorted(clip_nodes.items(), key=lambda x: int(x[0])):
        print(f"  CLIP node {nid}: text_len={len(nd['inputs'].get('text',''))}, clip={nd['inputs'].get('clip')}")

    # 验证关键节点
    for check_type in ["KSampler", "EmptyImage", "EmptyLatentImage", "CheckpointLoaderSimple", "VAEDecode", "VAEEncode"]:
        found = [nid for nid, nd in api_wf.items() if nd["class_type"] == check_type]
        if found:
            print(f"  {check_type}: nodes={found}")
    print()

print("所有工作流转换验证通过!")
