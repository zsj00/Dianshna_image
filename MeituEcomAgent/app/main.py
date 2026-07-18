"""
FastAPI 主应用入口

提供 REST API 端点:
- POST /api/v1/generate      — 提交生成任务
- GET  /api/v1/task/{task_id} — 查询任务状态
- POST /api/v1/check         — 单独图片合规审核
- GET  /api/v1/rules/{platform} — 获取平台规则
- GET  /api/v1/health        — 健康检查
- GET  /api/v1/tasks         — 获取所有任务列表
"""
import time
import asyncio
import logging
import logging.handlers
import traceback
import os
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.models.schemas import (
    PlatformEnum,
    GenerateRequest,
    GenerateResponse,
    ComplianceCheckRequest,
    ComplianceCheckResponse,
    TaskStatusResponse,
    TaskStatusEnum,
    TaskListItem,
    TaskListResponse,
    HealthCheckResponse,
    RuleInfo,
    ErrorResponse,
    PipelineFormRequest,
    PipelineResponse,
)
from app.agents.orchestrator import AgentOrchestrator, PipelineStatus
from app.agents.compliance_checker import ComplianceCheckerAgent, ComplianceCheckerError
from app.services.rag_service import RAGService
from app.services.comfyui_service import ComfyUIClient
from app.services.image_provider import CloudImageProvider

# 配置日志
log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
log_datefmt = "%Y-%m-%d %H:%M:%S"

handlers = [logging.StreamHandler()]

# 配置文件日志持久化
if settings.LOG_FILE:
    log_dir = os.path.dirname(settings.LOG_FILE)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        settings.LOG_FILE,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(log_format, datefmt=log_datefmt))
    handlers.append(file_handler)

logging.basicConfig(
    level=log_level,
    format=log_format,
    datefmt=log_datefmt,
    handlers=handlers,
)
logger = logging.getLogger(__name__)

# 全局单例
_orchestrator: Optional[AgentOrchestrator] = None
_rag_service: Optional[RAGService] = None
_comfyui_client: Optional[ComfyUIClient] = None
_comfyui_available: Optional[bool] = None  # 缓存 ComfyUI 连接状态


def get_orchestrator() -> AgentOrchestrator:
    """获取全局调度器单例"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgentOrchestrator()
    return _orchestrator


def get_rag_service() -> RAGService:
    """获取全局RAG服务单例"""
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service


# ==================== 进度映射 ====================

STATUS_PROGRESS_MAP = {
    PipelineStatus.PENDING: 5,
    PipelineStatus.PARSING: 15,
    PipelineStatus.GENERATING: 40,
    PipelineStatus.AUDITING: 65,
    PipelineStatus.RETRYING: 80,
    PipelineStatus.ARCHIVING: 92,
    PipelineStatus.COMPLETED: 100,
    PipelineStatus.FAILED: 100,
}

STATUS_STEP_MAP = {
    PipelineStatus.PENDING: "任务已排队",
    PipelineStatus.PARSING: "正在解析平台规则和商品描述",
    PipelineStatus.GENERATING: "正在生成商品图片",
    PipelineStatus.AUDITING: "正在审核图片合规性",
    PipelineStatus.RETRYING: "不合规图片修复重绘中",
    PipelineStatus.ARCHIVING: "正在归档图片文件",
    PipelineStatus.COMPLETED: "管道已完成",
    PipelineStatus.FAILED: "管道执行失败",
}


# ==================== 应用生命周期 ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭时的生命周期管理"""
    # 启动时：初始化 RAG 知识库
    logger.info("=" * 50)
    logger.info("MeituEcomAgent 正在启动...")
    logger.info("=" * 50)

    try:
        rag = get_rag_service()
        logger.info("正在初始化 RAG 知识库索引...")
        index = rag.get_or_create_index()
        logger.info("RAG 知识库索引初始化成功 ✓")
    except Exception as e:
        logger.warning("RAG 知识库初始化失败（将按需加载）: %s", str(e))

    # 预热 orchestrator
    get_orchestrator()
    logger.info("AgentOrchestrator 已就绪 ✓")
    logger.info("MeituEcomAgent 启动完成")

    yield  # ← 应用运行期间

    # 关闭时：清理资源
    logger.info("MeituEcomAgent 正在关闭...")
    if _orchestrator:
        await _orchestrator.close()
    logger.info("MeituEcomAgent 已关闭")


