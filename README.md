# MeituEcomAgent (Dianshna Image)

> Multi-Agent E-Commerce Product Image Generation & Compliance Checking System
> 基于多智能体协作的跨平台商品图片自动生成与合规审核系统

## Features / 功能

- **规则解析** — 自动解析淘宝/天猫、Amazon、AliExpress、Shopee 四大平台的图片合规规则
- **智能生图** — 调用 ComfyUI 一次生成4张商品套图：白底主图、场景生活图、细节特写图、尺寸标注图
- **合规审核** — Vision LLM + Chain of Thought 逐条对照平台规则审核
- **自动修复** — 不合规图片自动生成修复 prompt → 重绘 → 重审闭环（最多3轮）
- **产品合成** — 白底图提取产品 + txt2img 场景背景 = 真实场景图（composite_product_to_scene）
- **知识库检索** — llama-index + ChromaDB RAG，支持按平台精确查询规则
- **REST API** — FastAPI 提供完整 REST API + Web UI
- **Docker 部署** — Dockerfile + docker-compose 一键编排

## Architecture / 技术架构

```
User Input (platform + product + image + selling points)
     |
     v
AgentOrchestrator (generate -> audit -> fix -> redraw loop)
     |
     |-- RuleParserAgent ------ RAG + LLM ----- Structured Prompts
     |-- ImageGeneratorAgent -- ComfyUI ------ 4 product images
     |       +-- composite_product_to_scene (compositing)
     +-- ComplianceCheckerAgent -- Vision LLM -- Audit results
              |
              |-- All compliant -> Archive + Report
              +-- Has violations -> Fix Prompt -> Redraw -> Re-audit
```

## Quick Start / 快速开始

### Prerequisites

- Python 3.11+
- ComfyUI (start separately, default 127.0.0.1:8188)
- GPU: 4GB+ VRAM recommended (2GB MX450 needs LCM-LoRA)
- LLM API: DashScope qwen-plus / qwen-vl-max (OpenAI-compatible)

### 1. Install

```bash
cd MeituEcomAgent
pip install -r requirements.txt
```

### 2. Configure

Edit `.env`:
```bash
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_API_KEY=sk-your-key-here
CHAT_MODEL=qwen-plus
VISION_MODEL=qwen-vl-max
COMFYUI_SERVER_ADDRESS=127.0.0.1:8188
```

### 3. Start ComfyUI

```bash
cd D:\ComfyUI\ComfyUI
venv\Scripts\python main.py --lowvram --port 8188
```

### 4. Start Service

```bash
cd MeituEcomAgent
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```



### Docker

```bash
docker compose up -d

```

## Pipeline / 核心管线

```
1. Upload image -> AI bg-removal + white bg -> Upload to ComfyUI
2. RuleParserAgent: RAG rules + LLM -> 4 structured prompts
3. ImageGeneratorAgent: Load workflow -> Inject prompts -> 4 images
4. ComplianceCheckerAgent: Vision LLM + CoT -> compliance audit
5. Auto-retry: Non-compliant -> Fix prompt -> Redraw -> Re-audit (3x)
6. Archive: output/{platform}/{product}_{timestamp}/ + report.json
```

## Image Types / 图片类型

| Type | Description | Post-processing |
|------|-------------|-----------------|
| white_bg_main | Pure white bg, product centered | White fill + selling points overlay |
| scene_lifestyle | Product in real scene | **Compositing**: extract product + txt2img bg |
| detail_closeup | Macro detail close-up | 40% center crop |
| scale_comparison | Dimension labels | W/H/D cm annotation lines |

## API Endpoints / 接口

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/v1/health | Health check |
| POST | /api/v1/generate | Submit task (JSON) |
| POST | /api/v1/pipeline/ecommerce-assets | Submit task (multipart with image) |
| GET | /api/v1/task/{task_id} | Query task status |
| GET | /api/v1/tasks | List all tasks |
| GET | /api/v1/rules/{platform} | Get platform rules |

### Example

```bash
curl -X POST http://localhost:8000/api/v1/pipeline/ecommerce-assets \
  -F "platform=taobao" \
  -F "product_desc=30ml ceramic foundation cream" \
  -F "selling_points=food-grade ceramic|matte finish|24h moisture" \
  -F "product_image=@product.png"

# Query result
curl http://localhost:8000/api/v1/task/{task_id}
```

## Project Structure / 项目结构

```
MeituEcomAgent/
├── app/
│   ├── agents/          # orchestrator, rule_parser, image_generator, compliance_checker
│   ├── models/          # Pydantic schemas
│   ├── services/        # comfyui, rag
│   ├── utils/           # file_utils, image_utils, image_processor
│   ├── static/          # Web UI (index.html)
│   ├── config.py        # Settings
│   └── main.py          # FastAPI entry
├── workflows/           # ComfyUI workflow JSONs
├── knowledge_base/      # Platform rules (.md)
├── tests/               # Unit tests
├── logs/                # App logs
├── output/              # Generated images + reports
├── docker-compose.yml
├── Dockerfile
├── start.bat
└── requirements.txt
```

## Adding New Platform / 添加新平台

1. Create `knowledge_base/{platform}_rules.md`
2. Add enum in `app/models/schemas.py` PlatformEnum
3. Add mapping in `app/agents/rule_parser.py` PLATFORM_DISPLAY_MAP
4. Restart service, RAG auto-rebuilds index

## Performance / 性能 (MX450 2GB)

| Metric | Value |
|--------|-------|
| Per-image generation | ~2 min |
| Full 4-image pipeline | ~12-15 min |
| ComfyUI Model | Deliberate_v2 + LCM-LoRA |
| Resolution | 512x512 scene / 800x800 main |

## Tech Stack / 技术栈

- **Backend**: Python 3.11, FastAPI, uvicorn
- **AI/ML**: ComfyUI (Stable Diffusion), LCM-LoRA
- **LLM**: DashScope qwen-plus / qwen-vl-max
- **RAG**: llama-index, ChromaDB, text-embedding-v3
- **Image**: Pillow
- **Deploy**: Docker, docker-compose

## License / 许可

