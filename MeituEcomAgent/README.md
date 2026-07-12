# MeituEcomAgent

> 美图电商智能生图代理服务 — 基于多智能体协作的跨平台商品图片自动生成与合规审核系统。

## 功能列表

- **规则解析** — 自动解析 Amazon、速卖通、淘宝/天猫、Shopee 四大平台的图片合规规则，生成结构化生图指令
- **智能生图** — 调用 ComfyUI，一次生成白底主图、场景生活图、细节特写图、尺寸对比图，共4张商品套图
- **合规审核** — 使用 GPT-4o 多模态能力 + Chain of Thought 思维链，逐条对照平台规则审核图片合规性
- **自动修复** — 不合规图片自动生成修复 prompt，调度 ComfyUI 重绘，形成"生成→审核→修复→重绘"闭环
- **知识库检索** — 基于 llama-index + ChromaDB 的 RAG 知识库，支持按平台精确查询规则
- **RESTful API** — FastAPI 提供完整 REST API，支持异步任务提交与轮询
- **容器化部署** — 提供 Dockerfile + docker-compose，一键编排 API 服务 + ChromaDB 向量数据库

---

## 技术架构

```
                            ┌─────────────────────────┐
                            │     FastAPI REST API     │
                            │     (app/main.py)        │
                            └───────────┬─────────────┘
                                        │
                            ┌───────────▼─────────────┐
                            │   AgentOrchestrator      │
                            │  (agents/orchestrator.py)│
                            │  生成→审核→修复→重绘 闭环  │
                            └─────┬──────┬──────┬─────┘
                                  │      │      │
                   ┌──────────────▼┐ ┌───▼───┐ ┌▼──────────────┐
                   │ RuleParser    │ │Image  │ │Compliance     │
                   │ Agent         │ │Gen    │ │Checker Agent  │
                   │               │ │Agent  │ │               │
                   └──────┬────────┘ └───┬───┘ └──────┬────────┘
                          │              │              │
              ┌───────────▼──┐   ┌──────▼──────┐  ┌───▼───────────┐
              │  RAG Service │   │ ComfyUI     │  │  OpenAI GPT-4o│
              │ (llama-index │   │ Service     │  │  (Vision API) │
              │  + ChromaDB) │   │ (aiohttp)   │  │               │
              └──────────────┘   └─────────────┘  └───────────────┘
```

### 核心流程

```
用户输入 (平台 + 商品描述)
    │
    ▼
RuleParserAgent ─── RAG知识库 ─── GPT-4o ─── 结构化 Prompts
    │
    ▼
ImageGeneratorAgent ─── ComfyUI ─── 4张商品图片
    │
    ▼
ComplianceCheckerAgent ─── GPT-4o Vision ─── 合规审核结果
    │
    ├── 全部合规 ──→ 归档 + 生成报告 ──→ 返回结果
    │
    └── 有违规 ──→ 生成修复Prompt ──→ 重绘 ──→ 重新审核
                                           ↑                 │
                                           └── 最多3次 ──────┘
```

---

## 快速开始

### 环境要求

| 依赖 | 版本要求 |
|------|---------|
| Python | 3.11+ |
| Docker (可选) | 20.10+ |
| ComfyUI | 最新版（需单独启动） |
| OpenAI API Key | 需支持 GPT-4o 和 text-embedding-ada-002 |

### 安装步骤

```bash
# 1. 克隆项目
cd MeituEcomAgent

# 2. 创建虚拟环境
python -m venv venv
# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key 和 ComfyUI 地址

# 5. 启动服务
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 配置说明（.env）

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `OPENAI_API_KEY` | 是 | — | OpenAI API 密钥 |
| `OPENAI_BASE_URL` | 否 | `https://api.openai.com/v1` | API 端点（可使用代理） |
| `COMFYUI_SERVER_ADDRESS` | 是 | `127.0.0.1:8188` | ComfyUI 服务地址 |
| `EMBEDDING_MODEL` | 否 | `text-embedding-ada-002` | 向量嵌入模型 |
| `CHAT_MODEL` | 否 | `gpt-4o` | 对话模型（需支持 vision） |
| `IMAGE_MODEL` | 否 | `dall-e-3` | 图片生成模型（预留） |
| `RAG_PERSIST_DIR` | 否 | `./knowledge_base_index` | 向量索引持久化目录 |
| `OUTPUT_DIR` | 否 | `./output` | 生成图片输出目录 |
| `KNOWLEDGE_BASE_DIR` | 否 | `./knowledge_base` | 规则文件目录 |
| `WORKFLOW_DIR` | 否 | `./workflows` | ComfyUI 工作流目录 |

