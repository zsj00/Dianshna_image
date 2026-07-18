"""
Pydantic 数据模型定义
"""
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# ==================== 枚举 ====================

class PlatformEnum(str, Enum):
    """支持的电商平台"""

    AMAZON = "amazon"
    ALIEXPRESS = "aliexpress"
    TAOBAO = "taobao"
    SHOPEE = "shopee"


class TaskStatusEnum(str, Enum):
    """任务状态枚举"""

    PENDING = "pending"
    PARSING = "parsing"
    GENERATING = "generating"
    AUDITING = "auditing"
    RETRYING = "retrying"
    ARCHIVING = "archiving"
    COMPLETED = "completed"
    FAILED = "failed"


class ImageTypeEnum(str, Enum):
    """图片类型枚举"""

    WHITE_BG_MAIN = "white_bg_main"
    SCENE_LIFESTYLE = "scene_lifestyle"
    DETAIL_CLOSEUP = "detail_closeup"
    SCALE_COMPARISON = "scale_comparison"


# ==================== 请求模型 ====================

class GenerateRequest(BaseModel):
    """生成任务请求"""

    platform: PlatformEnum = Field(
        ...,
        description="目标电商平台",
        examples=["amazon"],
    )
    product_desc: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="商品描述文本",
        examples=["红色陶瓷咖啡杯，容量350ml，简约北欧风格，哑光釉面"],
    )
    reference_image_url: Optional[str] = Field(
        default=None,
        description="参考图片URL（可选）",
        examples=["https://example.com/reference.jpg"],
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="不合规图片最大重试次数",
    )

    @field_validator("product_desc")
    @classmethod
    def validate_product_desc(cls, v: str) -> str:
        """验证商品描述不为纯空白"""
        if not v.strip():
            raise ValueError("商品描述不能为空")
        return v.strip()


class ComplianceCheckRequest(BaseModel):
    """单独审核请求"""

    image_url: str = Field(
        ...,
        min_length=1,
        description="图片URL或本地路径",
        examples=["output/some_image.png"],
    )
    platform: PlatformEnum = Field(
        ...,
        description="目标平台",
    )
    image_type: ImageTypeEnum = Field(
        default=ImageTypeEnum.WHITE_BG_MAIN,
        description="图片类型",
    )


class RuleQueryRequest(BaseModel):
    """规则查询请求"""

    platform: PlatformEnum = Field(
        ...,
        description="目标平台",
    )
    query: Optional[str] = Field(
        default=None,
        description="可选的具体查询问题",
    )


# ==================== 响应模型 ====================

class GenerateResponse(BaseModel):
    """生成任务提交响应"""

    task_id: str = Field(..., description="任务ID")
    status: str = Field(default="pending", description="任务状态")
    message: str = Field(default="任务已提交，正在处理中", description="响应消息")

    model_config = {
        "json_schema_extra": {
            "example": {
                "task_id": "a1b2c3d4e5f6",
                "status": "pending",
                "message": "任务已提交，正在处理中",
            }
        }
    }


class TaskImageInfo(BaseModel):
    """任务中单张图片的信息"""

    type: ImageTypeEnum = Field(..., description="图片类型")
    type_label: str = Field(default="", description="图片类型中文标签")
    path: str = Field(default="", description="图片文件路径")
    compliant: bool = Field(default=False, description="是否合规")
    retry_count: int = Field(default=0, description="重试次数")
    audit_result: Optional[Dict[str, Any]] = Field(
        default=None, description="审核结果详情"
    )


class ComplianceStats(BaseModel):
    """合规统计"""

    total: int = Field(default=0, description="图片总数")
    compliant: int = Field(default=0, description="合规图片数")
    non_compliant: int = Field(default=0, description="不合规图片数")
    compliance_rate: str = Field(default="0/0", description="合规率")
    average_score: float = Field(default=0.0, description="平均评分")


class TaskStatusResponse(BaseModel):
    """任务状态响应"""

    task_id: str = Field(..., description="任务ID")
    status: TaskStatusEnum = Field(..., description="任务状态")
    progress: int = Field(default=0, ge=0, le=100, description="进度百分比")
    current_step: str = Field(default="", description="当前执行步骤")
    platform: Optional[str] = Field(default=None, description="目标平台")
    product: Optional[str] = Field(default=None, description="商品描述")
    images: Optional[List[TaskImageInfo]] = Field(
        default=None, description="生成图片列表"
    )
    compliance_stats: Optional[ComplianceStats] = Field(
        default=None, description="合规统计"
    )
    total_retries: int = Field(default=0, description="总重试次数")
    report: Optional[Dict[str, Any]] = Field(
        default=None, description="完整报告"
    )
    error: Optional[str] = Field(default=None, description="错误信息（如有）")
    created_at: Optional[str] = Field(default=None, description="创建时间")

    model_config = {
        "json_schema_extra": {
            "example": {
                "task_id": "a1b2c3d4e5f6",
                "status": "completed",
                "progress": 100,
                "current_step": "管道已完成",
                "platform": "amazon",
                "product": "红色陶瓷咖啡杯",
                "images": [],
                "compliance_stats": {
                    "total": 4,
                    "compliant": 3,
                    "non_compliant": 1,
                    "compliance_rate": "3/4",
                    "average_score": 87.5,
                },
                "total_retries": 1,
                "error": None,
            }
        }
    }


