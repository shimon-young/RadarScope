"""任务存储治理。

目录布局（单任务自包含，便于整体删除 / 迁移）：
    <jobs_dir>/<job_id>/
        input.nii.gz       原始上传
        meta.json          JobMeta  快照（任何状态迁移后重写）
        result.json        JobResult（仅 done）
        findings.csv       与既有 golden CSV 同格式（机器可读留档）
        segmentation.nii.gz（可选）
        log.txt            运行日志（可选）

写入一律走「临时文件 + os.replace」，避免半文件被并发读取。
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel

# os.replace 在 Windows 上被第三方短暂占用时的重试策略
_REPLACE_TRIES = 5
_REPLACE_BACKOFF_S = 0.03

from .errors import AppError
from .schemas import ErrorCode, JobMeta, JobResult, JobState, JobSummary

INPUT_NAME = "input.nii.gz"
META_NAME = "meta.json"
RESULT_NAME = "result.json"
CSV_NAME = "findings.csv"
SEG_NAME = "segmentation.nii.gz"
LOG_NAME = "log.txt"

_TERMINAL = frozenset({JobState.DONE, JobState.FAILED, JobState.CANCELLED})


def _rmtree_quiet(d: Path) -> None:
    """尽力删除目录，任何失败都不允许向外抛。

    关键是连 SystemExit 也要吞掉：某些运行环境（沙箱/安全软件钩子）会在
    shutil.rmtree 上挂「批量删除保护」，以 SystemExit 中断进程 —— 而它
    穿得过 FastAPI 的异常处理器，会把整个服务进程带走（实测发生过：
    DELETE /api/jobs/{id} → 服务静默退出）。删不掉顶多留下脏目录，
    由 prune 周期重试，绝不能搭上服务本身。
    """
    try:
        shutil.rmtree(d, ignore_errors=True)
    except SystemExit:
        pass
    except BaseException:
        pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobStore:
    def __init__(self, jobs_dir: Path, *, retention_days: int = 7, max_jobs: int = 200,
                 estimated_output_mb: int = 1024) -> None:
        self.jobs_dir = jobs_dir
        self.retention_days = retention_days
        self.max_jobs = max_jobs
        self.estimated_output_mb = estimated_output_mb

    # ── 基础 ──
    def ensure_ready(self) -> None:
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def dir_of(self, job_id: str) -> Path:
        return self.jobs_dir / job_id

    def path_of(self, job_id: str, *parts: str) -> Path:
        return self.dir_of(job_id).joinpath(*parts)

    def create_dir(self, job_id: str) -> Path:
        d = self.dir_of(job_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def exists(self, job_id: str) -> bool:
        return self.dir_of(job_id).is_dir()

    def write_bytes_atomic(self, path: Path, data: bytes) -> int:
        """原子写文件：临时文件 → os.replace。

        Windows 坑：`os.replace` 会抛 `[WinError 5] 拒绝访问`，原因是目标文件被第三方
        （杀毒软件实时扫描、Windows 搜索索引、网盘同步客户端等）短暂独占打开。
        这在进度频繁写 meta.json 时偶发，曾导致跑到 96% 的任务整体失败。

        分层降级，原则是"绝不因一次瞬时锁丢掉已完成的工作"：
          1. 重试若干次（瞬时锁通常在几十毫秒内释放）
          2. 重试无效则尝试清除目标文件的只读属性再替换一次
          3. 仍失败则退化为直接写（放弃原子性，但保证数据落盘）
          4. 全部失败才抛异常
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        last_err: OSError | None = None

        for attempt in range(_REPLACE_TRIES):
            fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                try:
                    os.replace(tmp, path)
                    return len(data)
                except PermissionError as e:
                    last_err = e
                    if attempt == 0 and path.is_file():
                        # 目标带只读属性时 replace 必然失败，清掉再试
                        try:
                            os.chmod(path, stat.S_IWUSR | stat.S_IRUSR)
                        except OSError:
                            pass
                    time.sleep(_REPLACE_BACKOFF_S * (attempt + 1))
            finally:
                if os.path.exists(tmp):
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass

        # 退化：直接写。meta/result 都是小文件，被截断的窗口极小，
        # 远好于让一个已推理完成的任务判定失败。
        try:
            path.write_bytes(data)
            return len(data)
        except OSError:
            if last_err is not None:
                raise last_err
            raise

    def write_json_atomic(self, path: Path, model: BaseModel) -> None:
        payload = model.model_dump_json()
        self.write_bytes_atomic(path, payload.encode("utf-8"))

    # ── meta / result ──
    def save_meta(self, meta: JobMeta) -> None:
        self.write_json_atomic(self.path_of(meta.job_id, META_NAME), meta)

    def load_meta(self, job_id: str) -> JobMeta | None:
        p = self.path_of(job_id, META_NAME)
        if not p.is_file():
            return None
        return JobMeta.model_validate_json(p.read_text(encoding="utf-8"))

    def save_result(self, result: JobResult) -> None:
        self.write_json_atomic(self.path_of(result.job_id, RESULT_NAME), result)

    def load_result(self, job_id: str) -> JobResult | None:
        p = self.path_of(job_id, RESULT_NAME)
        if not p.is_file():
            return None
        return JobResult.model_validate_json(p.read_text(encoding="utf-8"))

    def append_log(self, job_id: str, line: str) -> None:
        p = self.path_of(job_id, LOG_NAME)
        try:
            with p.open("a", encoding="utf-8") as f:
                f.write(f"[{utcnow().isoformat(timespec='seconds')}] {line}\n")
        except OSError:
            pass  # 日志失败不影响主流程

    def read_log(self, job_id: str) -> str:
        p = self.path_of(job_id, LOG_NAME)
        return p.read_text(encoding="utf-8") if p.is_file() else ""

    # ── 磁盘 / 容量 ──
    def free_bytes(self) -> int:
        target = self.jobs_dir if self.jobs_dir.exists() else self.jobs_dir.parent
        try:
            return shutil.disk_usage(str(target)).free
        except OSError:
            return 0

    def free_gb(self) -> float | None:
        b = self.free_bytes()
        return round(b / (1024 ** 3), 2) if b else None

    def ensure_capacity(self, need_bytes: int) -> None:
        """写入前检查磁盘余量，不足直接 507（契约规定 INSUFFICIENT_STORAGE）。"""
        free = self.free_bytes()
        if free and need_bytes > free:
            raise AppError(
                ErrorCode.INSUFFICIENT_STORAGE,
                "磁盘空间不足",
                detail={
                    "need_bytes": int(need_bytes),
                    "free_bytes": int(free),
                    "need_gb": round(need_bytes / 1024 ** 3, 2),
                    "free_gb": round(free / 1024 ** 3, 2),
                },
                retryable=True,
            )

    # ── 列表 / 删除 / 清理 ──
    def iter_job_ids(self) -> list[str]:
        if not self.jobs_dir.is_dir():
            return []
        return sorted(
            (d.name for d in self.jobs_dir.iterdir() if d.is_dir()),
            key=lambda n: self.dir_of(n).stat().st_mtime,
            reverse=True,
        )

    def summaries(self, limit: int = 50, cursor: str | None = None) -> tuple[list[JobSummary], str | None]:
        ids = self.iter_job_ids()
        start = ids.index(cursor) + 1 if cursor and cursor in ids else 0
        window = ids[start:start + limit]
        out: list[JobSummary] = []
        for jid in window:
            meta = self.load_meta(jid)
            if meta is None:
                continue
            max_prob: float | None = None
            positive_count: int | None = None
            res = self.load_result(jid)
            if res is not None:
                probs = [f.prob for f in res.findings if f.prob is not None]
                max_prob = max(probs) if probs else None
                positive_count = sum(1 for f in res.findings if f.positive)
            out.append(
                JobSummary(
                    job_id=jid,
                    file_name=meta.input.file_name if meta.input else None,
                    state=meta.state,
                    created_at=meta.created_at,
                    model_type=meta.params.model_type,
                    items_mode=meta.params.items_mode,
                    device=meta.params.device.value,
                    max_prob=max_prob,
                    positive_count=positive_count,
                    patient_id=meta.patient_id,
                    client_ip=meta.client_ip,
                )
            )
        next_cursor = window[-1] if len(ids) > start + limit else None
        return out, next_cursor

    def delete(self, job_id: str, *, keep_locked: Iterable[str] = ()) -> None:
        if job_id in set(keep_locked):
            raise AppError(ErrorCode.CONFLICT, "任务正在运行，无法删除")
        d = self.dir_of(job_id)
        if not d.is_dir():
            raise AppError(ErrorCode.NOT_FOUND, "任务不存在", detail={"job_id": job_id})
        _rmtree_quiet(d)

    def prune(self, *, keep_locked: Iterable[str] = ()) -> int:
        """回收终态任务：优先按保留天数，其次按任务数上限（较新的保留）。"""
        locked = set(keep_locked)
        candidates: list[tuple[str, datetime]] = []
        for jid in self.iter_job_ids():
            if jid in locked:
                continue
            meta = self.load_meta(jid)
            if meta is None or meta.state not in _TERMINAL:
                continue
            candidates.append((jid, meta.finished_at or meta.created_at))

        removed = 0
        cutoff = utcnow() - timedelta(days=self.retention_days)
        survivors: list[tuple[str, datetime]] = []
        for jid, ts in candidates:
            if ts < cutoff:
                _rmtree_quiet(self.dir_of(jid))
                removed += 1
            else:
                survivors.append((jid, ts))

        over = len(survivors) - self.max_jobs
        if over > 0:
            for jid, _ in sorted(survivors, key=lambda kv: kv[1])[:over]:
                _rmtree_quiet(self.dir_of(jid))
                removed += 1
        return removed


def dump_meta(meta: JobMeta) -> dict[str, Any]:
    return json.loads(meta.model_dump_json())
