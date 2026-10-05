"""模型注册表：设备/精度解析 + 单飞加载 + 已加载模型视图。

加载权重的代码与旧 `api_server.load_model` 逐字一致（不得改动/优化）。
"""

from __future__ import annotations

import os
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Literal

import torch
from monai import transforms

from ..config import CKPT_DIR
from ..errors import AppError
from ..schemas import ErrorCode, ItemsMode, LoadedModel, ModelType

# 依赖仓库根的本地模块（inference_demo 等）
_ROOT_DIR = Path(__file__).resolve().parents[2]
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

# inference_demo 在 **import 期** 就把 CONFIGS_ROOT 拼进 tokenizer 路径
# （模块级常量），所以必须在 import 之前钉死绝对路径。
# 旧实现依赖 CWD=RADAR_inference 让 "../ckpt" 侥幸成立，太脆弱。
os.environ.setdefault("CONFIGS_ROOT", str(CKPT_DIR))

from dynamic_network_architectures.med import XBertEncoder  # noqa: E402
from dynamic_network_architectures.vision_branch import VisionBranch  # noqa: E402
from inference_demo import RADAR, _get_scan_interval, center_crop, collate_fn  # noqa: E402

from .items import items_spec  # noqa: E402

DeviceParam = Literal["auto", "gpu", "cpu"]
PrecisionParam = Literal["auto", "bf16", "fp16", "fp32"]

# main 在中文放射报告上预训练（bert-base-chinese，词表 21128）；
# plus 在英文 Merlin 协议上微调，因此必须用 bert-base-uncased（词表 30522）。
BERT_NAME_OF: dict[str, str] = {
    "main": "bert-base-chinese",
    "plus": "bert-base-uncased",
    "plus_scratch": "bert-base-uncased",
}

# model_type → 文本嵌入文件名。
# plus 用 merlin_en.pt（MERLIN 官方提示词 + plus 文本编码器现算），
# 不用官方同名的 merlin.pt：后者是「中文 BERT + main 权重」空间下的嵌入，
# 与 plus 的英文空间不匹配，配错不会报错，只会静默产出错误概率。
TEXT_EMBEDDING_NAME_OF: dict[str, str] = {
    ModelType.MAIN.value: "infer_text_embedding_radar.pt",
    ModelType.PLUS.value: "infer_text_embedding_merlin_en.pt",
    ModelType.PLUS_SCRATCH.value: "infer_text_embedding_plus_scratch.pt",
}

CHECKPOINT_NAME_OF: dict[str, str] = {
    ModelType.MAIN.value: "checkpoint_radar_pretrain.pth",
    ModelType.PLUS.value: "checkpoint_radar_plus_finetuned_on_merlin.pth",
    ModelType.PLUS_SCRATCH.value: "checkpoint_radar_plus.pth",
}


@contextmanager
def _bert_context(model_type: ModelType, ckpt_dir: Path) -> Iterator[None]:
    """为 XBertEncoder.from_config 准备正确的 BERT 语言/路径上下文。

    官方 `XBertEncoder.from_config` 只认两个环境变量（CONFIGS_ROOT / BERT_NAME），
    没有别的可传参数，因此只能这样切换。加载被 ModelRegistry._lock 串行化，
    try/finally 还原保证不会污染其它模型的加载。

    必须切到对应语言的 BERT：main 的文本编码器词表 21128，plus 是 30522，
    配错会让整层 text_encoder（199 个参数）在 strict=False 下被静默丢弃。
    """
    saved = {k: os.environ.get(k) for k in ("BERT_NAME", "CONFIGS_ROOT")}
    os.environ["BERT_NAME"] = BERT_NAME_OF[model_type.value]
    os.environ["CONFIGS_ROOT"] = str(ckpt_dir)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def resolve_device(param: DeviceParam) -> str:
    """auto/gpu/cpu → cuda|cpu（与旧实现一致：gpu 不可用时显式报错）。"""
    if param == "cpu":
        return "cpu"
    if param == "gpu":
        if not torch.cuda.is_available():
            raise AppError(ErrorCode.BAD_REQUEST, "GPU 不可用", detail={"param": "device"})
        return "cuda"
    return "cuda" if torch.cuda.is_available() else "cpu"


