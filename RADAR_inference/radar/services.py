"""任务编排：创建任务 / 同步执行 / 结果组装。

HTTP 层只负责协议；所有状态迁移、文件写入、错误分类都在这一层完成。
`JobService.execute` 运行在专用线程池（单 worker）中，**可以用 torch/CUDA**。
"""

from __future__ import annotations

import asyncio
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import SimpleITK as sitk
import numpy as np
from fastapi import UploadFile

from .config import Settings, VERSION, default_items_mode
from .dicom_zip import _remove_tree, convert_dicom_zip
from .engine.items import (
    ENGLISH_MAPPING, LABEL_OF_ORGAN, ORGANS, ORGANS_EN, items_spec, split_finding_key,
)
from .engine.loader import ModelRegistry, dtype_name, resolve_device, resolve_dtype
from .engine.palette import color_of_label
from .engine.runner import RunConfig, run_inference
from .errors import AppError, JobCancelled
from .schemas import (
    Artifacts, EngineInfo, ErrorBody, ErrorCode, Finding, InputMeta, ItemsMode,
    JobMeta, JobParams, JobResult, JobState, OrganSummary, ProgressEvent, ResultEvent,
    SegmentationInfo, SegmentationLabel, TimingInfo, ErrorEvent, ThresholdInfo,
)
from .storage import CSV_NAME, INPUT_NAME, SEG_NAME, JobStore, utcnow

ALLOWED_SUFFIXES = (".nii.gz", ".nii", ".zip")


def _convert_zip_sync(zip_path: Path, out_nifti: Path, tmp_dir: Path) -> dict:
    """convert_dicom_zip 的同步薄包装（供 asyncio.to_thread 调用）。"""
    return convert_dicom_zip(zip_path, out_nifti, tmp_dir)


def _derive_patient_id(file_name: str) -> str | None:
    """从文件名推导患者/病例编号（上传方未手填时的兜底）。

    规则保守：取第一个「含数字的词元」（去扩展名后按非字母数字切分），
    例如 "AC4242a2f.nii.gz" → "AC4242a2f"、"01_腹部.nii.gz" → "01"；
    推导不出含数字的词元就返回 None，宁缺毋滥。
    """
    import re

    stem = file_name
    for suf in (".nii.gz", ".nii", ".zip"):
        if stem.lower().endswith(suf):
            stem = stem[: -len(suf)]
            break
    for token in re.split(r"[^0-9A-Za-z_-]+", stem):
        clean = token.strip("_-")
        if clean and any(c.isdigit() for c in clean):
            return clean[:64]
    return None

# label 索引 → (中文名, 英文名)；索引 0 占位
ORGAN_NAME_BY_LABEL: list[tuple[str, str]] = [("", "")] + [
    (ORGANS[i], ORGANS_EN[i]) for i in range(len(ORGANS))
]


def _classify_failure(exc: Exception) -> tuple[ErrorCode, str, dict | None, bool]:
    """把底层异常翻译成用户可自助处理的错误（错误码 + 行动指引）。

    显存/内存不足是最常见的可恢复失败，给「换精度 / 换设备 / 关程序」的具体建议，
    其余仍归 INTERNAL 并附原因。
    """
    reason = (str(exc) or type(exc).__name__).splitlines()[0][:300]
    oom_cls: tuple[type[BaseException], ...] = ()
    try:  # CPU-only 环境没有 torch.cuda，不能让它拖垮兜底路径
        import torch

        oom_cls = (torch.cuda.OutOfMemoryError,)
    except Exception:  # noqa: BLE001
        pass

    text = f"{type(exc).__name__}: {exc}"
    if (oom_cls and isinstance(exc, oom_cls)) or "CUDA out of memory" in text:
        return (
            ErrorCode.INSUFFICIENT_STORAGE,
            "GPU 显存不足，无法完成本次推理。"
            "可尝试：① 把精度改为 fp32 或 fp16；② 设备改用 CPU；"
            "③ 关闭其他占用显存的程序后重试。",
            {"reason": reason},
            True,
        )
    low = text.lower()
    if (
        isinstance(exc, MemoryError)
        or "out of memory" in low
        or ("allocate" in low and ("cannot" in low or "can't" in low))
    ):
        return (
            ErrorCode.INSUFFICIENT_STORAGE,
            "系统内存不足，无法完成本次推理。"
            "可关闭其他大型程序后重试，或改用 CPU 模式（峰值内存更低）。",
            {"reason": reason},
            True,
        )
    return (ErrorCode.INTERNAL, "推理过程发生异常", {"reason": reason}, False)


