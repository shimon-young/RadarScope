#!/usr/bin/env python
"""下载官方模型权重到 ckpt/（默认走国内镜像 hf-mirror.com）。

官方仓库：radar-generalist/RADAR（HuggingFace）。仓库根目录即 ckpt 目录，
因此文件名可直接写 `checkpoint_radar_pretrain.pth`、`bert-base-chinese/*`。

用法：
    python scripts/download_weights.py                  # main 最小可用集（默认）
    python scripts/download_weights.py --preset plus    # plus 微调权重
    python scripts/download_weights.py --preset all     # main + plus
    python scripts/download_weights.py --include-patterns checkpoint_radar_pretrain.pth
    python scripts/download_weights.py --dry-run        # 只看要下什么，不联网

服务端管理页的「下载」按钮调用的是同一个脚本（/api/admin/model/download），
只是把 --include-patterns 换成页面上选定的文件。

断点续传：已下载完成的文件会跳过，中断后重跑本脚本即可继续。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ID = "radar-generalist/RADAR"
MIRROR = "https://hf-mirror.com"

# 最小可用集：main 跑起来必需的权重 + 中文 BERT。
# 文本嵌入 infer_text_embedding_*.pt 只随分发包提供（官方 HF 仓库不含这两个文件，
# 它们在官方 GitHub 仓库的 ckpt/ 下），因此不在下载清单内。
PRESET_MAIN = [
    "checkpoint_radar_pretrain.pth",
    "bert-base-chinese/*",
]
# plus 微调权重；其文本嵌入 ckpt/infer_text_embedding_merlin_en.pt 随分发包提供
PRESET_PLUS = [
    "checkpoint_radar_plus_finetuned_on_merlin.pth",
]
PRESETS: dict[str, list[str]] = {
    "main": PRESET_MAIN,
    "plus": PRESET_PLUS,
    "all": PRESET_MAIN + PRESET_PLUS,
}

HERE = Path(__file__).resolve().parent
DEFAULT_LOCAL_DIR = HERE.parent.parent / "ckpt"  # <repo root>/ckpt


def _human(n: int | None) -> str:
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}GB"


def _expand(patterns: list[str]) -> list[str]:
    """把精确文件名挑出来用于落盘校验。

    带通配符的条目（`bert-base-chinese/*`）无法在下载前展开成文件名，
    因此改为下载后用远端清单核对，见 _verify_present()。
    """
    return [p for p in patterns if "*" not in p]


# 每个通配符预设展开后必须存在的关键文件。缺任何一个都算下载失败——
# 官方目录里除权重外还有 config/vocab 等小文件，缺了它们
# transformers 的 from_pretrained() 会在真正加载时才报错。
WILDCARD_REQUIRED: dict[str, list[str]] = {
    "bert-base-chinese/*": [
        "bert-base-chinese/config.json",
        "bert-base-chinese/pytorch_model.bin",
        "bert-base-chinese/vocab.txt",
    ],
}


def _verify_present(local_dir: Path, patterns: list[str]) -> list[str]:
    """核对落盘结果，返回缺失文件列表。"""
    missing: list[str] = []
    for name in _expand(patterns):
        if not (local_dir / name).is_file():
            missing.append(name)
    for pattern in patterns:
        if "*" in pattern:
            base = pattern.split("*", 1)[0].rstrip("/")
            for name in WILDCARD_REQUIRED.get(pattern, []):
                if not (local_dir / name).is_file():
                    missing.append(name)
            # 目录整体是否存在（无关键文件清单时至少保证目录建了）
            if not (local_dir / base).is_dir() and pattern not in WILDCARD_REQUIRED:
                missing.append(f"{base}/ (目录未创建)")
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="下载 RADAR 官方模型权重")
    parser.add_argument("--local-dir", default=str(DEFAULT_LOCAL_DIR),
                        help=f"下载目录（默认 {DEFAULT_LOCAL_DIR}）")
    parser.add_argument("--repo-id", default=REPO_ID, help=f"官方仓库（默认 {REPO_ID}）")
    parser.add_argument("--endpoint", default=None,
                        help=f"HF 端点，默认环境变量 HF_ENDPOINT 或 {MIRROR}")
    parser.add_argument("--preset", choices=sorted(PRESETS), default=None,
                        help="预置组合：main（默认）/ plus / all")
    parser.add_argument("--include-patterns", nargs="*", default=None,
                        help="精确文件名或目录前缀（bert-base-chinese/*），优先于 --preset")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不下载")
    args = parser.parse_args(argv)

    patterns = args.include_patterns or PRESETS[args.preset or "main"]
    local_dir = Path(args.local_dir).resolve()
    endpoint = args.endpoint or os.environ.get("HF_ENDPOINT") or MIRROR

    print(f"repo      : {args.repo_id}")
    print(f"endpoint  : {endpoint}")
    print(f"local dir : {local_dir}")
    print("patterns  :")
    for p in patterns:
        print(f"  - {p}")

    if args.dry_run:
        for name in _expand(patterns):
            f = local_dir / name
            print(f"  [plan] {name}: {'already present' if f.is_file() else 'to download'}")
        for pattern in patterns:
            if "*" in pattern:
                req = WILDCARD_REQUIRED.get(pattern, [])
                print(f"  [plan] {pattern} -> 需核对 {len(req)} 个关键文件:")
                for name in req:
                    f = local_dir / name
                    print(f"           {'present' if f.is_file() else 'to download'}  {name}")
        return 0

    # 推理服务本身离线运行（HF_HUB_OFFLINE=1），这里必须显式解除
    os.environ["HF_ENDPOINT"] = endpoint
    os.environ["HF_HUB_OFFLINE"] = "0"
    os.environ.pop("HF_HUB_DISABLE_PROGRESS_BARS", None)

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("[ERROR] 缺少 huggingface_hub，请先运行 setup_env 安装依赖", file=sys.stderr)
        return 1

    local_dir.mkdir(parents=True, exist_ok=True)
    try:
        snapshot_path = snapshot_download(
            repo_id=args.repo_id,
            repo_type="model",
            local_dir=str(local_dir),
            allow_patterns=patterns,
        )
    except Exception as exc:  # noqa: BLE001 - 网络/镜像问题原样上报
        print(f"[ERROR] 下载失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        print("        若为网络问题，可换镜像后重试：", file=sys.stderr)
        print(f"        HF_ENDPOINT={MIRROR} python scripts/download_weights.py", file=sys.stderr)
        return 1

    print(f"\ndownloaded to: {snapshot_path}")

    missing = _verify_present(local_dir, patterns)
    if missing:
        print("[ERROR] 以下文件下载后未找到：", file=sys.stderr)
        for n in missing:
            print(f"  - {n}", file=sys.stderr)
        print("        网络中断时重跑本命令即可续传。", file=sys.stderr)
        return 1

    print("\nverified:")
    for name in _expand(patterns):
        f = local_dir / name
        print(f"  OK {name} ({_human(f.stat().st_size)})")
    for pattern in patterns:
        if "*" in pattern:
            for name in WILDCARD_REQUIRED.get(pattern, []):
                f = local_dir / name
                print(f"  OK {name} ({_human(f.stat().st_size)})")

    # 文本嵌入随分发包提供，官方 HF 仓库没有；缺失时给出恢复方式
    need_embeddings = ["infer_text_embedding_radar.pt"]
    if any("plus" in p for p in patterns):
        need_embeddings.append("infer_text_embedding_merlin_en.pt")
    for name in need_embeddings:
        f = local_dir / name
        if f.is_file():
            print(f"  OK {name} ({_human(f.stat().st_size)})")
        else:
            print(f"  [MISSING] {name} — 官方 HF 仓库不提供该文件，请从分发包恢复，")
            print("            或从官方 GitHub 仓库 alibaba-damo-academy/damo-radar 的 ckpt/ 下载")
    return 0


if __name__ == "__main__":
    sys.exit(main())
