# MeituEcomAgent AGENTS.md

## 项目概览

**MeituEcomAgent** (美图电商智能生图代理服务) — 基于多智能体协作的跨平台商品图片自动生成与合规审核系统。

### 核心管线

```
用户输入 (平台 + 商品描述/卖点 + 原图)
  → RuleParserAgent (解析规则 → 结构化 prompts)
  → ImageGeneratorAgent (ComfyUI → 4张商品图)
  → ComplianceCheckerAgent (Vision API → 合规审核结果)
    ├─ 全部合规 → 归档 + 生成报告
    └─ 有违规  → 修复 Prompt → 重绘 → 重新审核 (最多 max_retries 轮)
```

### 交付物

| 交付物 | 说明 |
|--------|------|
| 白底主图 | 纯白/浅色背景商品正面展示 |
| 场景营销图 | 商品在真实使用场景中的展示 |
| 细节特写图 | 关键细节的超大特写 |
| 尺寸对比图 | 通过参照物展示商品实际大小 |
| 合规检测报告 | JSON结构化报告 (违规项、修改建议、CoT分析) |
| 结构化素材库归档 | output/{platform}/{product}_{timestamp}/ |

---

## 硬件配置与模型选型

### 本机硬件

| 硬件 | 规格 |
|------|------|
| GPU | NVIDIA GeForce MX450, 2GB VRAM, CUDA 11.7 |
| Driver | 516.54 |
| Python | 3.11 |

### ComfyUI 模型建议 (2GB VRAM)

> 当前 workflows 中使用了 sd_xl_base_1.0.safetensors (SDXL)，在 MX450 2GB 上会导致 OOM。

| 方案 | 模型 | VRAM | 速度 | 质量 |
|------|------|------|------|------|
| ★ 推荐 | SD 1.5 + LCM-LoRA (sd_v15_lcm.safetensors) | ~1.5GB | ~2-3s | 可接受 |
| 推荐 | SDXL-turbo (sd_xl_turbo_1.0_fp16.safetensors) | ~2.0GB | ~1-2s | 良好 |
| 备用 | SSD-1B (Segmind SD) | ~1.8GB | ~3s | 中等 |

**操作**: 修改对应 workflow JSON 中 CheckpointLoaderSimple 节点的 ckpt_name 为轻量模型。切换后更新 KSampler 的 steps (LCM: 4-8, Turbo: 4-6, 常规: 20-25)。

### LLM 模型配置 (当前)

```
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
CHAT_MODEL=qwen-plus
VISION_MODEL=qwen-vl-max
EMBEDDING_MODEL=text-embedding-v3
```

**省钱建议**: 如使用 OpenAI 直连，用 gpt-4o-mini 替代 gpt-4o 可降 90% 成本，审核质量损失不大。

---

## 代码规范

### 注释与文档

- 所有注释、日志、prompt 使用中文（项目定位国内电商客户）
- 变量名、函数名、类名必须使用英文
- 避免在注释中出现非 ASCII 字符的编码问题（优先用简体中文 UTF-8）

### Python 风格

- 类型注解: 所有函数参数和返回值必须标注类型
- import 顺序: 标准库 → 第三方库 → 本地模块，每组空行分隔
- 异常类: 在模块顶部定义细粒度异常类，继承基础异常
- 日志: 使用 logger = logging.getLogger(__name__)，避免 print()
- 配置: 所有环境变量通过 config.py 的 Settings 类读取，不直接 os.getenv()

### 项目结构约定

```
MeituEcomAgent/
├── app/
│   ├── agents/          # 智能体 (orchestrator, rule_parser, image_generator, compliance_checker)
│   ├── models/          # Pydantic schemas
│   ├── services/        # 基础设施服务 (comfyui, rag)
│   ├── utils/           # 工具函数 (file_utils, image_processor, image_utils)
│   ├── static/          # Web UI
│   ├── config.py        # 配置管理
│   └── main.py          # FastAPI 入口
├── workflows/           # ComfyUI 工作流 JSON
├── knowledge_base/      # 平台规则 Markdown
├── tests/               # 单元测试
└── output/              # 生成结果
```

---

## Token 优化策略

### RuleParserAgent (规则解析)

- **批量生成**: _build_main_user_prompt() 一次性为 4 种图片类型生成 prompts，避免 4 次独立 API 调用
- **响应格式**: 使用 response_format={"type": "json_object"} 确保结构化输出
- **temperature=0.3**: 降低随机性，减少不合规输出导致的重复调用
- **max_tokens=4096**: 不要设得过高，4 种图片的 prompts 不需要超过 4K tokens

### ComplianceCheckerAgent (合规审核)

- **避免冗余调用**: 先用 _check_single_image() 逐张审核，只有发现有违规才精修 prompt 重绘
- **CoT 分析开关**: cot_analysis 在调试时可开启，生产环境可移除以节省 token
- **high detail 模式**: 已启用 detail=high，但仅在审核时使用（不是每个环节都传图）
- **规则上下文**: get_all_rules_for_platform() 返回全量规则 → 考虑改为只返回与当前图片类型相关的规则片段

