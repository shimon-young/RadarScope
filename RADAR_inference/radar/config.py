"""配置与静态常量。

优先级：环境变量 > 默认。所有路径均以仓库布局推导，不使用相对路径。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .schemas import ModelType, WeightInfo

APP_NAME = "RadarScope"
VERSION = "2.0.0"

ROOT_DIR = Path(__file__).resolve().parents[1]  # .../RADAR_inference
REPO_ROOT = ROOT_DIR.parent                     # .../damo-radar
# 权重目录可经环境变量外置（分发包不含权重时，可指向数据盘目录）；
# 管理页的官方下载端点会写入同一目录，用户下载即装即用。
CKPT_DIR = Path(os.environ.get("RADAR_CKPT_DIR", "").strip() or (REPO_ROOT / "ckpt")).resolve()
DEFAULT_RESULTS_DIR = REPO_ROOT / "results"
DEFAULT_RESULTS_DIR = REPO_ROOT / "results"

_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "127.0.0.0"})

# 权重清单（存在性在运行时检查；expected_bytes 用于提示下载/拷贝是否完整）
WEIGHT_MANIFEST: tuple[WeightInfo, ...] = (
    WeightInfo(
        name="checkpoint_radar_pretrain.pth",
        path=str(CKPT_DIR / "checkpoint_radar_pretrain.pth"),
        required=True,
        expected_bytes=1_566_049_482,
    ),
    WeightInfo(
        name="checkpoint_radar_plus_finetuned_on_merlin.pth",
        path=str(CKPT_DIR / "checkpoint_radar_plus_finetuned_on_merlin.pth"),
        required=False,
        expected_bytes=1_651_335_230,
    ),
    WeightInfo(
        name="checkpoint_radar_plus.pth",
        path=str(CKPT_DIR / "checkpoint_radar_plus.pth"),
        # 从头训练版（plus_scratch 槽位）：下载后首次使用自动派生文本嵌入
        required=False,
        expected_bytes=1_651_336_682,
    ),
    WeightInfo(
        name="infer_text_embedding_merlin_en.pt",
        path=str(CKPT_DIR / "infer_text_embedding_merlin_en.pt"),
        # plus + merlin20 必需：MERLIN 官方提示词 + plus 文本编码器现算（见 text_embed CLI）
        required=False,
        expected_bytes=48_381,
    ),
    WeightInfo(
        name="infer_text_embedding_merlin.pt",
        path=str(CKPT_DIR / "infer_text_embedding_merlin.pt"),
        # 官方原文件，属「中文 BERT + main」空间，与 plus 不匹配；仅作对照，不参与推理
        required=False,
        expected_bytes=47_682,
    ),
    WeightInfo(
        name="infer_text_embedding_radar.pt",
        path=str(CKPT_DIR / "infer_text_embedding_radar.pt"),
        required=True,
        expected_bytes=346_348,
    ),
)

# 上传与产物规模估算（abdomen CT 常见 50~200MB，留出充分余量）
DEFAULT_MAX_UPLOAD_MB = 2048
ESTIMATED_OUTPUT_MB = 1024


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default).strip() or default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    results_dir: Path
    jobs_dir: Path
    max_upload_mb: float
    retention_days: int
    max_jobs: int
    estimated_output_mb: int
    log_level: str
    api_docs: bool = False

    @property
    def lan_mode(self) -> bool:
        """非回环地址即为局域网模式（会在 /api/system 暴露给前端做安全提示）。"""
        return self.host not in _LOCAL_HOSTS

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)


def load_settings() -> Settings:
    results_dir = Path(_env_str("RADAR_RESULTS_DIR", str(DEFAULT_RESULTS_DIR))).resolve()
    return Settings(
        host=_env_str("RADAR_HOST", "127.0.0.1"),
        port=_env_int("RADAR_PORT", 8000),
        results_dir=results_dir,
        jobs_dir=Path(_env_str("RADAR_JOBS_DIR", str(results_dir / "jobs"))).resolve(),
        max_upload_mb=_env_float("RADAR_MAX_UPLOAD_MB", DEFAULT_MAX_UPLOAD_MB),
        retention_days=_env_int("RADAR_RETENTION_DAYS", 7),
        max_jobs=_env_int("RADAR_MAX_JOBS", 200),
        estimated_output_mb=_env_int("RADAR_ESTIMATED_OUTPUT_MB", ESTIMATED_OUTPUT_MB),
        log_level=_env_str("RADAR_LOG_LEVEL", "info"),
        # /docs 的 Swagger UI 从 cdn.jsdelivr.net 加载，国内网络可能失败。
        # 产品形态下用不到，默认关闭；开发调试用 `python service.py --api-docs` 开启。
        api_docs=_env_str("RADAR_API_DOCS", "0") not in ("0", "", "false", "False"),
    )


def default_items_mode(model_type: ModelType):
    """测试项集合由模型原生决定：main→146 项全面筛查，plus→20 项 Merlin 急诊协议。"""
    from .schemas import ItemsMode

    return ItemsMode.RADAR146 if model_type == ModelType.MAIN else ItemsMode.MERLIN20
