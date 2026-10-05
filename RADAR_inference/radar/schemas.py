"""
前后端 JSON 契约的唯一来源（Pydantic v2）。

约定：
1. 本文件是契约的唯一权威定义，前端 `frontend/src/api/types.ts` 必须与本文件字段逐一对齐。
2. `docs/API_CONTRACT.md` 由本文件生成/维护，供人工阅读。
3. 任何字段增删改都必须同步三处：本文件、types.ts、API_CONTRACT.md。

设计要点（勿擅自更改）：
- 服务端**不**做阈值过滤，全量 findings 下发，阈值过滤在前端即时完成（避免改阈值重跑推理）。
- `prob` 必须是有限数；非有限值一律置 None 并在 input.warnings 记录，绝不允许 NaN 出现在 JSON 中
  （NaN 不是合法 JSON，会让前端 JSON.parse 崩溃）。
- 色板由后端下发（segmentation.labels[].color），前端仅存兜底默认值。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"


# ─────────────────────────────── 枚举 ───────────────────────────────


class JobState(str, Enum):
    QUEUED = "queued"
    PREPROCESSING = "preprocessing"
    SLIDING_WINDOW = "sliding_window"
    POSTPROCESSING = "postprocessing"
    FINALIZING = "finalizing"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES = frozenset({JobState.DONE, JobState.FAILED, JobState.CANCELLED})


class ModelType(str, Enum):
    MAIN = "main"
    PLUS = "plus"  # 官方 Merlin 微调版（界面显示 Plus-Merlin）
    PLUS_SCRATCH = "plus_scratch"  # 官方从头训练版 checkpoint_radar_plus.pth


class ItemsMode(str, Enum):
    """测试项集合。由模型原生决定：main→radar146（146 项全面筛查），plus→merlin20（20 项急诊协议）。"""

    RADAR146 = "radar146"
    MERLIN20 = "merlin20"


class Device(str, Enum):
    AUTO = "auto"
    GPU = "gpu"
    CPU = "cpu"


class Precision(str, Enum):
    AUTO = "auto"
    BF16 = "bf16"
    FP16 = "fp16"
    FP32 = "fp32"


class TextFeatures(str, Enum):
    PRECOMPUTED_PT = "precomputed_pt"
    ONLINE_MERLIN_PROMPTS = "online_merlin_prompts"
    ONLINE_EN_NAME = "online_en_name"


class ErrorCode(str, Enum):
    BAD_REQUEST = "BAD_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    UNSUPPORTED_MEDIA = "UNSUPPORTED_MEDIA"
    INVALID_IMAGE = "INVALID_IMAGE"
    INSUFFICIENT_STORAGE = "INSUFFICIENT_STORAGE"  # CUDA OOM / 内存不足，HTTP 507
    WEIGHTS_MISSING = "WEIGHTS_MISSING"
    CONFLICT = "CONFLICT"
    CANCELLED = "CANCELLED"
    UNAUTHORIZED = "UNAUTHORIZED"  # 后台管理未登录 / 会话过期，HTTP 401
    INTERNAL = "INTERNAL"


# ─────────────────────────────── 子结构 ───────────────────────────────


class InputMeta(BaseModel):
    file_name: str
    size_bytes: int
    sha256: str | None = None
    dimensions: list[int] | None = None  # [nx, ny, nz]
    spacing_mm: list[float] | None = None  # [sx, sy, sz]
    origin_mm: list[float] | None = None
    direction: list[float] | None = None
    datatype: str | None = None  # int16 / uint8 / float32 ...
    rescale_slope: float | None = None
    rescale_intercept: float | None = None
    warnings: list[str] = Field(default_factory=list)


class EngineInfo(BaseModel):
    model_type: ModelType
    items_mode: ItemsMode
    # 本次实际输出的「器官_病症」项数（146 / 20）。
    # 必须为可选：磁盘上历史任务的 result.json 写于该字段出现之前，
    # 若设为必填，load_result 严格校验会直接失败，进而拖垮 /api/jobs 列表。
    item_count: int | None = None
    device: Literal["cuda", "cpu"]
    device_name: str | None = None
    precision: str  # bfloat16 / float16 / float32
    torch: str | None = None
    monai: str | None = None
    transformers: str | None = None
    text_features: TextFeatures


class ThresholdInfo(BaseModel):
    default: float = 0.5
    applied_on: Literal["client"] = "client"
    min: float = 0.0
    max: float = 1.0


class TimingInfo(BaseModel):
    preprocess_s: float | None = None
    sliding_window_s: float | None = None
    postprocess_s: float | None = None
    segmentation_s: float | None = None
    total_s: float | None = None


class Finding(BaseModel):
    """单项「器官_病症」阳性概率。prob 为 None 表示该值非有限（原为 NaN/Inf）。"""

    key: str  # 原始中文键，如 "肝_肝囊肿"
    organ: str
    organ_en: str | None = None
    finding: str
    finding_en: str | None = None
    prob: float | None = None
    positive: bool = False  # 按本次请求阈值算一次，仅供参考；前端以本地阈值为准


class OrganSummary(BaseModel):
    organ: str
    organ_en: str | None = None
    max_prob: float | None = None
    positive_count: int = 0
    total_count: int = 0


class SegmentationLabel(BaseModel):
    index: int  # label 1..36
    organ: str
    organ_en: str | None = None
    color: list[int] = Field(min_length=3, max_length=3)  # RGB
    voxel_count: int = 0


class SegmentationInfo(BaseModel):
    available: bool = False
    url: str | None = None  # /api/jobs/{id}/segmentation?space=ras
    format: Literal["nifti-gz"] = "nifti-gz"
    dimensions: list[int] | None = None
    spacing_mm: list[float] | None = None
    num_labels: int = 0
    labels: list[SegmentationLabel] = Field(default_factory=list)


class Artifacts(BaseModel):
    result_url: str
    csv_url: str
    log_url: str | None = None
    input_url: str | None = None


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    detail: dict[str, Any] | None = None
    request_id: str | None = None
    retryable: bool = False


# ─────────────────────────────── 顶层结构 ───────────────────────────────


class JobParams(BaseModel):
    model_type: ModelType = ModelType.MAIN
    items_mode: ItemsMode | None = None  # 缺省时按 model_type 推导
    device: Device = Device.AUTO
    precision: Precision = Precision.AUTO
    threshold: float = 0.5
    save_segmentation: bool = True


class JobMeta(BaseModel):
    """任务状态快照（落 meta.json，SSE 断线可补齐）。"""

    schema_version: str = SCHEMA_VERSION
    job_id: str
    state: JobState
    progress: float = 0.0
    stage: str | None = None
    message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    params: JobParams
    input: InputMeta | None = None
    queue_position: int | None = None
    error: ErrorBody | None = None
    # 多用户场景：来源与患者标识（NIfTI 无患者信息，patient_id 由上传方提供
    # 或从文件名推导，允许为空）
    patient_id: str | None = None
    client_ip: str | None = None


class JobResult(BaseModel):
    """推理完成结果（落 result.json，GET /api/jobs/{id}/result 返回）。"""

    schema_version: str = SCHEMA_VERSION
    job_id: str
    state: Literal[JobState.DONE] = JobState.DONE
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    input: InputMeta
    engine: EngineInfo
    threshold: ThresholdInfo = Field(default_factory=ThresholdInfo)
    timing: TimingInfo = Field(default_factory=TimingInfo)

    findings: list[Finding] = Field(default_factory=list)
    organ_summary: list[OrganSummary] = Field(default_factory=list)
    segmentation: SegmentationInfo = Field(default_factory=SegmentationInfo)
    artifacts: Artifacts


class JobSummary(BaseModel):
    """历史列表条目（registry.json）。"""

    job_id: str
    file_name: str | None = None
    state: JobState
    created_at: datetime
    model_type: ModelType | None = None
    items_mode: ItemsMode | None = None
    device: str | None = None
    max_prob: float | None = None
    positive_count: int | None = None
    patient_id: str | None = None
    client_ip: str | None = None
    queue_position: int | None = None


class JobList(BaseModel):
    items: list[JobSummary] = Field(default_factory=list)
    next_cursor: str | None = None


# ─────────────────────────────── SSE 事件 ───────────────────────────────


class ProgressEvent(BaseModel):
    event: Literal["state", "progress", "result", "error"] = "progress"
    job_id: str
    state: JobState
    progress: float = 0.0
    stage: str | None = None
    message: str | None = None
    queue_position: int | None = None
    elapsed_s: float | None = None
    eta_s: float | None = None
    updated_at: datetime


class ResultEvent(BaseModel):
    """done 时推送一次摘要；完整 findings 需前端再 GET /result（避免 SSE 帧过大）。"""

    event: Literal["result"] = "result"
    job_id: str
    state: Literal[JobState.DONE] = JobState.DONE
    progress: float = 1.0
    positive_count: int = 0
    max_prob: float | None = None
    total_s: float | None = None


class ErrorEvent(BaseModel):
    event: Literal["error"] = "error"
    job_id: str
    state: Literal[JobState.FAILED, JobState.CANCELLED]
    error: ErrorBody


# ─────────────────────────────── 系统信息 ───────────────────────────────


class WeightInfo(BaseModel):
    name: str
    path: str
    required: bool = True
    exists: bool = False
    size_bytes: int | None = None
    expected_bytes: int | None = None


class LoadedModel(BaseModel):
    key: str
    model_type: ModelType
    items_mode: ItemsMode
    device: str
    dtype: str
    bytes: int
    last_used: datetime | None = None


class SystemInfo(BaseModel):
    version: str = "2.0.0"
    host: str  # 绑定地址
    port: int
    lan_ip: str  # 本机局域网真实 IP（供用户拼访问地址；绑定 0.0.0.0 时 host 不可读）
    lan_mode: bool  # 非 127.0.0.1 即为局域网模式
    gpu_available: bool
    gpu_name: str | None = None
    gpu_total_gb: float | None = None
    gpu_free_gb: float | None = None
    gpu_used_gb: float | None = None
    torch: str | None = None
    monai: str | None = None
    transformers: str | None = None
    loaded_models: list[LoadedModel] = Field(default_factory=list)
    weights: list[WeightInfo] = Field(default_factory=list)
    jobs_running: int = 0
    jobs_queued: int = 0
    results_dir: str
    disk_free_gb: float | None = None
    uptime_s: float | None = None


class AdminSettings(BaseModel):
    """后台可调的运行参数（持久化到 results/admin_settings.json，重启仍生效）。

    model_type / precision 是服务端统一默认值：硬件条件只有服务端清楚，
    前端不再暴露模型与精度选择，新任务一律按这里配置执行。
    """

    retention_days: int = Field(ge=1, le=365)
    max_jobs: int = Field(ge=10, le=2000)
    model_type: ModelType = ModelType.MAIN
    precision: Precision = Precision.AUTO
    # 计算设备默认值：auto=GPU 优先、无 GPU 自动回退 CPU；gpu/cpu 为强制指定
    device: Device = Device.AUTO


class ModelDownloadStatus(BaseModel):
    """官方权重一键下载的后台任务状态（同一时间只允许一个下载）。"""

    running: bool = False
    name: str | None = None  # 正在/最近下载的权重文件名
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None  # 失败时给出输出尾部，便于排查网络问题


# ─────────────────────────── 后台管理：鉴权 / 官方仓库 ───────────────────────────


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class AdminLoginResponse(BaseModel):
    token: str
    username: str
    expires_in: int  # 秒


class AdminPasswordChange(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class AdminSessionInfo(BaseModel):
    username: str


class RepoFileInfo(BaseModel):
    """官方 HF 仓库中的一个文件（递归展开），并附本地就绪状态。"""

    path: str  # 仓库内相对路径，如 bert-base-uncased/vocab.txt
    size: int  # 官方文件字节数（下载进度分母）
    local_exists: bool = False
    local_size: int | None = None


class RepoInfo(BaseModel):
    repo_id: str
    fetched_at: datetime | None = None
    files: list[RepoFileInfo] = Field(default_factory=list)
    error: str | None = None  # 镜像不可达时给出原因（此时 files 为空）
