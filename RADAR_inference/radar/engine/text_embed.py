"""文本特征缓存（infer_text_embedding_*.pt）的生成 CLI。

模型推理时需要一份「病症 → 特征向量」的缓存，结构与用途：

- 内容：{中文项名: Tensor[2, 256]}，row0=阴性锚、row1=阳性提示词，两行 L2 归一化；
  推理时对两行做 2 类 softmax，取 index1 为阳性概率。
- 项名用中文，仅作索引与展示；向量由英文提示词算出——plus 的文本编码器是
  bert-base-uncased（词表 30522），在英文 MERLIN 报告上训练。
  官方训练指南明确推理使用 MERLIN 官方发布的提示词，本 CLI 即按此配方计算。
- 缓存与权重一一对应：换权重就要重新生成，不能跨权重复用
  （架构虽相同，文本编码器参数不同 → 文本空间不同）。

随分发包提供 plus 的 `infer_text_embedding_merlin_en.pt`；缺失或换权重时用本 CLI 重建：

    python -m radar.engine.text_embed --items merlin20 \
        --checkpoint ../ckpt/checkpoint_radar_plus_finetuned_on_merlin.pth \
        --out ../ckpt/infer_text_embedding_merlin_en.pt

    python -m radar.engine.text_embed --items merlin20 \
        --checkpoint ../ckpt/checkpoint_radar_plus.pth \
        --out ../ckpt/infer_text_embedding_plus_scratch.pt
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import torch
import torch.nn.functional as F

from ..schemas import ItemsMode, ModelType
from .items import items_spec

# items_mode → 文本编码器的语言上下文（与 ModelRegistry._bert_context 同一约定）
_BERT_NAME_OF: dict[str, str] = {
    ModelType.MAIN.value: "bert-base-chinese",
    ModelType.PLUS.value: "bert-base-uncased",
    ModelType.PLUS_SCRATCH.value: "bert-base-uncased",
}

# items_mode → 缺省 checkpoint 文件名（与 ModelRegistry._checkpoint_path 一致）
_CHECKPOINT_OF: dict[str, str] = {
    ModelType.MAIN.value: "checkpoint_radar_pretrain.pth",
    ModelType.PLUS.value: "checkpoint_radar_plus_finetuned_on_merlin.pth",
    ModelType.PLUS_SCRATCH.value: "checkpoint_radar_plus.pth",
}


def _build_model(ckpt_path: Path, items_mode: ItemsMode, ckpt_dir: Path):
    """按 loader 的同一约定构建并装载 RADAR（只需 tokenizer/text_encoder/text_proj）。"""
    from inference_demo import RADAR, VisionBranch  # noqa: E402 - 依赖 RADAR_inference 根目录
    from dynamic_network_architectures.med import XBertEncoder  # noqa: E402

    model_type = (
        ModelType.MAIN if items_mode == ItemsMode.RADAR146 else ModelType.PLUS
    )
    saved = {k: os.environ.get(k) for k in ("BERT_NAME", "CONFIGS_ROOT")}
    os.environ["BERT_NAME"] = _BERT_NAME_OF[model_type.value]
    os.environ["CONFIGS_ROOT"] = str(ckpt_dir)
    try:
        # main 用下载好的中文预训练权重初始化；merlin20 系权重完整随 ckpt 提供，
        # 不加载预训练（与 ModelRegistry._load 逐字一致）。
        text_encoder = XBertEncoder.from_config(
            {}, from_pretrained=(items_mode == ItemsMode.RADAR146)
        )
        model = RADAR(image_encoder=VisionBranch(), text_encoder=text_encoder)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    model.load_state_dict(ckpt["model"], strict=False)
    model.eval()
    return model


def generate_text_embedding(
    ckpt_path: Path,
    items_mode: ItemsMode,
    out_path: Path,
    ckpt_dir: Path,
) -> dict[str, int]:
    """为一个 checkpoint 现算测试项文本特征缓存并写盘。

    返回统计 {"items": N}；生成失败抛出的异常由调用方决定如何呈现。
    """
    from .items import split_finding_key  # noqa: F401 - 保留给调用方排查用

    t0 = time.perf_counter()
    items, english_mapping = items_spec(items_mode)

    # 编码器语言与 checkpoint 的词表强绑定，先做一致性预防检查：
    # 中文词表(21128)配 radar146，英文词表(30522)配 merlin20 系。
    expected_vocab = 21128 if items_mode == ItemsMode.RADAR146 else 30522

    model = _build_model(ckpt_path, items_mode, ckpt_dir)
    vocab = model.text_encoder.config.vocab_size
    if vocab != expected_vocab:
        raise ValueError(
            f"checkpoint 词表({vocab})与 {items_mode.value} 所需词表({expected_vocab})不符："
            "该权重不能用于此测试项集合"
        )

    # 提示词与行布局按官方推理脚本（infer_plus_bf16.build_text_feat_dict*）逐字对齐：
    # - radar146：每项两行 = [normal, 病症英文名(保留原大小写，剥掉器官前缀)]
    # - merlin20：merlin_prompts 的正/负短语组各自取均值 → [负例均值, 正例均值]
    # 推理侧对两行做 2 类 softmax 取 index1 为阳性，row0=阴性锚/row1=阳性 与之一致。
    if items_mode == ItemsMode.RADAR146:
        item_texts = [(k, [english_mapping[k].split("_", 1)[-1], "normal"]) for k in items]
    else:
        from merlin_prompts import disease_prompts  # noqa: E402 - RADAR_inference 根目录
        from items_merlin20 import MERLIN20_PROMPT_KEYS  # noqa: E402

        item_texts = []
        for k in items:
            prompts = disease_prompts[MERLIN20_PROMPT_KEYS[k]]
            item_texts.append(
                (
                    k,
                    list(prompts.positive_prompts) + list(prompts.negative_prompts),
                    len(prompts.positive_prompts),
                )
            )

    table: dict[str, torch.Tensor] = {}
    with torch.inference_mode():
        for entry in item_texts:
            k, texts, n_pos = entry[0], entry[1], (entry[2] if len(entry) > 2 else 1)
            tok = model.tokenizer(
                texts,
                padding="max_length",
                truncation=True,
                max_length=100,
                return_tensors="pt",
            )
            h = model.text_encoder.forward_text(tok).last_hidden_state
            feat = F.normalize(model.text_proj(h[:, 0]), dim=-1)
            if n_pos == 1 and len(texts) == 2:  # radar146：[disease, normal] → [normal, disease]
                row = torch.cat([feat[1:2], feat[0:1]], dim=0)
            else:  # merlin20：正/负短语各自取均值
                pos = feat[:n_pos].mean(0, keepdim=True)
                neg = feat[n_pos:].mean(0, keepdim=True)
                row = torch.cat([neg, pos], dim=0)
            table[k] = row

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    torch.save(table, tmp)
    tmp.replace(out_path)

    dt = time.perf_counter() - t0
    print(f"[text-embed] 生成 {out_path.name}: {len(items)} 项, {dt:.1f}s")
    return {"items": len(items)}


def main(argv: list[str] | None = None) -> int:
    import argparse

    from ..config import CKPT_DIR

    ap = argparse.ArgumentParser(description="生成 RADAR 测试项文本特征缓存")
    ap.add_argument("--items", choices=[m.value for m in ItemsMode], required=True)
    ap.add_argument("--checkpoint", default=None, help="缺省按 items_mode 取对应槽位权重")
    ap.add_argument("--out", default=None, help="缺省写到 ckpt 目录的约定文件名")
    ap.add_argument("--ckpt-dir", default=str(CKPT_DIR))
    args = ap.parse_args(argv)

    items_mode = ItemsMode(args.items)
    ckpt_dir = Path(args.ckpt_dir)
    if args.checkpoint:
        ckpt_path = Path(args.checkpoint)
    else:
        # CLI 缺省按"项集合 → 对应槽位权重"推断
        model_type = ModelType.MAIN if items_mode == ItemsMode.RADAR146 else ModelType.PLUS
        ckpt_path = ckpt_dir / _CHECKPOINT_OF[model_type.value]
    if args.out:
        out_path = Path(args.out)
    else:
        # 缺省输出名 = 运行时实际使用的文件名（plus 槽位 = merlin_en.pt）。
        # 官方同名 merlin.pt 属「中文 BERT + main」空间，留给对照，不覆盖。
        name = (
            "infer_text_embedding_radar.pt"
            if items_mode == ItemsMode.RADAR146
            else "infer_text_embedding_merlin_en.pt"
        )
        out_path = ckpt_dir / name

    if not ckpt_path.is_file():
        print(f"[text-embed] 权重不存在: {ckpt_path}", file=sys.stderr)
        return 1
    generate_text_embedding(ckpt_path, items_mode, out_path, ckpt_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