### 启动方式

**方式一：本地启动**

```bash
# 安装依赖并启动
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**方式二：Docker 启动**

```bash
# 构建并启动所有服务（API + ChromaDB）
docker-compose up -d

# 查看日志
docker-compose logs -f api

# 停止服务
docker-compose down
```

**方式三：仅启动 API（已有 ChromaDB）**

```bash
docker build -t meitu-ecom-agent .
docker run -p 8000:8000 --env-file .env meitu-ecom-agent
```

启动后访问：
- API 文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/api/v1/health

---

## API 文档

### 1. 健康检查

```bash
curl http://localhost:8000/api/v1/health
```

**响应示例：**

```json
{
  "status": "healthy",
  "api": "ok",
  "comfyui": "connected",
  "knowledge_base": "loaded",
  "version": "0.1.0"
}
```

### 2. 提交生成任务

```bash
curl -X POST http://localhost:8000/api/v1/generate \
  -H "Content-Type: application/json" \
  -d '{
    "platform": "amazon",
    "product_desc": "红色陶瓷咖啡杯，容量350ml，简约北欧风格，哑光釉面",
    "max_retries": 3
  }'
```

**响应示例（202 Accepted）：**

```json
{
  "task_id": "a1b2c3d4e5f6",
  "status": "pending",
  "message": "任务已提交，正在处理中 | platform=amazon | product=红色陶瓷咖啡杯..."
}
```

### 3. 查询任务状态

```bash
curl http://localhost:8000/api/v1/task/a1b2c3d4e5f6
```

**响应示例（进行中）：**

```json
{
  "task_id": "a1b2c3d4e5f6",
  "status": "generating",
  "progress": 40,
  "current_step": "正在生成商品图片",
  "platform": "amazon",
  "product": "红色陶瓷咖啡杯",
  "images": null,
  "compliance_stats": null,
  "total_retries": 0,
  "error": null
}
```

**响应示例（已完成）：**

```json
{
  "task_id": "a1b2c3d4e5f6",
  "status": "completed",
  "progress": 100,
  "current_step": "管道已完成",
  "platform": "amazon",
  "product": "红色陶瓷咖啡杯",
  "images": [
    {
      "type": "white_bg_main",
      "type_label": "白底主图",
      "path": "output/a1b2/white_bg_main_generated_xxx.png",
      "compliant": true,
      "retry_count": 0,
      "audit_result": { "overall_score": 95, "is_compliant": true }
    }
  ],
  "compliance_stats": {
    "total": 4,
    "compliant": 3,
    "non_compliant": 1,
    "compliance_rate": "3/4",
    "average_score": 87.5
  },
  "total_retries": 1,
  "error": null
}
```

### 4. 单独审核图片

```bash
curl -X POST http://localhost:8000/api/v1/check \
  -H "Content-Type: application/json" \
  -d '{
    "image_url": "output/some_image.png",
    "platform": "amazon",
    "image_type": "white_bg_main"
  }'
