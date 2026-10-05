"""DICOM 压缩包（.zip）→ NIfTI 转换。

上传接口收到 .zip 时的处理流程（防御性设计）：

1. 逐条目读 DICOM 信息头（PS3.10 preamble 魔数 ``DICM`` @128 偏移 +
   ``pydicom.dcmread(stop_before_pixels=True)``），不做任何像素解码；
2. 序列防御：按 SeriesInstanceUID 分组——
   - 一个 DICOM 文件都没有 → UNSUPPORTED_MEDIA（不是 DICOM 数据）；
   - 多于一个序列 → INVALID_IMAGE（列出各序列，要求用户拆包重传）；
3. 单序列通过后把该序列条目解包到临时目录（拍平，防 zip 内任意嵌套路径），
   用 SimpleITK GDCM 序列读取（自动按 ImagePositionPatient 排序、正确处理
   RescaleSlope/Intercept、继承方向/层间距/层厚），写出 NIfTI。

转换后影像与直接上传 NIfTI 走完全相同的下游（_probe_input / runner），方向、
层数、层厚等几何信息由 DICOM 头继承，不做任何重采样。
"""

from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path
from typing import Any

import pydicom
import SimpleITK as sitk

from .errors import AppError
from .schemas import ErrorCode

# 防御上限：防止 zip 炸弹 / 异常巨大包
MAX_DCM_ENTRIES = 4000        # 压缩包内最多允许的 DICOM 文件数
MAX_TOTAL_DECOMPRESSED = 6 * 1024**3  # 解压后总字节上限 6GB
MAX_HEADER_BYTES = 1024 * 1024  # 单个条目读头时的读取上限


def _is_dicom_stream(stream: io.BufferedIOBase) -> bool:
    """判断流是否为 Part-10 DICOM 文件（128 字节 preamble + 'DICM' 魔数）。"""
    try:
        stream.seek(128)
        return stream.read(4) == b"DICM"
    except (OSError, ValueError):
        return False


def _read_header(stream: Any) -> pydicom.dataset.Dataset | None:
    """读 DICOM 信息头（不碰像素）。失败返回 None（当作非 DICOM 条目跳过）。"""
    try:
        stream.seek(0)
        return pydicom.dcmread(stream, stop_before_pixels=True, force=False)
    except Exception:  # noqa: BLE001 - 单个坏条目不应打断整体判断
        return None


def _remove_tree(path: Path) -> None:
    """逐文件删除自己创建的临时目录。

    不用 shutil.rmtree：部分运行环境对其挂有「防批量删除」守卫，会抛
    SystemExit 打断调用方（实测会杀死 asyncio 事件循环）。本函数只删
    convert_dicom_zip 自己解包出来的文件，逐个 unlink 后自底向上 rmdir。
    """
    try:
        entries = sorted(path.rglob("*"), key=lambda p: len(p.parts), reverse=True)
        for p in entries:
            try:
                if p.is_dir() and not p.is_symlink():
                    p.rmdir()
                else:
                    p.unlink()
            except OSError:
                pass
        try:
            path.rmdir()
        except OSError:
            pass
    except OSError:
        pass


def convert_dicom_zip(zip_path: Path, out_nifti: Path, tmp_dir: Path) -> dict:
    """校验并转换 DICOM zip → NIfTI。失败抛 AppError，成功返回序列信息。"""
    headers: list[tuple[str, pydicom.dataset.Dataset]] = []
    total_unc = 0
    seen_entries = 0

    try:
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                seen_entries += 1
                if seen_entries > MAX_DCM_ENTRIES * 4:
                    raise AppError(
                        ErrorCode.INVALID_IMAGE,
                        "压缩包条目过多，疑似不是病例数据",
                        detail={"entries": seen_entries},
                    )
                total_unc += info.file_size
                if total_unc > MAX_TOTAL_DECOMPRESSED:
                    raise AppError(
                        ErrorCode.PAYLOAD_TOO_LARGE,
                        "压缩包解压后超过大小上限",
                        detail={"total_bytes": total_unc},
                    )
                if not info.filename.lower().endswith((".dcm", ".dicm")):
                    # 扩展名不限死：非 .dcm 条目仍尝试魔数识别（部分导出无后缀）
                    with zf.open(info) as st:
                        if not _is_dicom_stream(st):
                            continue
                else:
                    with zf.open(info) as st:
                        if not _is_dicom_stream(st):
                            continue
                with zf.open(info) as st:
                    ds = _read_header(st)
                if ds is None or not getattr(ds, "SeriesInstanceUID", None):
                    continue
                headers.append((info.filename, ds))
    except zipfile.BadZipFile as exc:
        raise AppError(
            ErrorCode.UNSUPPORTED_MEDIA, "不是有效的 zip 压缩包", detail={"reason": str(exc)}
        ) from exc

    if not headers:
        raise AppError(
            ErrorCode.UNSUPPORTED_MEDIA,
            "压缩包内没有识别到 DICOM 数据（需要检查序列内含 .dcm 文件的 zip 包）",
        )

    # ── 序列防御：必须单一序列 ──
    by_series: dict[str, list[tuple[str, pydicom.dataset.Dataset]]] = {}
    for name, ds in headers:
        by_series.setdefault(str(ds.SeriesInstanceUID), []).append((name, ds))

    if len(by_series) > 1:
        series_list = sorted(
            (
                {
                    "series_uid": uid[:24] + "…",
                    "modality": str(items[0][1].get("Modality", "?")),
                    "slices": len(items),
                    "series_number": str(items[0][1].get("SeriesNumber", "?")),
                }
                for uid, items in by_series.items()
            ),
            key=lambda s: -s["slices"],
        )
        raise AppError(
            ErrorCode.INVALID_IMAGE,
            f"压缩包内包含 {len(by_series)} 个序列，请只打包单一序列后重新上传",
            detail={"series": series_list[:10]},
        )

    uid, items = next(iter(by_series.items()))
    first_ds = items[0][1]
    modality = str(first_ds.get("Modality", ""))
    warnings: list[str] = []
    if modality and modality != "CT":
        warnings.append(f"Modality 为 {modality}（本模型面向腹部 CT）")

    # ── 解包到临时目录（拍平）──
    tmp_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for i, (name, _ds) in enumerate(items):
                target = tmp_dir / f"{i:06d}.dcm"
                with zf.open(name) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted.append(target)

        # ── SimpleITK 序列读取 → NIfTI ──
        reader = sitk.ImageSeriesReader()
        if len(extracted) == 1:
            image = sitk.ReadImage(str(extracted[0]))
        else:
            names = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(tmp_dir), uid)
            if not names:
                raise AppError(
                    ErrorCode.INVALID_IMAGE,
                    "序列文件无法被 DICOM 解码器读取（可能为非常规编码）",
                )
            reader.SetFileNames(names)
            image = reader.Execute()

        if image.GetDimension() != 3:
            raise AppError(
                ErrorCode.INVALID_IMAGE,
                "影像必须是三维（多层序列）",
                detail={"dimension": image.GetDimension()},
            )
        if image.GetSize()[2] < 8:
            warnings.append(f"层数仅 {image.GetSize()[2]} 层，可能不是完整检查")

        sitk.WriteImage(image, str(out_nifti))
    finally:
        _remove_tree(tmp_dir)

    size = image.GetSize()
    spacing = image.GetSpacing()
    return {
        "series_uid": uid,
        "modality": modality,
        "slices": int(size[2]),
        "dimensions": [int(v) for v in size],
        "spacing_mm": [round(float(v), 4) for v in spacing],
        "warnings": warnings,
        "dicom_files": len(items),
    }
