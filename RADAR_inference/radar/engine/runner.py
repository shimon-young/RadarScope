"""推理内核。

**本文件是数值红线区**：滑动窗口推理、全图分割聚合、掩膜导出、146 项打分
全部逐字搬迁自 `api_server.evaluate_api` / `DataFolderEx`，不允许任何形式的
重排、简化或性能优化。唯一新增的是协作式取消检查点与进度回调（不影响计算）。

坐标/轴序约定见 docs 与 `scripts/verify_alignment.py`：
模型掩膜输出 (D,W,H)=(k,j,i) 与 sitk GetImageFromArray 期望的 (z,y,x) 天然一致，
**不要再加 transpose**，否则掩膜会相对 CT 面内旋转 90°。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Any, Callable

import sys

import numpy as np
import pandas as pd
import SimpleITK as sitk
import torch
import torch.nn.functional as F
from monai import transforms
from monai.data.utils import dense_patch_slices
from torch.utils.data import DataLoader

# 依赖仓库根的本地模块（loader 也会插入，这里显式保证本模块可独立导入）
_ROOT_DIR = str(Path(__file__).resolve().parents[2])
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from inference_demo import (  # noqa: E402
    DataFolder, _get_scan_interval, center_crop, collate_fn,
)

from ..errors import JobCancelled  # noqa: E402
from ..schemas import JobState  # noqa: E402
from .loader import ModelHandle  # noqa: E402

# ── 滑窗超参（勿改，与已验证的 golden 结果绑定）──
SW_BATCH_SIZE = 1
OVERLAP = 0.25
ROI_SIZE = (96, 256, 384)
REF_SPACING = (1.0, 1.0, 5.0)
BOUNDARY_MARGIN = 2

ProgressFn = Callable[[JobState, float, str | None], None]


# ══════════════════════════════════════════════════════════
# 数据管线（逐字搬迁自 DataFolderEx）
# ══════════════════════════════════════════════════════════
class DataFolderEx(DataFolder):
    """扩展 DataFolder：在 meta_info 中传出空间变换参数，用于把分割掩膜重采样回原图空间。

    `test_items=None` 时与父类逐字一致（146 项，数值红线）；
    仅在 plus/merlin20 模式下由上层显式下发 20 项清单。
    """

    def __init__(self, img_dir, test_items=None, english_mapping=None):
        super().__init__(img_dir)
        if test_items is not None:
            self.test_items = list(test_items)
            self.english_mapping = dict(english_mapping) if english_mapping else dict.fromkeys(self.test_items, '')
            self.test_organs = list(set([item.split('_')[0] for item in self.test_items]))

    def __getitem__(self, index):
        image_path = self.img_paths[index]
        data = {"image": image_path}
        res = transforms.LoadImaged(keys=["image"], image_only=False, ensure_channel_first=True)(data)
        image = res["image"]
        affine = res["image_meta_dict"]["affine"]
        spacing = (abs(affine[0, 0].item()), abs(affine[1, 1].item()), abs(affine[2, 2].item()))
        _, h, w, d = image.shape

        ref_spacing = REF_SPACING
        scale = [spacing[i] / ref_spacing[i] for i in range(3)]
        target_size = [int(h * scale[1]), int(w * scale[0]), int(d * scale[2])]

        trans = transforms.Compose([
            transforms.Resized(spatial_size=target_size, keys=["image"], mode="trilinear"),
            transforms.Transposed(keys=["image"], indices=(0, 3, 2, 1)),
        ])
        resized_data = trans(res)
        image = resized_data["image"]  # [C, D', W', H']，D'=z、W'=y、H'=x
        # 重采样后各轴的真实体素间距（extent 不变 / 新尺寸）。
        # 变量名对应：h=i 轴(x)、w=j 轴(y)、d=k 轴(z)；用于掩膜原点回推，不能用
        # REF_SPACING 硬编码——z 方向 5.009 vs 5.0 的误差小，但方向余弦 ≠ 单位阵时
        # 原点偏移必须走方向矩阵（见 run_inference 的 seg 保存）。
        resized_spacing = (
            spacing[0] * h / target_size[0],
            spacing[1] * w / target_size[1],
            spacing[2] * d / target_size[2],
        )
        image[image > 400] = 400
        image[image < -300] = -300
        image = (image - image.min()) / (image.max() - image.min() + 1e-8)

        roi_coords = np.nonzero(image[0].cpu().numpy())
        min_dhw = torch.from_numpy(np.min(roi_coords, axis=1))
        max_dhw = torch.from_numpy(np.max(roi_coords, axis=1))
        min_dhw = torch.max(min_dhw - torch.tensor([5, 20, 20]), torch.tensor([0, 0, 0]))
        max_dhw = torch.min(max_dhw + torch.tensor([5, 20, 20]),
                            torch.tensor([image.shape[1], image.shape[2], image.shape[3]]))

        cropped_image = image[:, min_dhw[0]:max_dhw[0], min_dhw[1]:max_dhw[1], min_dhw[2]:max_dhw[2]]
        crop_shape_dhw = tuple(cropped_image.shape[1:])

        data["image"] = cropped_image
        data_pad = self.pad_func(data)

        file_name = os.path.basename(image_path)
        # 用 SimpleITK 直接读取原始空间信息（LPS 约定，与后续掩膜重采样一致）
        # 注意：monai/nibabel 的 affine 是 RAS 约定，直接给 SimpleITK 会导致 origin 的 x/y 符号相反、掩膜偏移
        orig_sitk = sitk.ReadImage(image_path)
        orig_spacing = orig_sitk.GetSpacing()
        orig_origin = orig_sitk.GetOrigin()
        orig_direction = orig_sitk.GetDirection()

        meta_info = {
            'file_name': file_name,
            'img_path': image_path,
            'patient_id': file_name.split('_')[0],
            'test_organ_names': self.test_organs,
            'letter': 'None',
            'orig_spacing': orig_spacing,
            'orig_origin': orig_origin,
            'orig_direction': orig_direction,
            'resized_spacing': resized_spacing,
            'crop_min_dhw': (min_dhw[0].item(), min_dhw[1].item(), min_dhw[2].item()),
            'crop_shape_dhw': crop_shape_dhw,
        }
        return data_pad['image'].as_tensor(), self.test_items, meta_info


# ══════════════════════════════════════════════════════════
# 推理
# ══════════════════════════════════════════════════════════
@dataclass
class RunConfig:
    input_dir: Path
    csv_path: Path
    seg_path: Path | None = None
    device: str = "cuda"
    dtype: torch.dtype = torch.bfloat16
    # None = 沿用 146 项（默认）；merlin20 模式下由上层下发 20 项清单
    test_items: tuple[str, ...] | None = None
    english_mapping: dict[str, str] | None = None


@dataclass
class RunResult:
    rows: list[tuple[str, float | None]]
    csv_path: Path
    seg_path: Path | None
    timing: dict[str, float] = field(default_factory=dict)
    num_windows: int = 0


def _check(cancel: Event | None) -> None:
    """协作式取消检查点（不触发线程强杀，避免 CUDA 上下文损坏）。"""
    if cancel is not None and cancel.is_set():
        raise JobCancelled()


@torch.inference_mode()
def run_inference(
    handle: ModelHandle,
    cfg: RunConfig,
    *,
    cancel: Event | None = None,
    emit: ProgressFn | None = None,
) -> RunResult:
    """执行一次完整推理。返回逐项的 (器官_病症, prob) 行，非有限值置 None。"""
    t_all = time.perf_counter()
    t_pre = t_sw = t_post = t_seg = 0.0

    def _emit(state: JobState, p: float, msg: str | None = None) -> None:
        if emit is not None:
            emit(state, p, msg)

    datafolder = DataFolderEx(str(cfg.input_dir), test_items=cfg.test_items,
                             english_mapping=cfg.english_mapping)
    dataloader = DataLoader(
        datafolder, batch_size=1, shuffle=False,
        num_workers=0, drop_last=False, collate_fn=collate_fn,
    )

    results: list[list[Any]] = []
    organ_feat_dict: dict[str, Any] = {}
    num_windows = 0

    _emit(JobState.PREPROCESSING, 0.02, "读取并预处理图像")

    it = iter(dataloader)
    t0 = time.perf_counter()
    image, test_items, meta_info = next(it)
    t_pre = time.perf_counter() - t0

    _check(cancel)
    if cfg.device == "cuda":
        torch.cuda.empty_cache()

    fid = meta_info['file_name']
    organ_feat_dict[fid] = {}
    image = image[None].to(device=cfg.device, dtype=cfg.dtype)
    test_organs = meta_info['test_organ_names']
    image_size = list(image.shape[2:])
    num_spatial_dims = len(image.shape) - 2

    scan_interval = _get_scan_interval(image_size, ROI_SIZE, num_spatial_dims, OVERLAP)
    slices = dense_patch_slices(image_size, ROI_SIZE, scan_interval)
    num_win = len(slices)
    num_windows = num_win
    organ_logits = dict(zip(test_items, [[] for _ in test_items]))

    # 全图分割聚合（内存优化版）
    _emit(JobState.SLIDING_WINDOW, 0.08, f"滑窗推理 0/{num_win}")
    t0 = time.perf_counter()
    mask_dtype = torch.bfloat16 if cfg.device == "cuda" else torch.float16
    full_mask = torch.zeros((1, 37) + tuple(image_size), dtype=mask_dtype, device=cfg.device)
    count_map = torch.zeros((1, 37) + tuple(image_size), dtype=torch.uint8, device=cfg.device)

    for slice_g in range(0, num_win, SW_BATCH_SIZE):
        _check(cancel)
        slice_range = range(slice_g, min(slice_g + SW_BATCH_SIZE, num_win))
        unravel_slice = [
            [slice(int(idx / num_win), int(idx / num_win) + 1), slice(None)] + list(slices[idx % num_win])
            for idx in slice_range
        ]
        window_patches = torch.cat([image[win_slice] for win_slice in unravel_slice]).to(device=cfg.device)

        organ_logits, pred_window_seg_prob = handle.model.forward_test_win(
            window_patches, None, organ_logits, test_organs,
            handle.text_feat_dict, organ_feat_dict[fid], None,
        )

        interpolated_seg_prob = F.interpolate(
            pred_window_seg_prob, size=window_patches.shape[2:], mode='trilinear'
        ).float()

        for ii, slice_idx in enumerate(slice_range):
            full_slice = unravel_slice[ii]
            full_mask[full_slice] += interpolated_seg_prob[ii]
            count_map[full_slice] += 1

        _emit(JobState.SLIDING_WINDOW, 0.08 + 0.72 * min(slice_g + SW_BATCH_SIZE, num_win) / max(num_win, 1),
              f"滑窗推理 {min(slice_g + SW_BATCH_SIZE, num_win)}/{num_win}")

    count_map = torch.clamp(count_map, min=1)
    stitched_mask = (full_mask / count_map).argmax(1).unsqueeze(0)
    t_sw = time.perf_counter() - t0

    # ── 保存分割掩膜（重采样回原始图像空间）──
    if cfg.seg_path is not None:
        _check(cancel)
        _emit(JobState.SLIDING_WINDOW, 0.82, "导出分割掩膜")
        t0 = time.perf_counter()
        seg_np = stitched_mask.squeeze().cpu().numpy().astype(np.uint8)
        d_crop, w_crop, h_crop = meta_info['crop_shape_dhw']
        seg_crop = seg_np[:d_crop, :w_crop, :h_crop]
        # 不要 transpose：见文件头注释
        seg_sitk = sitk.GetImageFromArray(seg_crop)
        sp_x, sp_y, sp_z = meta_info['resized_spacing']
        seg_sitk.SetSpacing((sp_x, sp_y, sp_z))
        min_z, min_j, min_i = meta_info['crop_min_dhw']
        ox, oy, oz = meta_info['orig_origin']
        # 原点回推必须过方向矩阵：crop_min_dhw 是 (z, y, x) 轴的索引偏移，
        # 而 LPS 世界坐标偏移 = direction @ (各轴偏移×各轴间距)。
        # 之前的实现逐轴直接相加，对 y 方向余弦为 -1 的 LAS 数据（本批数据全部是）
        # 等于把 y 偏移加反 —— 裁剪偏移 12 的病例掩膜整体错位 24 个体素（AC4240fff）。
        dir_np = np.asarray(meta_info['orig_direction'], dtype=np.float64).reshape(3, 3)
        delta = np.array([min_i * sp_x, min_j * sp_y, min_z * sp_z], dtype=np.float64)
        offset_lps = dir_np @ delta
        seg_sitk.SetOrigin((ox + offset_lps[0], oy + offset_lps[1], oz + offset_lps[2]))
        seg_sitk.SetDirection(meta_info['orig_direction'])
        orig_img = sitk.ReadImage(meta_info['img_path'])
        resampler = sitk.ResampleImageFilter()
        resampler.SetReferenceImage(orig_img)
        resampler.SetInterpolator(sitk.sitkNearestNeighbor)
        resampler.SetDefaultPixelValue(0)
        seg_orig = resampler.Execute(seg_sitk)
        cfg.seg_path.parent.mkdir(parents=True, exist_ok=True)
        sitk.WriteImage(seg_orig, str(cfg.seg_path))
        t_seg = time.perf_counter() - t0

    # ── 边界器官检测 + 补窗口 ──
    _check(cancel)
    _emit(JobState.SLIDING_WINDOW, 0.88, "边界器官补推理")
    t0 = time.perf_counter()
    margin = BOUNDARY_MARGIN
    boundaries = []
    squeeze_stitched_mask = stitched_mask.squeeze(0).squeeze(0)
    for d in range(squeeze_stitched_mask.dim()):
        start_slice = [slice(None)] * squeeze_stitched_mask.dim()
        end_slice = [slice(None)] * squeeze_stitched_mask.dim()
        start_slice[d] = slice(None, margin)
        end_slice[d] = slice(-margin, None)
        boundaries.append(squeeze_stitched_mask[tuple(start_slice)][squeeze_stitched_mask[tuple(start_slice)] > 0])
        boundaries.append(squeeze_stitched_mask[tuple(end_slice)][squeeze_stitched_mask[tuple(end_slice)] > 0])
    boundaries = torch.cat(boundaries)
    boundary_organs = torch.unique(boundaries[boundaries > 0].flatten())

    for k, v in organ_logits.items():
        _check(cancel)
        if not len(v):
            organ_name = k.split('_')[0]
            organ_id = datafolder.organs.index(organ_name)
            window_patch, window_mask = center_crop(
                image, torch.eq(stitched_mask, organ_id + 1), crop_size=ROI_SIZE
            )
            window_mask = window_mask.float()
            window_mask[window_mask == 1] = organ_id + 1
            pad_data = handle.pad_func({'image': window_patch[0], 'label': window_mask[0]})
            window_patch, window_mask = pad_data['image'], pad_data['label']
            organ_logits, _ = handle.model.forward_test_win(
                window_patch[None], None, organ_logits, test_organs,
                handle.text_feat_dict, organ_feat_dict[fid], None, skip_organ=organ_id,
            )
    # 补窗口也是滑窗阶段的一部分
    t_sw += time.perf_counter() - t0

    # ── 打分（mean(0)[1]，勿改）──
    _emit(JobState.POSTPROCESSING, 0.94, "汇总结果")
    t0 = time.perf_counter()
    res = [meta_info['file_name']] + [''] * len(datafolder.test_items)
    organ_logits = {item: probs for item, probs in organ_logits.items() if len(probs) > 0}
    for item, probs in organ_logits.items():
        res[datafolder.test_items.index(item) + 1] = np.concatenate(probs).mean(0)[1]
    results.append(res)

    english_mapping = datafolder.english_mapping
    rows: list[tuple[str, float | None]] = []
    for key in datafolder.test_items:
        raw = res[datafolder.test_items.index(key) + 1]
        if raw == '' or raw is None:
            rows.append((key, None))
            continue
        val = float(raw)
        rows.append((key, val if np.isfinite(val) else None))

    pd.DataFrame(
        results,
        columns=['file_name'] + [f'{k} ({english_mapping[k]})' for k in datafolder.test_items],
    ).to_csv(cfg.csv_path, index=False, encoding='utf-8-sig')
    t_post = time.perf_counter() - t0

    total = time.perf_counter() - t_all
    return RunResult(
        rows=rows,
        csv_path=cfg.csv_path,
        seg_path=cfg.seg_path if cfg.seg_path and cfg.seg_path.is_file() else None,
        timing={
            "preprocess_s": round(t_pre, 3),
            "sliding_window_s": round(t_sw, 3),
            "postprocess_s": round(t_post, 3),
            "segmentation_s": round(t_seg, 3) if cfg.seg_path else None,
            "total_s": round(total, 3),
        },
        num_windows=num_windows,
    )
