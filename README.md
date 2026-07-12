# Dianshna Image (MeituEcomAgent)

> 基于多智能体协作的跨平台电商商品图片自动生成与合规审核系统

[![Python](https://img.shields.io/badge/Python-3.11-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![ComfyUI](https://img.shields.io/badge/ComfyUI-0.27+-orange.svg)](https://github.com/comfyanonymous/ComfyUI)
[![Docker](https://img.shields.io/badge/Docker-Supported-2496ED.svg)](https://www.docker.com/)

## 功能

输入**商品原图 + 平台 + 卖点文案**，全自动输出：

- **白底主图** — 商品纯白背景正面展示
- **场景营销图** — 产品合成到真实生活场景（抠图+合成）
- **细节特写图** — 关键细节超大特写
- **尺寸对比图** — 专业标注长宽高（cm）
- **合规检测报告** — JSON 结构化报告（违规项、修改建议、CoT 分析）
- **自动修复重绘** — 不合规图片自动修复 prompt 并重绘（最多 3 轮）
- **结构化归档** — `output/{platform}/{product}_{timestamp}/`

## 架构

```
用户输入 (平台 + 商品描述 + 原图 + 卖点)
  → RuleParserAgent (RAG + LLM → 结构化 prompts)
  → ImageGeneratorAgent (ComfyUI → 4张商品图)
  → ComplianceCheckerAgent (Vision API → 合规审核)
    ├─ 全部合规 → 归档 + 报告
    └─ 有违规 → 修复 Prompt → 重绘 → 重新审核 (最多 3 轮)
```

## 快速开始

### 环境要求

- Python 3.11+
- ComfyUI（本地或远程，默认 `127.0.0.1:8188`）
- LLM API（支持阿里云 DashScope / OpenAI 兼容接口）

### 1. 克隆仓库

```bash
git clone https://github.com/zsj00/Dianshna_image.git
cd Dianshna_image/MeituEcomAgent
```

### 2. 安装依赖

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

### 3. 配置环境

```bash
cp .env.example .env
# 编辑 .env，填入你的 API Key 和 ComfyUI 地址
```

### 4. 启动 ComfyUI

```bash
# 在 ComfyUI 目录下
python main.py --port 8188 --lowvram
```

### 5. 启动服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

访问 http://localhost:8000/ui 使用 Web 界面。

### Docker 部署

```bash
docker compose up -d
# 访问 http://localhost:8002
```

## 项目结构

```
MeituEcomAgent/
├── app/
│   ├── agents/              # 智能体
│   │   ├── orchestrator.py      # 总调度器
│   │   ├── rule_parser.py       # 规则解析（RAG + LLM）
│   │   ├── image_generator.py   # 图像生成（ComfyUI）
│   │   └── compliance_checker.py # 合规审核（Vision API）
│   ├── models/              # Pydantic schemas
│   ├── services/            # 基础设施（ComfyUI, RAG）
│   ├── utils/               # 工具函数（图像处理、合成、文件管理）
│   ├── static/              # Web UI
│   ├── config.py            # 配置管理
│   └── main.py              # FastAPI 入口
├── workflows/               # ComfyUI 工作流 JSON
├── knowledge_base/          # 平台规则 Markdown
├── tests/                   # 单元测试
├── output/                  # 生成结果（gitignore）
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/pipeline/ecommerce-assets` | POST | 提交完整管线任务（multipart） |
| `/api/v1/generate` | POST | 提交生成任务（JSON） |
| `/api/v1/task/{task_id}` | GET | 查询任务状态和结果 |
| `/api/v1/health` | GET | 健康检查 |
| `/api/v1/rules/{platform}` | GET | 查询平台规则 |
| `/ui` | GET | Web 界面 |
| `/output/{task_id}/*` | GET | 浏览生成结果 |

## 支持平台

| 平台 | 知识库文件 |
|------|-----------|
| 淘宝/天猫 | `knowledge_base/taobao_rules.md` |
| Amazon | `knowledge_base/amazon_rules.md` |
| AliExpress | `knowledge_base/aliexpress_rules.md` |
| Shopee | `knowledge_base/shopee_rules.md` |

## 添加新平台

1. `knowledge_base/` 下创建 `{platform}_rules.md`
2. `app/models/schemas.py` 的 `PlatformEnum` 添加枚举
3. `app/agents/rule_parser.py` 的 `PLATFORM_DISPLAY_MAP` 添加映射
4. `app/services/rag_service.py` 的 `platforms` 添加映射
5. 重启应用（RAG 自动重建索引）

## 关键技术

- **img2img + txt2img 混合**：主图用 img2img 保证产品一致，场景图用 txt2img 生成背景
- **抠图+合成**：从白底图提取产品，合成到场景背景上
- **RAG 知识库**：llama-index + ChromaDB，持久化向量索引
- **ComfyUI 工作流**：LCM-LoRA 加速（2GB VRAM 可用）
- **Vision API 审核**：CoT 链式推理，结构化违规检测

## License

MIT