class ComplianceCheckResponse(BaseModel):
    """单独审核响应"""

    platform: str = Field(..., description="平台名称")
    image_type: str = Field(default="", description="图片类型")
    is_compliant: bool = Field(..., description="是否合规")
    confidence: float = Field(default=0.0, description="置信度")
    overall_score: float = Field(default=0.0, description="综合评分")
    violations: List[Dict[str, Any]] = Field(
        default_factory=list, description="违规项列表"
    )
    summary: str = Field(default="", description="审核总结")
    cot_analysis: Optional[Dict[str, Any]] = Field(
        default=None, description="思维链分析过程"
    )


class HealthCheckResponse(BaseModel):
    """健康检查响应"""

    status: str = Field(..., description="整体状态")
    api: str = Field(default="ok", description="API服务状态")
    image_provider: str = Field(default="unknown", description="图片生成Provider状态")
    comfyui: str = Field(default="unknown", description="ComfyUI连接状态")
    knowledge_base: str = Field(default="unknown", description="知识库状态")
    version: str = Field(default="0.3.0", description="版本号")


class RuleInfo(BaseModel):
    """平台规则信息"""

    platform: str = Field(..., description="平台名称")
    platform_code: str = Field(..., description="平台代码")
    filename: str = Field(default="", description="规则文件名")
    rules_text: str = Field(default="", description="规则文本内容")
    size_chars: int = Field(default=0, description="规则文本字符数")


class TaskListItem(BaseModel):
    """任务列表项"""

    task_id: str = Field(..., description="任务ID")
    platform: Optional[str] = Field(default=None, description="目标平台")
    product: Optional[str] = Field(default=None, description="商品描述")
    status: TaskStatusEnum = Field(..., description="任务状态")
    created_at: Optional[str] = Field(default=None, description="创建时间")
    error: Optional[str] = Field(default=None, description="错误信息")


class TaskListResponse(BaseModel):
    """任务列表响应"""

    total: int = Field(default=0, description="任务总数")
    tasks: List[TaskListItem] = Field(default_factory=list, description="任务列表")


# ==================== 错误响应模型 ====================

class ErrorResponse(BaseModel):
    """标准错误响应"""

    error: str = Field(..., description="错误类型")
    message: str = Field(..., description="错误详情")
    detail: Optional[str] = Field(default=None, description="详细信息")
    task_id: Optional[str] = Field(default=None, description="相关任务ID")
    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="错误时间",
    )


# ==================== 兼容旧模型（保留） ====================

class ComplianceResult(BaseModel):
    """合规审核结果模型（旧版兼容）"""

    is_compliant: bool = Field(..., description="是否合规")
    score: float = Field(default=0.0, description="合规评分")
    issues: List[str] = Field(default_factory=list, description="不合规问题列表")
    suggestions: List[str] = Field(default_factory=list, description="修改建议")


class ParsedRule(BaseModel):
    """解析后的规则模型"""

    platform: str = Field(..., description="平台名称")
    rule_type: str = Field(..., description="规则类型")
    constraints: dict = Field(default_factory=dict, description="约束条件")
    raw_text: str = Field(default="", description="原始规则文本")


# ==================== Form 表单管道请求 ====================

class PipelineFormRequest(BaseModel):
    """电商生图管道 Form 表单请求（支持文件上传 + 文本参数）"""

    platform: str = Field(
        ...,
        description="目标电商平台: amazon / taobao / aliexpress / shopee",
        examples=["amazon"],
    )
    selling_points: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="商品卖点文案（如：350ml大容量 | 食品级陶瓷 | 北欧简约风格）",
        examples=["350ml大容量 | 哑光釉面 | 食品级陶瓷 | 北欧简约设计"],
    )
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="不合规图片最大重试次数",
    )


class PipelineResponse(BaseModel):
    """电商生图管道响应"""

    task_id: str = Field(..., description="任务ID")
    status: str = Field(default="pending", description="任务状态")
    message: str = Field(default="任务已提交", description="响应消息")
    product_image_saved: Optional[str] = Field(default=None, description="原图保存路径")


class SellingPointSuggestionResponse(BaseModel):
    """商品图片卖点生成响应"""

    selling_points: str = Field(..., description="可直接用于生成任务的卖点文案")
    points: List[str] = Field(default_factory=list, description="结构化卖点列表")
    product_summary: str = Field(default="", description="商品视觉摘要")