```

**响应示例：**

```json
{
  "platform": "amazon",
  "image_type": "white_bg_main",
  "is_compliant": false,
  "confidence": 0.92,
  "overall_score": 65,
  "violations": [
    {
      "rule": "背景必须纯白",
      "severity": "critical",
      "description": "背景存在灰色渐变",
      "suggestion": "将背景替换为纯白 RGB(255,255,255)"
    }
  ],
  "summary": "主图背景不满足纯白要求，需调整",
  "cot_analysis": {
    "step1_content_description": "图片展示一个红色陶瓷咖啡杯...",
    "step2_rule_comparison": ["背景要求 — 不通过 — 存在灰色渐变", "..."],
    "step3_compliance_decision": "背景不满足纯白要求，判定不合规",
    "step4_fix_suggestions": ["背景替换为纯白RGB(255,255,255)"]
  }
}
```

### 5. 获取平台规则

```bash
# 获取 Amazon 规则
curl http://localhost:8000/api/v1/rules/amazon

# 获取淘宝规则
curl http://localhost:8000/api/v1/rules/taobao
```

### 6. 获取任务列表

```bash
# 所有任务
curl http://localhost:8000/api/v1/tasks

# 按状态筛选
curl "http://localhost:8000/api/v1/tasks?status=completed&limit=10"
```

---

## 项目结构

```
MeituEcomAgent/
├── app/                              # 应用主目录
│   ├── __init__.py
│   ├── main.py                       # FastAPI 入口：路由、中间件、生命周期
│   ├── config.py                     # 配置管理：dotenv 加载所有环境变量
│   ├── agents/                       # 智能体模块
│   │   ├── __init__.py
│   │   ├── orchestrator.py           # 总调度器："生成→审核→修复→重绘"闭环
│   │   ├── rule_parser.py            # 规则解析Agent：平台规则→结构化Prompt
│   │   ├── image_generator.py        # 生图调度Agent：Prompt→ComfyUI→图片
│   │   └── compliance_checker.py     # 合规审核Agent：GPT-4o Vision审核
│   ├── models/                       # 数据模型
│   │   ├── __init__.py
│   │   └── schemas.py               # Pydantic模型：请求/响应/枚举定义
│   ├── services/                     # 服务层
│   │   ├── __init__.py
│   │   ├── rag_service.py           # RAG知识库：llama-index + ChromaDB
│   │   └── comfyui_service.py       # ComfyUI客户端：aiohttp + WebSocket
│   └── utils/                        # 工具模块
│       ├── __init__.py
│       ├── file_utils.py            # 文件工具：目录创建/图片保存/报告/归档/清理
│       └── image_utils.py           # 图片工具：验证/缩放/Base64/压缩
├── knowledge_base/                   # 规则Markdown文件
│   ├── amazon_rules.md              # 亚马逊平台图片合规规则
│   ├── aliexpress_rules.md          # 速卖通平台图片合规规则
│   ├── taobao_rules.md              # 淘宝/天猫平台图片合规规则
│   └── shopee_rules.md              # Shopee平台图片合规规则
├── knowledge_base_index/             # RAG向量索引持久化（自动生成）
├── workflows/                        # ComfyUI工作流JSON文件
├── output/                           # 生成结果输出目录
├── .env                              # 环境变量（不提交Git）
├── .env.example                      # 环境变量模板
├── .gitignore                        # Git忽略规则
├── Dockerfile                        # Docker镜像构建（多阶段）
├── docker-compose.yml                # Docker编排：API + ChromaDB
├── requirements.txt                  # Python依赖清单
└── README.md                         # 项目文档
```

---

## 扩展指南

### 如何添加新平台规则

1. **创建规则文件**：在 `knowledge_base/` 下创建 `{platform}_rules.md`，使用与现有文件相同的结构化格式

2. **注册平台**：在 `app/agents/rule_parser.py` 的 `PLATFORM_DISPLAY_MAP` 中添加映射：

```python
PLATFORM_DISPLAY_MAP = {
    "amazon": "Amazon（亚马逊）",
    "aliexpress": "AliExpress（速卖通）",
    # 新增 ↓
    "lazada": "Lazada（来赞达）",
}
```

3. **注册枚举**：在 `app/models/schemas.py` 的 `PlatformEnum` 中添加：

```python
class PlatformEnum(str, Enum):
    AMAZON = "amazon"
    LAZADA = "lazada"  # 新增
