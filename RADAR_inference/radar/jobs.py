"""异步任务管理：排队、单并发执行、SSE 扇出、协作式取消。

为什么用线程池而不是进程池：CUDA 上下文与 fork 不兼容，多进程会直接崩。
为什么只用一个 worker：推理本身吃满 GPU/内存，并发只会互相拖垮并放大 OOM 风险。

跨线程向 asyncio 发事件只能通过 `loop.call_soon_threadsafe`（见 publish_threadsafe），
直接操作 Queue 会造成竞争丢失。
"""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .schemas import ErrorBody, ErrorCode, JobState, ProgressEvent
from .storage import JobStore, utcnow

Event = object  # ProgressEvent | ResultEvent | ErrorEvent


class JobManager:
    def __init__(self, store: JobStore, execute: Callable[[str, threading.Event, Callable], None]) -> None:
        self._store = store
        self._execute = execute
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="radar-infer")
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending: list[str] = []
        self._running: str | None = None
        self._cancels: dict[str, threading.Event] = {}
        self._subs: dict[str, list[asyncio.Queue]] = {}
        self._worker: asyncio.Task | None = None
        self._started_at = time.time()

    # ═══════════════════ 生命周期 ═══════════════════
    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def shutdown(self) -> None:
        if self._worker is not None and not self._worker.done():
            self._worker.cancel()
        for ev in self._cancels.values():
            ev.set()
        self._executor.shutdown(wait=False, cancel_futures=False)

    @property
    def uptime_s(self) -> float:
        return round(time.time() - self._started_at, 2)

    def active_ids(self) -> list[str]:
        ids = list(self._pending)
        if self._running:
            ids.append(self._running)
        return ids

    @property
    def pending_ids(self) -> list[str]:
        return list(self._pending)

    @property
    def running_id(self) -> str | None:
        return self._running

    # ═══════════════════ SSE ═══════════════════
    def subscribe(self, job_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=512)
        self._subs.setdefault(job_id, []).append(q)
        # 立即补发当前状态，让后连上的客户端知道进度（契约：不补历史帧，只补快照）
        meta = self._store.load_meta(job_id)
        if meta is not None:
            q.put_nowait(ProgressEvent(
                job_id=job_id,
                state=meta.state,
                progress=meta.progress,
                stage=meta.stage,
                message=meta.message,
                queue_position=self._queue_position(job_id),
                updated_at=utcnow(),
            ))
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(job_id)
        if not subs:
            return
        if q in subs:
            subs.remove(q)
        if not subs:
            self._subs.pop(job_id, None)

    def _publish(self, job_id: str, event: Event) -> None:
        for q in list(self._subs.get(job_id, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass  # 慢客户端丢帧：状态以 meta.json 为准，重连后可补齐

    def publish_threadsafe(self, job_id: str, event: Event) -> None:
        """从 worker 线程向事件循环投递事件（唯一正确的跨线程方式）。"""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._publish, job_id, event)

    # ═══════════════════ 队列 / 执行 ═══════════════════
    def _queue_position(self, job_id: str) -> int | None:
        if job_id in self._pending:
            return self._pending.index(job_id) + 1
        return None

    def queue_position(self, job_id: str) -> int | None:
        """公开版队列位次（0 = 不在队列）。"""
        return self._queue_position(job_id)

    def _refresh_queue(self) -> None:
        for job_id in self._pending:
            meta = self._store.load_meta(job_id)
            if meta is None:
                continue
            meta.queue_position = self._queue_position(job_id)
            self._store.save_meta(meta)

    def enqueue(self, job_id: str) -> None:
        self._pending.append(job_id)
        self._refresh_queue()
        self._ensure_worker()

    def prioritize(self, job_id: str) -> bool:
        """把排队中的任务移到队首：当前任务完成后立即执行它。

        队列本身是严格 FIFO（按提交顺序），这是唯一的插队通道；
        运行中或不在队列里的任务返回 False，由端点转成 409。
        """
        if job_id not in self._pending:
            return False
        if self._pending[0] != job_id:
            self._pending.remove(job_id)
            self._pending.insert(0, job_id)
            self._refresh_queue()
        return True

    def _ensure_worker(self) -> None:
        if self._loop is None:
            return
        if self._worker is None or self._worker.done():
            self._worker = self._loop.create_task(self._worker_loop())

    async def _worker_loop(self) -> None:
        while self._pending:
            job_id = self._pending.pop(0)
            self._refresh_queue()
            await self._run_one(job_id)

    async def _run_one(self, job_id: str) -> None:
        loop = asyncio.get_running_loop()
        cancel_ev = threading.Event()
        self._cancels[job_id] = cancel_ev
        self._running = job_id
        emit = lambda ev: self.publish_threadsafe(job_id, ev)  # noqa: E731
        try:
            await loop.run_in_executor(self._executor, self._execute, job_id, cancel_ev, emit)
        except Exception as exc:  # noqa: BLE001 - execute 内部已兜底，这里只防 worker 崩掉
            self._store.append_log(job_id, f"worker error: {exc!r}")
        finally:
            self._running = None
            self._cancels.pop(job_id, None)

    # ═══════════════════ 取消 ═══════════════════
    def cancel(self, job_id: str) -> bool:
        """取消：排队中直接置为 cancelled；运行中通过 Event 让内核在检查点退出。"""
        meta = self._store.load_meta(job_id)
        if meta is None:
            return False

        if job_id in self._pending:
            self._pending.remove(job_id)
            self._refresh_queue()
            meta.state = JobState.CANCELLED
            meta.stage = JobState.CANCELLED.value
            meta.progress = 1.0
            meta.finished_at = utcnow()
            meta.error = ErrorBody(code=ErrorCode.CANCELLED, message="任务已取消")
            self._store.save_meta(meta)
            self.publish_threadsafe(job_id, ProgressEvent(
                job_id=job_id, state=JobState.CANCELLED, progress=1.0,
                stage=JobState.CANCELLED.value, message="任务已取消", updated_at=utcnow(),
            ))
            return True

        ev = self._cancels.get(job_id)
        if ev is not None:
            ev.set()
            return True
        return False
