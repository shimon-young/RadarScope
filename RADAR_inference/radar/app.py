"""FastAPI 应用工厂。

路由严格遵循 docs/API_CONTRACT.md v1.0。所有端点均为 `async def`，
任何阻塞 IO / 推理都下沉到 JobManager 的专用线程池，避免冻结事件循环。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, AsyncIterator

from fastapi import FastAPI, File, Form, Path as FPath, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .admin import REPO_ID, AdminAuth, RepoCache
from .seal import seal_hex
from .config import (
    CKPT_DIR, REPO_ROOT, VERSION, WEIGHT_MANIFEST, Settings, default_items_mode, load_settings,
)
from .engine.loader import ModelRegistry
from .errors import (
    AppError, app_error_handler, unhandled_error_handler, validation_error_handler,
)
from .jobs import JobManager
from .schemas import (
    TERMINAL_STATES, AdminLoginRequest, AdminLoginResponse, AdminPasswordChange,
    AdminSessionInfo, AdminSettings, Device, ErrorCode, JobList, JobMeta, JobParams,
    JobResult, JobState, JobSummary, ModelDownloadStatus, ModelType, Precision, RepoInfo,
    SystemInfo, WeightInfo,
)
from .services import JobService
from .storage import CSV_NAME, INPUT_NAME, LOG_NAME, SEG_NAME, JobStore

logger = logging.getLogger("radar")

DEFAULT_JOB_LIMIT = 20

# ── 后台运行参数（定时清理窗口等）的持久化 ──
ADMIN_SETTINGS_NAME = "admin_settings.json"


def _admin_settings_path(settings: Settings) -> Path:
    return settings.results_dir / ADMIN_SETTINGS_NAME


def _load_admin_settings(settings: Settings) -> dict:
    try:
        return json.loads(_admin_settings_path(settings).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - 文件缺失/损坏时用环境变量默认值
        return {}


def _save_admin_settings(settings: Settings, body: AdminSettings) -> None:
    p = _admin_settings_path(settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body.model_dump_json(indent=2), encoding="utf-8")


def _lan_ip() -> str:
    """探测本机局域网真实 IP（绑定 0.0.0.0 时 host 字段不可读，用它拼访问地址）。

    UDP connect 不会真正发包，只让内核选路由源地址；多网卡时返回默认路由出口 IP。
    """
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # 保留地址，仅触发路由选择
        ip = s.getsockname()[0]
    except OSError:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except OSError:
            ip = "127.0.0.1"
    finally:
        s.close()
    return ip


# ── 官方权重一键下载（后台线程跑 scripts/download_weights.py，走国内镜像 hf-mirror）──
_download_state = ModelDownloadStatus()
_download_lock = threading.Lock()
_DOWNLOAD_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "download_weights.py"

# job_id 统一由服务端生成（12 位十六进制）。对路径参数做格式白名单：
# ① 非法字符永远到不了文件系统层（纵深防御，避免任何路径拼接歧义）；
# ② 不存在的合法 id 才走 404，语义更干净。
JOB_ID_PATTERN = r"^[0-9a-f]{12}$"
JobId = Annotated[str, FPath(pattern=JOB_ID_PATTERN, description="12 位十六进制任务 ID")]


def frontend_dist_dir() -> Path:
    """前端构建产物目录（可用 RADAR_FRONTEND_DIST 覆盖，方便绿色版自定义布局）。"""
    custom = os.environ.get("RADAR_FRONTEND_DIST")
    if custom:
        return Path(custom).resolve()
    return REPO_ROOT / "frontend" / "dist"


class Ctx:
    """应用级单例容器（替代全局变量，便于测试替换）。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.auth = AdminAuth(settings.results_dir / "admin_auth.json")
        self.repo_cache = RepoCache(CKPT_DIR)
        self.store = JobStore(
            settings.jobs_dir,
            retention_days=settings.retention_days,
            max_jobs=settings.max_jobs,
            estimated_output_mb=settings.estimated_output_mb,
        )
        self.registry = ModelRegistry()
        self.service = JobService(settings, self.store, self.registry)
        self.manager = JobManager(self.store, self.service.execute)
        self.started_at = time.time()
        self.frontend_note = "未初始化"
        # 后台设置文件覆盖环境变量默认值（retention_days / max_jobs 可在运行中调整；
        # model_type / precision 是服务端统一默认值，前端不再选择）
        saved = _load_admin_settings(settings)
        if isinstance(saved.get("retention_days"), int):
            self.store.retention_days = saved["retention_days"]
        if isinstance(saved.get("max_jobs"), int):
            self.store.max_jobs = saved["max_jobs"]
        try:
            self.default_model_type = ModelType(saved.get("model_type", ModelType.MAIN.value))
        except ValueError:
            self.default_model_type = ModelType.MAIN
        try:
            self.default_precision = Precision(saved.get("precision", Precision.AUTO.value))
        except ValueError:
            self.default_precision = Precision.AUTO
        try:
            self.default_device = Device(saved.get("device", Device.AUTO.value))
        except ValueError:
            self.default_device = Device.AUTO


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ctx: Ctx = app.state.ctx
    ctx.store.ensure_ready()
    ctx.manager.attach_loop(asyncio.get_running_loop())

    async def _prune_loop() -> None:
        """定时清理：按 retention_days / max_jobs 周期回收过期任务结果，
        并卸载空闲超过 15 分钟的模型权重归还显存。

        retention_days 可在运行中通过 /api/admin/settings 调整（下个周期生效）。
        """
        while True:
            await asyncio.sleep(1800)
            try:
                removed = ctx.store.prune(keep_locked=ctx.manager.active_ids())
                if removed:
                    print(f"[api] 定时清理回收任务 {removed} 个")
            except Exception as exc:  # noqa: BLE001 - 清理失败不影响服务
                print(f"[api] 定时清理跳过: {exc}")
            try:
                unloaded = ctx.registry.unload_idle(max_idle_s=15 * 60)
                if unloaded:
                    print(f"[api] 已卸载空闲模型 {unloaded} 个（超 15 分钟无任务）")
            except Exception as exc:  # noqa: BLE001
                print(f"[api] 空闲模型卸载跳过: {exc}")

    try:
        removed = ctx.store.prune(keep_locked=ctx.manager.active_ids())
        if removed:
            print(f"[api] 已回收过期任务 {removed} 个")
    except Exception as exc:  # noqa: BLE001 - 启动清理失败不影响服务
        print(f"[api] 启动清理跳过: {exc}")
    prune_task = asyncio.create_task(_prune_loop())
    print(f"[api] RadarScope v{VERSION}  http://{ctx.settings.host}:{ctx.settings.port}"
          f"  [{'局域网' if ctx.settings.lan_mode else '单机'}模式]")
    try:
        yield
    finally:
        prune_task.cancel()
        await ctx.manager.shutdown()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    ctx = Ctx(settings)

    # 默认不挂载 /docs、/redoc、/openapi.json：
    # 它们会从 cdn.jsdelivr.net 拉 Swagger UI，是国内网络下的唯一外网依赖。
    # 需要交互文档时用 `python service.py --api-docs` 启动。
    docs_args = {}
    if not settings.api_docs:
        docs_args = {"docs_url": None, "redoc_url": None, "openapi_url": None}

    app = FastAPI(
        title="RadarScope",
        version=VERSION,
        description="达摩院 DAMO RADAR 医学影像大模型本地推理服务",
        lifespan=lifespan,
        **docs_args,
    )
    app.state.ctx = ctx

    app.add_middleware(
        CORSMiddleware,
        # 前端由本服务同源托管，生产环境无需跨域；仅放行本地 Vite 开发服务器，
        # 避免任意网页（含局域网内其他主机页面）跨域调用本机推理接口。
        allow_origins=[
            "http://localhost:5173", "http://127.0.0.1:5173",
            "http://localhost:5174", "http://127.0.0.1:5174",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    @app.middleware("http")
    async def _request_id(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex[:12]
        return await call_next(request)

    # ══════════════════════════ 系统 ══════════════════════════
    @app.get("/api/system", response_model=SystemInfo)
    async def api_system() -> SystemInfo:
        gpu_name: str | None = None
        gpu_total = gpu_free = gpu_used = None
        try:
            import torch

            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                free, total = torch.cuda.mem_get_info()
                gpu_total = round(total / 1024 ** 3, 2)
                gpu_free = round(free / 1024 ** 3, 2)
                gpu_used = round((total - free) / 1024 ** 3, 2)
        except Exception:  # noqa: BLE001
            pass

        return SystemInfo(
            version=VERSION,
            host=ctx.settings.host,
            port=ctx.settings.port,
            lan_mode=ctx.settings.lan_mode,
            lan_ip=_lan_ip(),
            gpu_available=gpu_name is not None,
            gpu_name=gpu_name,
            gpu_total_gb=gpu_total,
            gpu_free_gb=gpu_free,
            gpu_used_gb=gpu_used,
            torch=_lib_version("torch"),
            monai=_lib_version("monai"),
            transformers=_lib_version("transformers"),
            loaded_models=ctx.registry.loaded_models(),
            weights=_probe_weights(),
            jobs_running=1 if ctx.manager.running_id else 0,
            jobs_queued=len(ctx.manager.pending_ids),
            results_dir=str(ctx.settings.jobs_dir),
            disk_free_gb=ctx.store.free_gb(),
            uptime_s=round(time.time() - ctx.started_at, 2),
        )

    # ══════════════════════════ 任务 ══════════════════════════
    @app.post("/api/jobs", response_model=JobMeta, status_code=202)
    async def api_create_job(
        request: Request,
        file: UploadFile = File(...),
        model_type: ModelType | None = Form(None),
        device: Device = Form(Device.AUTO),
        precision: Precision | None = Form(None),
        threshold: float = Form(0.5),
        save_segmentation: bool = Form(True),
        patient_id: str | None = Form(None),
    ) -> JobMeta:
        if not 0.0 <= threshold <= 1.0:
            raise AppError(
                ErrorCode.BAD_REQUEST, "threshold 必须在 0~1 之间", detail={"threshold": threshold}
            )
        # 模型与精度由服务端统一配置（后台 /api/admin/settings）；
        # 显式传参仍被接受（API 兼容），但界面不再提供入口
        effective_model = model_type or ctx.default_model_type
        effective_precision = precision or ctx.default_precision
        # 设备：auto=跟随后台默认（GPU 优先/强制 CPU 由后台决定）；显式 gpu/cpu 仍兼容
        effective_device = device if device != Device.AUTO else ctx.default_device
        # 测试项集合由模型决定：main→radar146 全面筛查，plus→merlin20 急诊协议。
        resolved_mode = default_items_mode(effective_model)
        # 多用户场景：记录来源 IP 与患者标识（手填优先，服务端兜底从文件名推导）
        clean_patient = (patient_id or "").strip()[:64] or None
        client_ip = request.client.host if request.client else None

        params = JobParams(
            model_type=effective_model,
            items_mode=resolved_mode,
            device=effective_device,
            precision=effective_precision,
            threshold=threshold,
            save_segmentation=save_segmentation,
        )
        meta = await ctx.service.create(
            file, params, patient_id=clean_patient, client_ip=client_ip
        )
        ctx.manager.enqueue(meta.job_id)
        logger.info(
            "用户 %s 上传任务 %s：文件「%s」 模型=%s 设备=%s 精度=%s 阈值=%.2f 患者=%s",
            client_ip or "?",
            meta.job_id,
            file.filename or "?",
            getattr(effective_model, "value", effective_model),
            getattr(effective_device, "value", effective_device),
            getattr(effective_precision, "value", effective_precision),
            threshold,
            clean_patient or "(未填)",
        )
        return meta

    @app.get("/api/jobs", response_model=JobList)
    async def api_list_jobs(
        limit: int = Query(DEFAULT_JOB_LIMIT, ge=1, le=200),
        cursor: str | None = Query(None),
    ) -> JobList:
        items: list[JobSummary]
        items, next_cursor = ctx.store.summaries(limit=limit, cursor=cursor)
        # 排队中的任务补充实时队列位次（registry 快照里没有）
        for it in items:
            if it.state == JobState.QUEUED:
                it.queue_position = ctx.manager.queue_position(it.job_id)
        return JobList(items=items, next_cursor=next_cursor)

    @app.post("/api/jobs/{job_id}/prioritize", response_model=JobMeta)
    async def api_prioritize_job(job_id: JobId) -> JobMeta:
        """右键「优先计算」：把排队中的任务移到队首，当前任务完成后立即执行。"""
        meta = _meta_or_404(ctx, job_id)
        if meta.state != JobState.QUEUED:
            raise AppError(
                ErrorCode.CONFLICT,
                "仅等待中的任务可以调整优先级",
                detail={"state": meta.state.value},
            )
        if not ctx.manager.prioritize(job_id):
            raise AppError(ErrorCode.CONFLICT, "任务不在等待队列中")
        ctx.store.append_log(job_id, "prioritized: moved to front of queue")
        logger.info("用户置顶任务 %s（移到队首）", job_id)
        return _meta_or_404(ctx, job_id)

    def _require_admin(request: Request) -> None:
        """所有 /api/admin/*（除 /login）的鉴权守卫：Bearer token 12 小时有效。"""
        auth = request.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.startswith("Bearer ") else ""
        if not token or not ctx.auth.verify_token(token):
            raise AppError(
                ErrorCode.UNAUTHORIZED,
                "后台管理需要登录（或登录已过期）",
                detail={"login": "/api/admin/login"},
            )

    @app.post("/api/admin/login", response_model=AdminLoginResponse)
    async def api_admin_login(request: Request, body: AdminLoginRequest) -> AdminLoginResponse:
        token = ctx.auth.login(body.username, body.password)
        if token is None:
            ip = request.client.host if request.client else "?"
            logger.warning("后台登录失败：用户 %s (IP %s)", body.username, ip)
            raise AppError(ErrorCode.UNAUTHORIZED, "账号或密码不正确")
        ip = request.client.host if request.client else "?"
        logger.info("后台登录成功：用户 %s (IP %s)", body.username, ip)
        return AdminLoginResponse(token=token, username=body.username, expires_in=12 * 3600)

    @app.post("/api/admin/logout")
    async def api_admin_logout(request: Request) -> dict:
        auth = request.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.startswith("Bearer ") else ""
        if token:
            ctx.auth.logout(token)
        return {"ok": True}

    @app.get("/api/admin/session", response_model=AdminSessionInfo)
    async def api_admin_session(request: Request) -> AdminSessionInfo:
        _require_admin(request)
        return AdminSessionInfo(username=ctx.auth.username)

    @app.post("/api/admin/password")
    async def api_admin_password(request: Request, body: AdminPasswordChange) -> dict:
        _require_admin(request)
        if not ctx.auth.verify_password(body.old_password):
            raise AppError(ErrorCode.UNAUTHORIZED, "旧密码不正确")
        ctx.auth.set_password(body.new_password)
        ip = request.client.host if request.client else "?"
        logger.warning("后台管理员修改了密码 (IP %s)，所有会话已失效", ip)
        return {"ok": True, "note": "密码已更新，所有登录会话已失效，请重新登录"}

    @app.get("/api/admin/settings", response_model=AdminSettings)
    async def api_get_admin_settings(request: Request) -> AdminSettings:
        _require_admin(request)
        return AdminSettings(
            retention_days=ctx.store.retention_days,
            max_jobs=ctx.store.max_jobs,
            model_type=ctx.default_model_type,
            precision=ctx.default_precision,
            device=ctx.default_device,
        )

    @app.put("/api/admin/settings", response_model=AdminSettings)
    async def api_put_admin_settings(request: Request, body: AdminSettings) -> AdminSettings:
        """调整运行参数，立即生效并持久化。

        模型/精度/设备变更时卸载全部已加载权重：显存立即归还，下一个任务按新配置
        重新装载（先卸载再装载，不存在双模型并存挤显存的问题）。
        """
        _require_admin(request)
        config_changed = (
            body.model_type != ctx.default_model_type
            or body.precision != ctx.default_precision
            or body.device != ctx.default_device
        )
        ctx.store.retention_days = body.retention_days
        ctx.store.max_jobs = body.max_jobs
        ctx.default_model_type = body.model_type
        ctx.default_precision = body.precision
        ctx.default_device = body.device
        _save_admin_settings(ctx.settings, body)
        unloaded = ctx.registry.unload_all() if config_changed else 0
        if unloaded:
            ctx.store.append_log("system", f"admin settings changed: unloaded {unloaded} model(s)")
        logger.info(
            "后台修改运行参数：模型=%s 精度=%s 设备=%s 保留天数=%s 最大任务=%s%s",
            getattr(body.model_type, "value", body.model_type),
            getattr(body.precision, "value", body.precision),
            getattr(body.device, "value", body.device),
            body.retention_days,
            body.max_jobs,
            f"（已卸载 {unloaded} 个模型释放显存）" if unloaded else "",
        )
        try:
            removed = ctx.store.prune(keep_locked=ctx.manager.active_ids())
            if removed:
                print(f"[api] 设置调整后回收任务 {removed} 个")
        except Exception as exc:  # noqa: BLE001
            print(f"[api] 设置后清理跳过: {exc}")
        return body

    @app.post("/api/admin/model/unload")
    async def api_unload_models(request: Request) -> dict:
        """手动卸载全部已加载模型，归还显存（下一个任务自动重新装载）。"""
        _require_admin(request)
        unloaded = ctx.registry.unload_all()
        logger.info("后台卸载全部模型（释放显存）：%s 个", unloaded)
        return {"unloaded": unloaded}

    @app.get("/api/admin/model/repo", response_model=RepoInfo)
    async def api_admin_repo(request: Request, force: bool = Query(False)) -> RepoInfo:
        """官方仓库完整文件清单（含本地就绪状态），镜像拉取、缓存 10 分钟。

        仓库清单可缓存，但本地 exists/size 每次请求重探——下载进度条靠它实时增长。
        """
        _require_admin(request)
        files, err, fetched_at = ctx.repo_cache.get(force=force)
        for f in files:
            local = CKPT_DIR / f.path
            f.local_exists = local.is_file()
            f.local_size = local.stat().st_size if local.is_file() else None
        return RepoInfo(repo_id=REPO_ID, fetched_at=fetched_at, files=files, error=err)

    @app.get("/api/admin/model/download", response_model=ModelDownloadStatus)
    async def api_download_status(request: Request) -> ModelDownloadStatus:
        """权重下载后台任务状态；进度条由前端结合 /api/system 的 weights 算出。"""
        _require_admin(request)
        return _download_state

    @app.post("/api/admin/model/download", response_model=ModelDownloadStatus)
    async def api_download_model(request: Request, name: str = Query(...)) -> ModelDownloadStatus:
        """从国内镜像（hf-mirror.com）后台下载官方仓库文件到 ckpt 目录。

        name 支持精确文件路径或「目录/*」前缀，白名单以官方仓库清单为准；
        同一时间只允许一个下载（子进程跑 scripts/download_weights.py）。
        """
        _require_admin(request)
        global _download_state
        try:
            targets = ctx.repo_cache.validate_pattern(name)
        except LookupError as exc:
            raise AppError(ErrorCode.BAD_REQUEST, str(exc)) from exc
        with _download_lock:
            if _download_state.running:
                raise AppError(
                    ErrorCode.CONFLICT,
                    "已有下载任务在进行中",
                    detail={"name": _download_state.name},
                )
            _download_state = ModelDownloadStatus(
                running=True, name=name, started_at=datetime.now().astimezone()
            )

        def _run() -> None:
            global _download_state
            # 推理服务本身离线运行（HF_HUB_OFFLINE=1），下载子进程必须显式解除
            env = {**os.environ, "HF_ENDPOINT": "https://hf-mirror.com", "HF_HUB_OFFLINE": "0"}
            cmd = [
                sys.executable,
                str(_DOWNLOAD_SCRIPT),
                "--local-dir", str(CKPT_DIR),
                "--include-patterns", *targets,
            ]
            try:
                proc = subprocess.run(
                    cmd, env=env, cwd=str(REPO_ROOT),
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=6 * 3600,
                )
                if proc.returncode != 0:
                    tail = (proc.stderr or proc.stdout or "")[-800:]
                    raise RuntimeError(f"下载脚本退出码 {proc.returncode}: {tail}")
                # 权重落盘后立即生效：卸载已缓存的模型句柄，下次推理重新加载。
                # 否则用户下载完权重还得重启服务才能用上。
                ctx.registry.unload_all()
                _download_state = ModelDownloadStatus(
                    running=False, name=name,
                    started_at=_download_state.started_at,
                    finished_at=datetime.now().astimezone(),
                )
            except Exception as exc:  # noqa: BLE001 - 网络失败/超时都落到 error 字段
                _download_state = ModelDownloadStatus(
                    running=False, name=name,
                    started_at=_download_state.started_at,
                    finished_at=datetime.now().astimezone(),
                    error=str(exc)[:1000],
                )

        threading.Thread(target=_run, name="model-download", daemon=True).start()
        return _download_state


    @app.get("/api/jobs/{job_id}", response_model=JobMeta)
    async def api_job_meta(job_id: JobId) -> JobMeta:
        return _meta_or_404(ctx, job_id)

    @app.delete("/api/jobs/{job_id}", status_code=204)
    async def api_delete_job(job_id: JobId) -> None:
        meta = _meta_or_404(ctx, job_id)
        if meta.state not in TERMINAL_STATES:
            raise AppError(ErrorCode.CONFLICT, "任务尚未结束，无法删除", detail={"state": meta.state.value})
        ctx.store.delete(job_id, keep_locked=ctx.manager.active_ids())
        logger.info("用户删除任务 %s（状态=%s）", job_id, getattr(meta.state, "value", meta.state))

    @app.post("/api/jobs/{job_id}/cancel", response_model=JobMeta)
    async def api_cancel_job(job_id: JobId) -> JobMeta:
        meta = _meta_or_404(ctx, job_id)
        if meta.state in TERMINAL_STATES:
            raise AppError(
                ErrorCode.CONFLICT, "任务已结束，无法取消", detail={"state": meta.state.value}
            )
        if not ctx.manager.cancel(job_id):
            raise AppError(ErrorCode.CONFLICT, "任务未在队列中，无法取消")
        logger.info("用户取消任务 %s", job_id)
        return _meta_or_404(ctx, job_id)

    @app.get("/api/jobs/{job_id}/events")
    async def api_events(job_id: JobId, request: Request) -> StreamingResponse:
        meta = _meta_or_404(ctx, job_id)
        queue = ctx.manager.subscribe(job_id)

        async def gen() -> AsyncIterator[str]:
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    event = await queue.get()
                    name = getattr(event, "event", "progress")
                    yield f"event: {name}\ndata: {json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n\n"
                    if getattr(event, "state", None) in TERMINAL_STATES:
                        break
            finally:
                ctx.manager.unsubscribe(job_id, queue)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/jobs/{job_id}/result", response_model=JobResult)
    async def api_result(job_id: JobId) -> JobResult:
        result = ctx.store.load_result(job_id)
        if result is not None:
            return result
        meta = _meta_or_404(ctx, job_id)
        raise AppError(
            ErrorCode.BAD_REQUEST, "任务尚未完成", detail={"state": meta.state.value}
        )

    @app.get("/api/jobs/{job_id}/csv")
    async def api_csv(job_id: JobId) -> FileResponse:
        path = ctx.store.path_of(job_id, CSV_NAME)
        if not path.is_file():
            raise AppError(ErrorCode.NOT_FOUND, "结果 CSV 不存在", detail={"job_id": job_id})
        return FileResponse(path, filename=f"radar_{job_id}.csv", media_type="text/csv")

    @app.get("/api/jobs/{job_id}/log")
    async def api_log(job_id: JobId) -> FileResponse:
        path = ctx.store.path_of(job_id, LOG_NAME)
        if not path.is_file():
            raise AppError(ErrorCode.NOT_FOUND, "日志不存在", detail={"job_id": job_id})
        return FileResponse(path, filename=f"radar_{job_id}.log", media_type="text/plain; charset=utf-8")

    @app.get("/api/jobs/{job_id}/input")
    @app.get("/api/jobs/{job_id}/input.nii.gz")
    async def api_input(job_id: JobId) -> FileResponse:
        """回传原始上传的 NIfTI，供前端重开历史任务时重建 MPR 视图。

        `.nii.gz` 后缀别名：Cornerstone3D 的 NIfTI loader 用 URL 后缀判断是否
        gzip（`pathname.endsWith('.gz')`），后缀缺失会导致其头解析直接失败。
        MVP 阶段 DICOM 不支持，输入始终是 NIfTI，故无需格式协商。
        """
        path = ctx.store.path_of(job_id, INPUT_NAME)
        if not path.is_file():
            raise AppError(ErrorCode.NOT_FOUND, "原始影像不存在", detail={"job_id": job_id})
        return FileResponse(
            path,
            filename=f"input_{job_id}.nii.gz",
            media_type="application/gzip",
        )

    @app.get("/api/jobs/{job_id}/segmentation")
    @app.get("/api/jobs/{job_id}/segmentation.nii.gz")
    async def api_segmentation(
        job_id: JobId,
        space: str = Query("ras", pattern="^(ras|native)$"),
    ) -> FileResponse:
        path = ctx.store.path_of(job_id, SEG_NAME)
        if not path.is_file():
            raise AppError(ErrorCode.NOT_FOUND, "没有分割掩膜", detail={"job_id": job_id})
        # 掩膜与输入 CT 共享同一 sform（相同 size/spacing/origin/direction），
        # Cornerstone3D 依据 header 解释，故 ras 与 native 当前返回同一文件。
        return FileResponse(
            path,
            filename=f"segmentation_{job_id}_{space}.nii.gz",
            media_type="application/gzip",
        )

    def _build_export_zip(job_id: str, meta: object, result: object, out_path: Path) -> None:
        """打包导出：元数据 + 结果 CSV（隐私保护：不含原始影像 / 分割掩膜 / 日志）。"""
        import zipfile

        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_STORED) as zf:
            zf.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2, default=str))
            if result is not None:
                zf.writestr(
                    "result.json", json.dumps(result, ensure_ascii=False, indent=2, default=str)
                )
            for name in (CSV_NAME,):
                p = ctx.store.path_of(job_id, name)
                if p.is_file():
                    zf.write(p, arcname=name)

    @app.get("/api/jobs/{job_id}/export")
    async def api_export(job_id: JobId) -> FileResponse:
        """一键导出整包（zip）：meta.json / result.json / findings.csv。
        隐私保护：不包含原始影像、分割掩膜与日志。首次点击生成缓存，之后直接复用。"""
        meta = _meta_or_404(ctx, job_id)
        if meta.state != JobState.DONE:
            raise AppError(
                ErrorCode.BAD_REQUEST, "任务尚未完成，无法导出", detail={"state": meta.state.value}
            )
        out_path = ctx.store.path_of(job_id, "export.zip")
        if not out_path.is_file():
            result = ctx.store.load_result(job_id)
            meta_json = json.loads(json.dumps(_meta_or_404(ctx, job_id).model_dump(mode="json")))
            # 导出包作者标记（异或混淆，radar.seal 可解出）——用于追溯分发来源
            meta_json["package_seal"] = seal_hex()
            result_json = (
                json.loads(json.dumps(result.model_dump(mode="json"))) if result else None
            )
            await asyncio.to_thread(_build_export_zip, job_id, meta_json, result_json, out_path)
        return FileResponse(
            out_path, filename=f"radar_export_{job_id}.zip", media_type="application/zip"
        )

    # ══════════════════════════ 前端托管 ══════════════════════════
    # 必须注册在所有 /api 路由之后：路由按注册顺序匹配，API 永远优先。
    dist = frontend_dist_dir()
    if dist.is_dir():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="frontend-assets")

        @app.get("/", include_in_schema=False)
        async def frontend_root() -> FileResponse:
            return FileResponse(
                str(dist / "index.html"),
                # HTML 是构建入口（内部以 hash 文件名引用 JS/CSS），必须每次
                # 回源校验，否则浏览器启发式缓存会让前端更新对用户不可见
                headers={"Cache-Control": "no-cache"},
            )

        @app.get("/{full_path:path}", include_in_schema=False)
        async def frontend_spa(full_path: str) -> FileResponse:
            candidate = (dist / full_path).resolve()
            if dist in candidate.parents and candidate.is_file():
                return FileResponse(str(candidate))
            return FileResponse(
                str(dist / "index.html"),
                headers={"Cache-Control": "no-cache"},
            )

        _log_frontend(ctx, f"前端已挂载: {dist}")
    else:
        @app.get("/", include_in_schema=False)
        async def root() -> JSONResponse:
            return JSONResponse({
                "name": "RadarScope",
                "version": VERSION,
                "status": "ok",
                "mode": "局域网" if ctx.settings.lan_mode else "单机",
                "frontend": "未构建（frontend/dist 不存在）",
                "endpoints": {
                    "api_docs": "/docs",
                    "system": "/api/system",
                    "jobs": "/api/jobs",
                },
                "hint": "当前是纯 API 模式；构建前端后此页将自动变成应用首页。",
            })

        _log_frontend(ctx, "frontend/dist 不存在，运行在纯 API 模式")

    return app


def _log_frontend(ctx: "Ctx", message: str) -> None:
    ctx.frontend_note = message
    print(f"[api] {message}")


# ══════════════════════════ 辅助 ══════════════════════════
def _meta_or_404(ctx: Ctx, job_id: JobId) -> JobMeta:
    meta = ctx.store.load_meta(job_id)
    if meta is None:
        raise AppError(ErrorCode.NOT_FOUND, "任务不存在", detail={"job_id": job_id})
    return meta


def _lib_version(name: str) -> str | None:
    try:
        mod = __import__(name)
        return getattr(mod, "__version__", None)
    except Exception:  # noqa: BLE001
        return None


def _probe_weights() -> list[WeightInfo]:
    out: list[WeightInfo] = []
    for w in WEIGHT_MANIFEST:
        exists = os.path.isfile(w.path)
        size = os.path.getsize(w.path) if exists else None
        out.append(WeightInfo(
            name=w.name,
            path=w.path,
            required=w.required,
            exists=exists,
            size_bytes=size,
            expected_bytes=w.expected_bytes,
        ))
    return out