class JobService:
    def __init__(self, settings: Settings, store: JobStore, registry: ModelRegistry) -> None:
        self.settings = settings
        self.store = store
        self.registry = registry

    # ══════════════════════════ 创建 ══════════════════════════
    async def create(
        self,
        upload: UploadFile,
        params: JobParams,
        *,
        patient_id: str | None = None,
        client_ip: str | None = None,
    ) -> JobMeta:
        file_name = upload.filename or "input.nii.gz"
        lower = file_name.lower()
        if not lower.endswith(ALLOWED_SUFFIXES):
            raise AppError(
                ErrorCode.UNSUPPORTED_MEDIA,
                "仅支持 NIfTI（.nii / .nii.gz）或 DICOM 压缩包（.zip）",
                detail={"file_name": file_name, "allowed": list(ALLOWED_SUFFIXES)},
            )
        # 阶段4：plus 已修为真 plus —— merlin20 用 20 项 merlin 文本嵌入；
        # 测试项集合由模型原生决定（main→radar146，plus→merlin20），不提供覆盖。
        declared = getattr(upload, "size", None)
        if declared is not None and declared > self.settings.max_upload_bytes:
            raise AppError(
                ErrorCode.PAYLOAD_TOO_LARGE,
                "上传文件过大",
                detail={"size": int(declared), "limit": self.settings.max_upload_bytes},
            )
        self.store.ensure_capacity(
            int((declared or 0) * 2 + self.settings.estimated_output_mb * 1024 * 1024)
        )

        job_id = uuid.uuid4().hex[:12]
        job_dir = self.store.create_dir(job_id)
        input_path = job_dir / INPUT_NAME
        is_zip = lower.endswith(".zip")

        # zip 解压后体积可达数倍：DICOM 压缩包按 6 倍预留容量
        if is_zip:
            self.store.ensure_capacity(
                int((declared or 0) * 6 + self.settings.estimated_output_mb * 1024 * 1024)
            )

        written = 0
        limit = self.settings.max_upload_bytes
        upload_path = job_dir / "upload.zip" if is_zip else input_path
        try:
            with upload_path.open("wb") as out:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > limit:
                        raise AppError(
                            ErrorCode.PAYLOAD_TOO_LARGE,
                            "上传文件过大",
                            detail={"limit": limit},
                        )
                    out.write(chunk)
        except AppError:
            _remove_tree(job_dir)
            raise
        finally:
            await upload.close()

        if written == 0:
            _remove_tree(job_dir)
            raise AppError(ErrorCode.BAD_REQUEST, "上传文件为空")

        dicom_info: dict | None = None
        if is_zip:
            # DICOM zip：信息头校验 + 单序列防御 + 转 NIfTI（线程池，避免阻塞事件循环）
            try:
                dicom_info = await asyncio.to_thread(
                    _convert_zip_sync, upload_path, input_path, job_dir / "_dicom_tmp"
                )
            except AppError:
                _remove_tree(job_dir)
                raise
            except Exception as exc:  # noqa: BLE001
                _remove_tree(job_dir)
                raise AppError(
                    ErrorCode.INVALID_IMAGE,
                    "DICOM 压缩包转换失败",
                    detail={"reason": str(exc)[:300]},
                ) from exc
            # 转换完成，原始 zip 不再需要（input.nii.gz 已就位）
            upload_path.unlink(missing_ok=True)

        input_meta = self._probe_input(input_path, file_name, written)
        if dicom_info:
            input_meta.warnings.extend(dicom_info.pop("warnings", []))
            if dicom_info.get("modality"):
                input_meta.warnings.insert(0, f"来源：DICOM 序列（Modality {dicom_info['modality']}）")
        meta = JobMeta(
            job_id=job_id,
            state=JobState.QUEUED,
            created_at=utcnow(),
            params=params,
            input=input_meta,
            progress=0.0,
            stage="queued",
            patient_id=patient_id or _derive_patient_id(file_name),
            client_ip=client_ip,
        )
        self.store.save_meta(meta)
        log_line = f"created file={file_name} size={written}"
        if dicom_info:
            log_line += f" | dicom series={dicom_info.get('series_uid', '')[:32]}… slices={dicom_info.get('slices')} dims={dicom_info.get('dimensions')}"
        self.store.append_log(job_id, log_line)
        return meta

    def _probe_input(self, path: Path, file_name: str, size: int) -> InputMeta:
        try:
            img = sitk.ReadImage(str(path))
            size_xyz = img.GetSize()
            spacing = img.GetSpacing()
            origin = img.GetOrigin()
            direction = img.GetDirection()
        except Exception as exc:  # noqa: BLE001 - 任何读取失败都归类为非法图像
            raise AppError(ErrorCode.INVALID_IMAGE, "无法读取 NIfTI 文件", detail={"reason": str(exc)})

        if len(size_xyz) != 3 or min(size_xyz) <= 0:
            raise AppError(ErrorCode.INVALID_IMAGE, "图像必须是三维", detail={"size": list(size_xyz)})

        slope = inter = None
        for key, target in (("scl_slope", "slope"), ("scl_inter", "inter")):
            if img.HasMetaDataKey(key):
                try:
                    val = float(img.GetMetaData(key))
                    slope = val if target == "slope" else slope
                    inter = val if target == "inter" else inter
                except ValueError:
                    pass

        warnings: list[str] = []
        z = float(spacing[2]) if len(spacing) > 2 else 0.0
        if z >= 3.0:
            warnings.append(f"层厚较厚（{z:.2f}mm），MPR 重建质量会下降")
        xy = (float(spacing[0]), float(spacing[1])) if len(spacing) > 1 else (0.0, 0.0)
        if z > 0 and max(xy) > 0 and (z / min(xy)) > 3.0:
            warnings.append("层间分辨率差异较大，冠状/矢状位已按各向异性校正")
        if size_xyz[2] < 30:
            warnings.append("层数偏少，可能不是完整的腹部 CT")

        return InputMeta(
            file_name=file_name,
            size_bytes=size,
            dimensions=list(size_xyz),
            spacing_mm=[round(float(v), 4) for v in spacing],
            origin_mm=[round(float(v), 3) for v in origin],
            direction=[round(float(v), 6) for v in direction],
            datatype=img.GetPixelIDTypeAsString(),
            rescale_slope=slope,
            rescale_intercept=inter,
            warnings=warnings,
        )

    # ══════════════════════════ 执行（在 worker 线程）══════════════════════════
    def execute(
        self,
        job_id: str,
        cancel_event,
        emit,          # Callable[[ProgressEvent | ResultEvent | ErrorEvent], None] 线程安全
    ) -> None:
        meta = self.store.load_meta(job_id)
        if meta is None or meta.state in (JobState.DONE, JobState.FAILED, JobState.CANCELLED):
            return

        last_progress = 0.0

        def stage(state: JobState, progress: float, message: str | None = None) -> None:
            nonlocal last_progress
            # 单调递增守卫：任何阶段重排都不允许让前端进度条回退
            progress = max(last_progress, min(1.0, max(0.0, progress)))
            last_progress = progress
            meta.state = state
            meta.progress = round(max(0.0, min(1.0, progress)), 4)
            meta.stage = state.value
            meta.message = message
            meta.queue_position = None
            self.store.save_meta(meta)
            emit(ProgressEvent(
                job_id=job_id, state=state,
                progress=meta.progress, stage=state.value, message=message,
                elapsed_s=_elapsed(meta.started_at),
                updated_at=utcnow(),
            ))

        def fail(code: ErrorCode, message: str, *, detail=None, retryable=False) -> None:
            body = ErrorBody(code=code, message=message, detail=detail, retryable=retryable)
            meta.state = JobState.FAILED if code != ErrorCode.CANCELLED else JobState.CANCELLED
            meta.progress = 1.0
            meta.stage = meta.state.value
            meta.error = body
            meta.finished_at = utcnow()
            self.store.save_meta(meta)
            self.store.append_log(job_id, f"{meta.state.value}: {message}")
            emit(ErrorEvent(
                job_id=job_id,
                state=JobState.CANCELLED if code == ErrorCode.CANCELLED else JobState.FAILED,
                error=body,
            ))

        try:
            meta.started_at = utcnow()
            # 阶段起点必须低于 runner 的首个 emit（runner 从 0.02 开始），否则进度会回退
            stage(JobState.PREPROCESSING, 0.004, "初始化")

            if cancel_event.is_set():
                raise JobCancelled()

            device = resolve_device(meta.params.device.value)
            dtype = resolve_dtype(meta.params.precision.value, device)
            items_mode = meta.params.items_mode or default_items_mode(meta.params.model_type)

            stage(JobState.PREPROCESSING, 0.01, "加载模型")
            handle = self.registry.acquire(meta.params.model_type, items_mode, device, dtype)

            job_dir = self.store.dir_of(job_id)
            test_items, english_mapping = items_spec(items_mode)
            cfg = RunConfig(
                input_dir=job_dir,
                csv_path=job_dir / CSV_NAME,
                seg_path=(job_dir / SEG_NAME) if meta.params.save_segmentation else None,
                device=device,
                dtype=dtype,
                test_items=(None if items_mode == ItemsMode.RADAR146 else test_items),
                english_mapping=(None if items_mode == ItemsMode.RADAR146 else english_mapping),
            )
            result_rows = run_inference(
                handle, cfg,
                cancel=cancel_event,
                emit=lambda s, p, m: stage(s, p, m),
            )
            stage(JobState.FINALIZING, 0.96, "组装结果")

            job_result = self._build_result(meta, result_rows.timing, device, dtype, items_mode, cfg)
            self.store.save_result(job_result)

            meta.state = JobState.DONE
            meta.progress = 1.0
            meta.stage = JobState.DONE.value
            meta.message = None
            meta.finished_at = utcnow()
            self.store.save_meta(meta)
            self.store.append_log(job_id, f"done windows={result_rows.num_windows}")

            probs = [f.prob for f in job_result.findings if f.prob is not None]
            emit(ResultEvent(
                job_id=job_id,
                positive_count=sum(1 for f in job_result.findings if f.positive),
                max_prob=max(probs) if probs else None,
                total_s=job_result.timing.total_s,
            ))
        except JobCancelled as exc:
            fail(ErrorCode.CANCELLED, str(exc) or "任务已取消")
        except AppError as exc:
            fail(exc.code, exc.message, detail=exc.detail, retryable=exc.retryable)
        except Exception as exc:  # noqa: BLE001 - 兜底，避免 worker 静默失败
            code, message, detail, retryable = _classify_failure(exc)
            fail(code, message, detail=detail, retryable=retryable)
            import traceback
            self.store.append_log(job_id, traceback.format_exc()[-4000:])
        finally:
            # 每个任务结束后释放推理期间的碎片缓存（权重本身仍常驻 registry
            # 供后续任务复用；空闲超时 / 后台改配置时才整体卸载，见 registry.unload）
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:  # noqa: BLE001 - CPU 环境忽略
                pass

    # ══════════════════════════ 结果组装 ══════════════════════════
    def _build_result(self, meta: JobMeta, timing: dict, device: str, dtype, items_mode: ItemsMode,
                      cfg: RunConfig) -> JobResult:
        threshold = meta.params.threshold
        _items, item_english = items_spec(items_mode)
        findings: list[Finding] = []
        for key, prob in _rows_of(meta, cfg):
            organ, finding = split_finding_key(key)
            organ_en = ORGANS_EN[LABEL_OF_ORGAN[organ] - 1] if organ in LABEL_OF_ORGAN else None
            findings.append(Finding(
                key=key,
                organ=organ,
                organ_en=organ_en,
                finding=finding,
                finding_en=_english_of(key, item_english),
                prob=prob,
                positive=bool(prob is not None and prob >= threshold),
            ))

        grouped: dict[str, OrganSummary] = {}
        for f in findings:
            s = grouped.setdefault(f.organ, OrganSummary(
                organ=f.organ, organ_en=f.organ_en, max_prob=None, positive_count=0, total_count=0,
            ))
            s.total_count += 1
            if f.positive:
                s.positive_count += 1
            if f.prob is not None and (s.max_prob is None or f.prob > s.max_prob):
                s.max_prob = f.prob

        return JobResult(
            job_id=meta.job_id,
            created_at=meta.created_at,
            started_at=meta.started_at,
            finished_at=utcnow(),
            input=meta.input,  # type: ignore[arg-type]
            engine=_engine_info(self.registry, meta, device, dtype, items_mode),
            threshold=ThresholdInfo(default=threshold),
            timing=TimingInfo(**timing),
            findings=findings,
            organ_summary=sorted(grouped.values(), key=lambda s: s.organ),
            segmentation=self._segmentation_info(meta, cfg),
            artifacts=Artifacts(
                result_url=f"/api/jobs/{meta.job_id}/result",
                csv_url=f"/api/jobs/{meta.job_id}/csv",
                log_url=f"/api/jobs/{meta.job_id}/log",
                # 带上 .nii.gz 后缀：Cornerstone3D NIfTI loader 以后缀识别 gzip
                input_url=f"/api/jobs/{meta.job_id}/input.nii.gz",
            ),
        )

    def _segmentation_info(self, meta: JobMeta, cfg: RunConfig) -> SegmentationInfo:
        if cfg.seg_path is None or not cfg.seg_path.is_file():
            return SegmentationInfo(available=False)
        try:
            img = sitk.ReadImage(str(cfg.seg_path))
            arr = sitk.GetArrayFromImage(img).astype(np.uint8)
        except Exception:  # noqa: BLE001
            return SegmentationInfo(available=False)

        counts = np.bincount(arr.reshape(-1), minlength=37)[:37]
        labels: list[SegmentationLabel] = []
        for lab in range(1, 37):
            if counts[lab] <= 0:
                continue
            cn, en = ORGAN_NAME_BY_LABEL[lab]
            labels.append(SegmentationLabel(
                index=lab,
                organ=cn,
                organ_en=en,
                color=color_of_label(lab),
                voxel_count=int(counts[lab]),
            ))
        return SegmentationInfo(
            available=True,
            # 同样带 .nii.gz 后缀（loader 按 URL 后缀判断是否 gzip）
            url=f"/api/jobs/{meta.job_id}/segmentation.nii.gz",
            dimensions=list(img.GetSize()),
            spacing_mm=[round(float(v), 4) for v in img.GetSpacing()],
            num_labels=len(labels),
            labels=labels,
        )