```

4. **重建索引**：启动项目后 RAG 知识库会自动重建索引；或调用：

```python
from app.services.rag_service import RAGService
rag = RAGService()
rag.build_index()
```

### 如何自定义 ComfyUI 工作流

工作流 JSON 文件放在 `workflows/` 目录下，命名遵循映射关系（在 `app/agents/image_generator.py` 中配置）：

```python
IMAGE_TYPE_WORKFLOW_MAP = {
    "white_bg_main": "product_white_bg.json",     # 白底主图
    "scene_lifestyle": "product_scene.json",       # 场景生活图
    "detail_closeup": "product_detail.json",       # 细节特写图
    "scale_comparison": "product_scale.json",      # 尺寸对比图
    "_default": "product_default.json",            # 默认回退
}
```

**工作流要求：**

- 必须包含至少一个 `CLIPTextEncode` 节点（系统自动注入 positive prompt）
- 推荐包含两个 `CLIPTextEncode` 节点（第二个注入 negative prompt）
- 包含 `KSampler` 节点（系统自动随机化 seed）
- 包含 `EmptyLatentImage` 节点（系统自动注入分辨率）

**从 ComfyUI 导出工作流：**

1. 在 ComfyUI 界面中设计好工作流
2. 点击「Save (API Format)」导出 JSON
3. 将 JSON 文件放入 `workflows/` 目录

### 如何替换大模型

**替换为国内兼容模型（如通义千问、DeepSeek）：**

编辑 `.env`：

```bash
# 以硅基流动 SiliconFlow 为例
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
OPENAI_API_KEY=sk-your-siliconflow-key
CHAT_MODEL=Qwen/Qwen2.5-VL-72B-Instruct   # 需支持 Vision
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5    # 替换 embedding 模型
```

**注意事项：**

- GPT-4o 替换模型必须支持多模态（Vision），否则合规审核无法工作
- embedding 模型替换后需在 `rag_service.py` 中调整 embedding 维度

---

## 常见问题 FAQ

### Q: ComfyUI 连接失败怎么办？

**A:** 确保 ComfyUI 已启动并监听在配置的地址。验证方式：

```bash
curl http://127.0.0.1:8188/system_stats
```

如果 ComfyUI 在另一台机器上，修改 `.env` 中的 `COMFYUI_SERVER_ADDRESS`。

### Q: 首次启动时 RAG 知识库构建很慢？

**A:** 首次构建会调用 OpenAI embedding API 为所有规则文件生成向量索引。后续启动会自动加载已有索引，无需重建。如果 embedding API 较慢，可考虑使用本地 embedding 模型。

### Q: 如何查看生成任务的详细日志？

**A:** 本地启动时日志输出到控制台。Docker 启动时：

```bash
docker-compose logs -f api
```

任务结果中的 `pipeline_log` 字段记录了每一步的执行日志。

### Q: 生成的图片在哪里？

**A:** 本地启动在 `output/` 目录下，以 `{task_id}/` 子目录组织。Docker 启动时挂载到 `output_data` named volume。

### Q: 审核结果不准确怎么办？

**A:** 
- 确认规则文件内容全面准确
- 可以调整 `compliance_checker.py` 中的 `temperature` 参数（默认 0.2）
- 确保 GPT-4o 使用 high detail 模式（已默认启用）

### Q: 如何批量处理多个商品？

**A:** 使用 API 并发提交多个生成任务：

```bash
for product in "红色咖啡杯" "蓝色水壶" "白色盘子"; do
  curl -X POST http://localhost:8000/api/v1/generate \
    -H "Content-Type: application/json" \
    -d "{\"platform\":\"amazon\",\"product_desc\":\"$product\"}" &
done
```

然后通过 `/api/v1/tasks` 查询所有任务状态。

### Q: 支持哪些平台？

**A:** 目前支持 Amazon（亚马逊）、AliExpress（速卖通）、淘宝/天猫、Shopee（虾皮）四大平台。添加新平台请参考上方「扩展指南」。

---

## 许可证

MIT License