def resolve_dtype(param: PrecisionParam, device: str) -> torch.dtype:
    if param == "fp32":
        return torch.float32
    if param == "fp16":
        return torch.float16
    if param == "bf16":
        return torch.bfloat16
    # auto：GPU 默认 bf16，CPU 默认 fp32（CPU bf16 极慢）
    return torch.bfloat16 if device == "cuda" else torch.float32


def dtype_name(dtype: torch.dtype) -> str:
    return str(dtype).replace("torch.", "")


@dataclass
class ModelHandle:
    """一次加载的产物（推理内核直接消费）。"""

    key: str
    model_type: ModelType
    items_mode: ItemsMode
    device: str
    dtype: torch.dtype
    pad_func: Any
    model: Any
    text_feat_dict: dict
    bytes: int
    loaded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_used: datetime | None = None


class ModelRegistry:
    """按 (model_type, items_mode, device, dtype) 缓存；同一 key 只允许一个线程加载。"""

    def __init__(self, ckpt_dir: Path = CKPT_DIR) -> None:
        self.ckpt_dir = ckpt_dir
        self._cache: dict[str, ModelHandle] = {}
        self._lock = threading.Lock()

    def _checkpoint_path(self, model_type: ModelType) -> Path:
        return self.ckpt_dir / CHECKPOINT_NAME_OF[model_type.value]

    def _text_embedding_path(self, model_type: ModelType, items_mode: ItemsMode) -> Path:
        """模型槽位 → 约定的文本嵌入文件。

        main 用官方发布的 infer_text_embedding_radar.pt（中文 BERT 空间，
        官方仓库 ckpt/ 内确有此文件，我们本地副本与其字节一致）；
        plus 用本项目按官方英文 prompt 配方现算的 merlin_en.pt（见
        TEXT_EMBEDDING_NAME_OF 处说明）；
        plus_scratch 官方没有对应的嵌入文件，文件名按槽位约定，
        缺失时请用 CLI 显式生成。
        """
        return self.ckpt_dir / TEXT_EMBEDDING_NAME_OF[model_type.value]

    def acquire(
        self,
        model_type: ModelType,
        items_mode: ItemsMode,
        device: str,
        dtype: torch.dtype,
    ) -> ModelHandle:
        key = f"{model_type.value}_{items_mode.value}_{device}_{dtype_name(dtype)}"
        with self._lock:
            handle = self._cache.get(key)
            if handle is not None:
                handle.last_used = datetime.now(timezone.utc)
                return handle
            handle = self._load(key, model_type, items_mode, device, dtype)
            handle.last_used = datetime.now(timezone.utc)
            self._cache[key] = handle
            return handle

    def _load(
        self,
        key: str,
        model_type: ModelType,
        items_mode: ItemsMode,
        device: str,
        dtype: torch.dtype,
    ) -> ModelHandle:
        ckpt_path = self._checkpoint_path(model_type)
        if not ckpt_path.is_file():
            raise AppError(
                ErrorCode.WEIGHTS_MISSING,
                "模型权重缺失",
                detail={"path": str(ckpt_path)},
            )
        text_emb_path = self._text_embedding_path(model_type, items_mode)
        if not text_emb_path.is_file():
            # main 槽位的官方嵌入文件随程序分发（约 350KB，请勿删除）；
            # plus 的 merlin_en.pt 同样随分发包提供（48KB），由官方英文 prompt
            # 配方生成（配方固定，可用 CLI 完全复现，不依赖任何私有标定）；
            # plus_scratch 等研究场景请用 CLI 显式生成（结果未经验证，仅供科研对照）。
            raise AppError(
                ErrorCode.WEIGHTS_MISSING,
                "文本嵌入文件缺失",
                detail={
                    "path": str(text_emb_path),
                    "items_mode": items_mode.value,
                    "hint": (
                        "main/plus 槽位的嵌入文件随程序分发，请从分发包恢复或联系管理员；"
                        "研究用途可执行 python -m radar.engine.text_embed "
                        f"--items {items_mode.value} --checkpoint {ckpt_path} "
                        f"--out {text_emb_path} 现算一份"
                        "（plus/merlin20 即官方英文 prompt 配方，可完全复现；"
                        "其他组合未经官方标定，仅供对照）"
                    ),
                },
            )

        # 整个构造过程都要在该上下文内：RADAR.__init__ 内部还会按
        # CONFIGS_ROOT 加载 tokenizer，脱离上下文会退回相对路径 "../ckpt"，
        # 进而被 transformers 当成 HF repo id 而报错。
        # main 的目录解析结果与旧实现（CWD 下的 ../ckpt）完全一致，仅更健壮。
        with _bert_context(model_type, self.ckpt_dir):
            # main 逐字沿用旧路径（下载好的 bert-base-chinese 预训练权重）；
            # plus 只有英文 config.json、没有预训练 bin，但微调后的
            # text_encoder 权重完整随 plus ckpt 提供，故不加载预训练。
            text_encoder = XBertEncoder.from_config(
                {}, from_pretrained=(model_type == ModelType.MAIN)
            )
            vision_encoder = VisionBranch()
            model = RADAR(image_encoder=vision_encoder, text_encoder=text_encoder)

        ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
        model.load_state_dict(ckpt["model"], strict=False)
        model.eval()
        model.to(device=device, dtype=dtype)

        # 按当前测试项集合加载文本嵌入（plus+merlin20 → 20 项 merlin 嵌入）
        raw_text_feat = torch.load(text_emb_path, map_location="cpu")
        items, _english = items_spec(items_mode)
        missing = [k for k in items if k not in raw_text_feat]
        if missing:
            raise AppError(
                ErrorCode.WEIGHTS_MISSING,
                "文本嵌入缺少测试项",
                detail={
                    "path": str(text_emb_path),
                    "items_mode": items_mode.value,
                    "missing": missing[:10],
                    "missing_count": len(missing),
                },
            )
        text_feat_dict = {k: v.to(device=device, dtype=dtype) for k, v in raw_text_feat.items()}
        pad_func = transforms.DivisiblePadd(
            keys=["image", "label"], k=32, mode="constant",
            constant_values=0, method="end",
        )

        num_bytes = sum(p.numel() * p.element_size() for p in model.parameters())
        return ModelHandle(
            key=key,
            model_type=model_type,
            items_mode=items_mode,
            device=device,
            dtype=dtype,
            pad_func=pad_func,
            model=model,
            text_feat_dict=text_feat_dict,
            bytes=num_bytes,
        )

    def loaded_models(self) -> list[LoadedModel]:
        return [
            LoadedModel(
                key=h.key,
                model_type=h.model_type,
                items_mode=h.items_mode,
                device=h.device,
                dtype=dtype_name(h.dtype),
                bytes=h.bytes,
                last_used=h.last_used,
            )
            for h in self._cache.values()
        ]

    def keys(self) -> list[str]:
        return list(self._cache.keys())

    # ═══════════════════ 显存管理 ═══════════════════
    def unload(self, predicate: Callable[[ModelHandle], bool] | None = None) -> int:
        """卸载命中的模型句柄并释放 CUDA 缓存，返回卸载数量。

        显存增长的根因：cache 按 (model_type, items_mode, device, dtype) 记账，
        换精度/换模型会各自驻留一份权重。三个回收入口：
        ① 任务结束后清碎片缓存（services.execute 的 finally）；
        ② 空闲超时自动卸载（app 的后台循环调 unload_idle）；
        ③ 后台改模型配置或手动卸载（unload_all）。
        """
        import gc

        with self._lock:
            hit = [k for k, h in self._cache.items() if predicate is None or predicate(h)]
            for k in hit:
                self._cache.pop(k, None)
        if hit:
            gc.collect()
            try:
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:  # noqa: BLE001 - CPU 环境或 CUDA 已销毁时忽略
                pass
        return len(hit)

    def unload_all(self) -> int:
        return self.unload(None)

    def unload_idle(self, max_idle_s: float) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_idle_s)
        return self.unload(lambda h: (h.last_used or h.loaded_at) < cutoff)