def _english_of(key: str, mapping: dict[str, str] | None = None) -> str | None:
    """英文项名：默认 146 项表，merlin20 模式下由调用方下发 20 项表。"""
    return (mapping or ENGLISH_MAPPING).get(key)


def _rows_of(meta: JobMeta, cfg: RunConfig) -> list[tuple[str, float | None]]:
    """从 golden 同格式 CSV 读回逐项概率。

    直接读回 runner 落盘的 CSV，保证「下发值」与「留档值」不可能不一致；
    非有限值一律降级为 None（契约：JSON 中不得出现 NaN）。
    """
    df = pd.read_csv(cfg.csv_path)
    if df.empty:
        return []
    row = df.iloc[0]
    out: list[tuple[str, float | None]] = []
    for col in df.columns:
        if col == "file_name":
            continue
        key = col.split(" (")[0]
        raw = row[col]
        if pd.isna(raw):
            out.append((key, None))
            continue
        val = float(raw)
        out.append((key, val if math.isfinite(val) else None))
    return out


def _elapsed(started_at: datetime | None) -> float | None:
    if started_at is None:
        return None
    return round((utcnow() - started_at).total_seconds(), 2)


def _engine_info(registry: ModelRegistry, meta: JobMeta, device: str, dtype,
                 items_mode: ItemsMode) -> EngineInfo:
    import monai
    import torch
    import transformers

    return EngineInfo(
        model_type=meta.params.model_type,
        items_mode=items_mode,
        item_count=len(items_spec(items_mode)[0]),
        device=device,
        device_name=torch.cuda.get_device_name(0) if device == "cuda" else None,
        precision=dtype_name(dtype),
        torch=torch.__version__,
        monai=monai.__version__,
        transformers=transformers.__version__,
        text_features="precomputed_pt",
    )