# ==================== 创建应用 ====================

app = FastAPI(
    title="MeituEcomAgent",
    description="美图电商智能生图代理服务 — 多平台商品图片自动生成与合规审核",
    version="0.3.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ==================== 中间件 ====================

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 请求日志中间件
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """记录每个请求的方法、路径和耗时"""
    start_time = time.time()
    method = request.method
    url = str(request.url)

    # 记录请求开始
    logger.info("→ %s %s", method, url)

    try:
        response = await call_next(request)
        elapsed = (time.time() - start_time) * 1000
        logger.info(
            "← %s %s | %d | %.0fms",
            method,
            url,
            response.status_code,
            elapsed,
        )
        response.headers["X-Process-Time"] = f"{elapsed:.0f}ms"
        return response
    except Exception as e:
        elapsed = (time.time() - start_time) * 1000
        logger.error(
            "← %s %s | 500 | %.0fms | error=%s",
            method,
            url,
            elapsed,
            str(e),
        )
        raise


# ==================== 异常处理器 ====================

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP 异常处理"""
    logger.warning("HTTP异常 | %s %s | %d: %s", request.method, request.url.path, exc.status_code, exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error="HTTPException",
            message=str(exc.detail),
            detail=str(exc.detail),
            timestamp=datetime.now().isoformat(),
        ).model_dump(),
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """值错误处理（如 Pydantic 验证失败）"""
    logger.warning("参数验证失败 | %s %s: %s", request.method, request.url.path, str(exc))
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error="ValidationError",
            message=str(exc),
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """全局异常兜底处理"""
    logger.exception("未捕获异常 | %s %s", request.method, request.url.path)
    trace = traceback.format_exc()
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error=type(exc).__name__,
            message="服务器内部错误",
            detail=trace[:1000],
            timestamp=datetime.now().isoformat(),
        ).model_dump(),
    )


# ==================== API 端点 ====================

# ---- 健康检查 ----

@app.get(
    "/api/v1/health",
    response_model=HealthCheckResponse,
    summary="系统健康检查",
    description="检查 API 服务、ComfyUI 后端、知识库的连接状态",
    tags=["系统"],
)
async def health_check():
    """
    健康检查接口，返回各组件的运行状态：
    - API 服务状态
    - ComfyUI 后端连接状态
    - RAG 知识库状态
    """
    global _comfyui_client, _comfyui_available

    # 检查图片生成 Provider。云端模式不要求本地 ComfyUI 在线。
    image_provider_status = "unknown"
    comfyui_status = "unknown"
    if settings.is_cloud_image_provider:
        cloud_provider = CloudImageProvider()
        try:
            image_provider_status = "cloud:configured" if await cloud_provider.check_connection() else "cloud:missing_config"
        finally:
            await cloud_provider.close()
        comfyui_status = "optional"
    elif settings.is_comfyui_image_provider:
        image_provider_status = "comfyui"
        if _comfyui_client is None:
            _comfyui_client = ComfyUIClient()
        if _comfyui_available is None:
            try:
                _comfyui_available = await _comfyui_client.check_connection()
            except Exception:
                _comfyui_available = False
        comfyui_status = "connected" if _comfyui_available else "disconnected"
        if comfyui_status == "disconnected":
            image_provider_status = "comfyui:disconnected"
    else:
        image_provider_status = f"unsupported:{settings.IMAGE_PROVIDER}"

    # 检查知识库
    kb_status = "unknown"
    try:
        rag = get_rag_service()
        # 尝试加载已有索引
        index = rag.load_index()
        kb_status = "loaded" if index else "not_built"
    except Exception as e:
        kb_status = f"error: {str(e)[:50]}"

    # 综合状态
    if "error" in kb_status:
        overall = "degraded"
    elif image_provider_status.endswith("missing_config") or image_provider_status.startswith("unsupported"):
        overall = "degraded"
    elif settings.is_comfyui_image_provider and comfyui_status == "disconnected":
        overall = "degraded"
    elif kb_status == "not_built":
        overall = "degraded"
    else:
        overall = "healthy"

    return HealthCheckResponse(
        status=overall,
        api="ok",
        image_provider=image_provider_status,
        comfyui=comfyui_status,
        knowledge_base=kb_status,
        version=app.version,
    )


# ---- 提交生成任务 ----

@app.post(
    "/api/v1/generate",
    response_model=GenerateResponse,
    status_code=202,
    summary="提交商品图生成任务",
    description="""
提交一个新的商品图片生成任务，系统将在后台依次完成：
1. 解析平台规则，生成结构化 prompt
2. 调用 ComfyUI 生成4张商品图片（白底主图、场景图、细节图、尺寸图）
3. 自动审核图片合规性
4. 不合规图片自动修复重绘（最多重试指定次数）
5. 归档生成结果，生成审核报告

该接口为异步接口，提交后立即返回 task_id，可通过 `/api/v1/task/{task_id}` 轮询任务状态。
    """,
    tags=["生成"],
)
async def generate(
    request: GenerateRequest,
    background_tasks: BackgroundTasks,
):
    """
    提交生成任务

    - **platform**: 目标电商平台 (amazon/aliexpress/taobao/shopee)
    - **product_desc**: 商品描述文本
    - **reference_image_url**: 参考图片URL（可选）
    - **max_retries**: 不合规图片最大重试次数（默认3）
    """
    try:
        orchestrator = get_orchestrator()

        # 预创建任务（解决竞态条件：background_tasks 在响应返回后才执行）
        import uuid
        task_id = uuid.uuid4().hex[:12]
        orchestrator._init_task(
            task_id=task_id,
            platform=request.platform.value,
            product_desc=request.product_desc,
        )

        # 创建捕获任务结果的回调
        async def run_pipeline_background():
            try:
                logger.info(
                    "后台任务开始 | platform=%s | product=%s",
                    request.platform,
                    request.product_desc[:30],
                )
                await orchestrator.run_pipeline(
                    platform=request.platform.value,
                    product_desc=request.product_desc,
                    reference_image=request.reference_image_url,
                    max_retries=request.max_retries,
                    task_id=task_id,
                )
            except Exception as e:
                logger.exception("后台任务异常: %s", str(e))

        background_tasks.add_task(run_pipeline_background)

        return GenerateResponse(
            task_id=task_id,
            status="pending",
            message=f"任务已提交，正在处理中 | platform={request.platform.value} | product={request.product_desc[:20]}...",
        )

    except Exception as e:
        logger.exception("提交任务失败")
        raise HTTPException(status_code=500, detail=f"提交任务失败: {str(e)}")


# ---- 查询任务状态 ----

@app.get(
    "/api/v1/task/{task_id}",
    response_model=TaskStatusResponse,
    summary="查询任务状态",
    description="根据 task_id 查询生成任务的当前状态和结果",
    tags=["生成"],
)
async def get_task_status(task_id: str):
    """
    查询任务状态

    返回任务的当前进度、生成的图片列表、合规审核结果等信息。
    任务状态变化: pending → parsing → generating → auditing → completed/failed
    """
    orchestrator = get_orchestrator()

    try:
        task_info = await orchestrator.get_task_status(task_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询任务状态失败: {str(e)}")

    if not task_info.get("exists"):
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    # 获取详细任务数据
    task_data = orchestrator._tasks.get(task_id, {})

    status_str = task_info["status"]
    try:
        pipeline_status = PipelineStatus(status_str) if status_str != "unknown" else PipelineStatus.PENDING
    except ValueError:
        pipeline_status = PipelineStatus.PENDING

    progress = STATUS_PROGRESS_MAP.get(pipeline_status, 0)
    current_step = STATUS_STEP_MAP.get(pipeline_status, "")

    # 构建图片列表
    images = None
    report = task_data.get("report")
    if report:
        raw_images = report.get("images", [])
        if raw_images:
            from app.models.schemas import TaskImageInfo, ComplianceStats
            images = []
            for img in raw_images:
                images.append({
                    "type": img.get("type", ""),
                    "type_label": img.get("type_label", ""),
                    "path": img.get("path", ""),
                    "compliant": img.get("compliant", False),
                    "retry_count": img.get("retry_count", 0),
                    "audit_result": img.get("audit_result"),
                })

    compliance_stats = None
    if report:
        stats = report.get("compliance_stats")
        if stats:
            compliance_stats = {
                "total": stats.get("total", 0),
                "compliant": stats.get("compliant", 0),
                "non_compliant": stats.get("non_compliant", 0),
                "compliance_rate": stats.get("compliance_rate", "0/0"),
                "average_score": stats.get("average_score", 0.0),
            }

    return TaskStatusResponse(
        task_id=task_id,
        status=TaskStatusEnum(status_str) if status_str != "unknown" else TaskStatusEnum.PENDING,
        progress=progress,
        current_step=current_step,
        platform=task_data.get("platform"),
        product=task_data.get("product"),
        images=images,
        compliance_stats=compliance_stats,
        total_retries=report.get("total_retries", 0) if report else 0,
        report=report,
        error=task_data.get("error"),
        created_at=task_data.get("created_at"),
    )


# ---- 单独审核 ----

@app.post(
    "/api/v1/check",
    response_model=ComplianceCheckResponse,
    summary="单独图片合规审核",
    description="对单张图片进行平台合规性审核，使用 GPT-4o 多模态能力 + Chain of Thought 思维链分析",
    tags=["审核"],
)
async def check_compliance(request: ComplianceCheckRequest):
    """
    单独审核一张图片的合规性

    - **image_url**: 图片文件路径（本地路径）
    - **platform**: 目标平台 (amazon/aliexpress/taobao/shopee)
    - **image_type**: 图片类型（white_bg_main/scene_lifestyle/detail_closeup/scale_comparison）
    """
    from pathlib import Path

    # 验证图片路径
    image_path = request.image_url
    if not Path(image_path).exists():
        # 尝试从 output 目录查找
        base_dir = Path(__file__).resolve().parent.parent
        resolved = base_dir / image_path
        if resolved.exists():
            image_path = str(resolved)
        else:
            raise HTTPException(status_code=404, detail=f"图片文件不存在: {request.image_url}")

    try:
        checker = ComplianceCheckerAgent()
        result = await checker.check_image(
            image_path=image_path,
            platform=request.platform.value,
            image_type=request.image_type.value,
        )
        await checker.close()

        return ComplianceCheckResponse(
            platform=result.get("platform", request.platform.value),
            image_type=result.get("image_type", ""),
            is_compliant=result.get("is_compliant", False),
            confidence=result.get("confidence", 0.0),
            overall_score=float(result.get("overall_score", 0)),
            violations=result.get("violations", []),
            summary=result.get("summary", ""),
            cot_analysis=result.get("cot_analysis"),
        )

    except ComplianceCheckerError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("审核失败")
        raise HTTPException(status_code=500, detail=f"审核服务异常: {str(e)}")


# ---- 平台规则查询 ----

@app.get(
    "/api/v1/rules/{platform}",
    response_model=RuleInfo,
    summary="获取平台规则",
    description="获取指定电商平台的完整图片合规规则",
    tags=["规则"],
)
async def get_platform_rules(platform: PlatformEnum):
    """
    获取平台规则

    - **platform**: 平台名称 (amazon/aliexpress/taobao/shopee)

    返回该平台的完整图片合规规则文本。
    """
    try:
        rag = get_rag_service()
        rules_text = rag.get_all_rules_for_platform(platform.value)

        if rules_text.startswith("不支持的平台") or rules_text.startswith("平台"):
            raise HTTPException(
                status_code=400,
                detail=f"获取 {platform.value} 规则失败: 规则数据不可用",
            )

        filename_map = {
            "amazon": "amazon_rules.md",
            "aliexpress": "aliexpress_rules.md",
            "taobao": "taobao_rules.md",
            "shopee": "shopee_rules.md",
        }

        return RuleInfo(
            platform=platform.value,
            platform_code=platform.value,
            filename=filename_map.get(platform.value, ""),
            rules_text=rules_text,
            size_chars=len(rules_text),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("获取规则失败")
        raise HTTPException(status_code=500, detail=f"获取规则失败: {str(e)}")


# ---- 获取所有任务列表 ----

@app.get(
    "/api/v1/tasks",
    response_model=TaskListResponse,
    summary="获取所有任务列表",
    description="获取所有已提交的生成任务列表，按创建时间倒序排列",
    tags=["生成"],
)
async def list_tasks(
    status: Optional[TaskStatusEnum] = None,
    limit: int = 50,
):
    """
    获取任务列表

    - **status**: 按状态筛选（可选）
    - **limit**: 最大返回数量（默认50）
    """
    orchestrator = get_orchestrator()
    tasks_data = orchestrator._tasks

    tasks = []
    for task_id, task_info in tasks_data.items():
        # 状态筛选
        task_status = task_info.get("status")
        if status:
            try:
                if task_status and task_status.value != status.value:
                    continue
            except AttributeError:
                continue

        tasks.append(TaskListItem(
            task_id=task_id,
            platform=task_info.get("platform"),
            product=task_info.get("product"),
            status=TaskStatusEnum(task_status.value) if task_status and hasattr(task_status, 'value') else TaskStatusEnum.PENDING,
            created_at=task_info.get("created_at"),
            error=task_info.get("error"),
        ))

    # 按创建时间倒序
    tasks.sort(key=lambda t: t.created_at or "", reverse=True)
    tasks = tasks[:limit]

    return TaskListResponse(
        total=len(tasks_data),
        tasks=tasks,
    )


# ==================== 静态文件 ====================

# 挂载 static 目录（前端页面）
static_dir = Path(__file__).resolve().parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# 挂载 output 目录（生成图片浏览）
output_dir_static = Path(__file__).resolve().parent.parent / settings.OUTPUT_DIR.lstrip("./")
output_dir_static.mkdir(parents=True, exist_ok=True)
app.mount("/output", StaticFiles(directory=str(output_dir_static)), name="output")

# 挂载 uploads 目录（上传原图浏览）
uploads_dir = output_dir_static / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

# ==================== 前端页面路由 ====================


@app.get("/ui", response_class=HTMLResponse, include_in_schema=False)
async def web_ui():
    """电商智能生图平台 Web 界面"""
    static_index = Path(__file__).resolve().parent / "static" / "index.html"
    if static_index.exists():
        return HTMLResponse(content=static_index.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})


# ---- 根路由 ----

@app.get(
    "/",
    summary="根路由",
    description="跳转到电商智能生图 Web 界面",
    tags=["系统"],
    include_in_schema=False,
)
async def root():
    """根路由 - 重定向到 Web UI"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/ui")