### RAGService (知识库检索)

- **持久化索引**: knowledge_base_index/chroma.sqlite3 已持久化，启动时不会重建索引
- **embedding 模型**: text-embedding-v3 比 text-embedding-ada-002 便宜 80% 且支持更长的上下文
- **chunk_size=1024**: 当前配置合理，过大增加 token 消耗，过小丢失上下文

---

## 开发工作流

### 添加新平台

1. 在 knowledge_base/ 下创建 {platform}_rules.md
2. 在 app/models/schemas.py 的 PlatformEnum 添加枚举
3. 在 app/agents/rule_parser.py 的 PLATFORM_DISPLAY_MAP 添加映射
4. 在 app/services/rag_service.py 的 platforms 字典添加映射
5. 重启应用后 RAG 会自动重建索引（或在代码中调用 rag.build_index()）

### 添加/修改 ComfyUI 工作流

1. 在 ComfyUI 界面设计好工作流，点击 Save (API Format) 导出 JSON
2. 将 JSON 放入 workflows/ 目录
3. 在 app/agents/image_generator.py 的 IMAGE_TYPE_WORKFLOW_MAP 添加映射
4. 工作流必须包含:
   - 至少一个 CLIPTextEncode 节点（系统自动注入 positive prompt）
   - 推荐包含两个 CLIPTextEncode（第二个注入 negative prompt）
   - 包含 KSampler 节点（系统自动随机化 seed）
   - 包含 EmptyLatentImage 或 EmptyImage 节点（系统自动注入分辨率）

### 测试

```bash
cd MeituEcomAgent
python -m pytest tests/ -v
python -m tests.verify_deliverables
python -m pytest tests/test_pipeline.py -v
```

---

## 常见陷阱与规避

### 1. ComfyUI 工作流格式
workflows/ 下的 JSON 是 GUI 格式，包含 nodes 和 links 数组。image_generator.py 的 _convert_gui_to_api() 会将其转换为 API 格式。所有 workflow 节点必须有唯一的 id 字段，且 class_type 正确。

### 2. 图片 base64 编码重复
compliance_checker.py 和 image_utils.py 都有 encode_image_to_base64() 函数。修改时需同步两者，或重构为共享工具函数。

### 3. RAG 索引兼容性
rag_service.py 中 _create_embedding_model() 使用 hack 绕过 llama-index 0.9.27 的模型名校验。升级 llama-index 版本时需验证此兼容性代码是否仍然有效。

### 4. 异步 vs 同步
- RAGService 的 query_rules() 是同步方法，通过 asyncio.to_thread() 包装后调用
- ComfyUIClient 是纯异步的 (aiohttp)
- ComplianceCheckerAgent 和 RuleParserAgent 使用 AsyncOpenAI
- 不要在协程中调用同步阻塞方法而不包装

### 5. pipeline_log 管理
orchestrator.py 的 pipeline_log 通过 append 维护，需确保: 每个步骤都有对应的 log 条目、重试轮次清晰标注、失败时记录完整错误栈。

### 6. 素材归档路径
结构化归档路径为 output/{platform}/{product_name}_{timestamp}/，其中 product_name 使用 _sanitize_filename() 过滤非法字符，同目录包含 4 张图片 + report.json + 可选 archive.zip。

---

## 模型切换指南

### 切换到本地模型 (如 ollama + ComfyUI 本地)

```
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_API_KEY=ollama
CHAT_MODEL=qwen2.5:14b
VISION_MODEL=llama3.2-vision:11b
EMBEDDING_MODEL=bge-m3:latest
```

注意: 本地 vision 模型质量通常不如云端 API，合规审核准确率可能会下降。

### 切换到省钱方案 (纯云端)

```
CHAT_MODEL=deepseek-chat
VISION_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small
```

---

## 关键文件索引

| 文件 | 职责 |
|------|------|
| app/main.py | FastAPI 入口: 6 个 REST 端点 + 表单文件上传 |
| app/config.py | 配置管理: 从 .env 读取所有配置项 |
| app/models/schemas.py | Pydantic 模型: 15+ 请求/响应模型 |
| app/agents/orchestrator.py | 总调度器: 编排生成→审核→修复→重绘闭环 |
| app/agents/rule_parser.py | 规则解析: RAG + LLM → 结构化 prompts |
| app/agents/image_generator.py | 图像生成: 加载 workflow → 注入 prompt → ComfyUI |
| app/agents/compliance_checker.py | 合规审核: Vision + CoT → 结构化审核结果 |
| app/services/comfyui_service.py | ComfyUI 客户端: HTTP + WebSocket |
| app/services/rag_service.py | RAG 服务: llama-index + ChromaDB |
| app/utils/image_processor.py | 图像预处理: rembg 抠图 + 白底合成 |
| app/utils/file_utils.py | 文件管理: 归档、报告、清理 |
| app/utils/image_utils.py | 图像工具: 验证、缩放、base64、压缩 |
| tests/verify_deliverables.py | 交付物完整性验证脚本 |