# ---- 电商全管道端点（Form表单 + 文件上传） ----

@app.post(
    "/api/v1/pipeline/ecommerce-assets",
    response_model=PipelineResponse,
    status_code=202,
    summary="[新版] 电商商品图全自动生成管道",
    description="""
**输入**：商品原图 + 目标平台 + 商品卖点文案

**全自动输出**：
- 平台合规白底主图（自动抠图 → 纯白底合成）
- 场景营销图
- 细节特写图
- 尺寸对比图
- 合规检测报告（违规项 + 修改建议）
- 自动归档结构化素材库

流程：上传原图 → AI抠图白底合成 → 上传到ComfyUI → 规则解析 → 4图并发生成 → 合规审核 → 自动修复重绘 → 归档 → 报告

该接口使用 **multipart/form-data** 表单方式接收商品原图文件和文本参数。
    """,
    tags=["管道"],
)
async def pipeline_ecommerce_assets(
    background_tasks: BackgroundTasks,
    product_image: UploadFile = File(..., description="商品原图（支持 PNG/JPEG/WebP）"),
    platform: str = Form(..., description="目标平台: amazon / taobao / aliexpress / shopee"),
    selling_points: str = Form(..., description="商品卖点文案"),
    max_retries: int = Form(3, ge=0, le=10, description="不合规图片最大重试次数"),
):
    """
    电商商品图全自动生成管道

    - **product_image**: 商品原图文件
    - **platform**: 目标电商平台
    - **selling_points**: 商品卖点文案
    - **max_retries**: 最大重试次数
    """
    from pathlib import Path
    from app.utils.image_processor import ImagePreprocessor
    from app.utils.file_utils import ensure_directory

    # 1. 验证平台
    valid_platforms = ["amazon", "aliexpress", "taobao", "shopee"]
    platform_lower = platform.lower().strip()
    if platform_lower not in valid_platforms:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的平台: '{platform}'。支持: {', '.join(valid_platforms)}",
        )

    # 2. 保存上传的商品原图
    base_dir = Path(__file__).resolve().parent.parent
    upload_dir = base_dir / settings.OUTPUT_DIR / "uploads"
    ensure_directory(str(upload_dir))

    # 0. 文件大小校验（最大20MB）
    MAX_UPLOAD_SIZE = 20 * 1024 * 1024
    image_bytes = await product_image.read()
    if len(image_bytes) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="图片文件过大，最大支持 20MB")

    # 生成唯一文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:18]
    ext = Path(product_image.filename).suffix if product_image.filename else ".png"
    original_filename = f"product_{timestamp}{ext}"
    original_path = upload_dir / original_filename

    with open(original_path, "wb") as f:
        f.write(image_bytes)

    logger.info(
        "商品原图已保存 | path=%s | size=%d bytes",
        original_path,
        len(image_bytes),
    )

    # 3. 可选本地抠图 + 白底合成（生产默认关闭，避免依赖本地模型）
    white_bg_path = original_path  # 默认使用原图
    _PROCESSING_TIMEOUT = 30  # 抠图最长等待30秒

    if settings.ENABLE_LOCAL_PREPROCESSING:
        try:
            logger.info("开始本地抠图 + 白底合成（超时=%ds）...", _PROCESSING_TIMEOUT)
            white_bg_bytes = await asyncio.wait_for(
                asyncio.to_thread(
                    ImagePreprocessor.make_white_background,
                    str(original_path),
                    (800, 800),
                ),
                timeout=_PROCESSING_TIMEOUT,
            )
            white_bg_filename = f"white_bg_{timestamp}.jpg"
            white_bg_path = upload_dir / white_bg_filename
            white_bg_path.write_bytes(white_bg_bytes)
            logger.info("白底图已生成 | path=%s", white_bg_path)
        except asyncio.TimeoutError:
            logger.warning("本地抠图超时（%ds），将使用原图继续", _PROCESSING_TIMEOUT)
        except Exception as e:
            logger.warning("本地抠图/白底合成失败（将使用原图继续）: %s", str(e))
    else:
        logger.info("本地抠图预处理未启用，使用原图继续 | ENABLE_LOCAL_PREPROCESSING=false")

    # 4. 先同步创建任务（解决竞态条件：background_tasks 在响应返回后才执行）
    orchestrator = get_orchestrator()
    import uuid
    task_id = uuid.uuid4().hex[:12]
    orchestrator._init_task(
        task_id=task_id,
        platform=platform_lower,
        product_desc=selling_points,
    )

    # 5. 提交后台任务
    async def run_pipeline_background():
        try:
            logger.info(
                "电商管道后台任务开始 | platform=%s | selling_points=%s",
                platform_lower,
                selling_points[:50],
            )
            await orchestrator.run_pipeline(
                platform=platform_lower,
                product_desc=selling_points,
                reference_image=str(white_bg_path),
                selling_points=selling_points,
                max_retries=max_retries,
                task_id=task_id,
            )
        except Exception as e:
            logger.exception("电商管道后台任务异常: %s", str(e))

    background_tasks.add_task(run_pipeline_background)

    return PipelineResponse(
        task_id=task_id,
        status="pending",
        message=(
            f"管道已启动 | platform={platform_lower} | "
            f"卖点={selling_points[:30]}... | "
            f"白底图={'已生成' if white_bg_path else '跳过'}"
        ),
        product_image_saved=str(white_bg_path),
    )
