"""离线守卫：证明「模型加载 + 完整推理」全程零外网请求。

RadarScope 定位是本地/局域网部署的桌面应用，所有权重、词表、BERT 均随仓库本地提供，
运行期不允许有任何外网访问（国内网络下联网尝试会表现为长时间超时卡顿）。

原理：hook socket 层（覆盖 requests / urllib3 / transformers / huggingface_hub 等全部上层），
      记录目标地址非本机/局域网的连接；同时清除代理环境变量，模拟"部署机裸网络"的最坏情况。

用法：
    python scripts/netprobe.py                 # 默认测 main（146 项）
    python scripts/netprobe.py plus            # 测 plus（20 项）

退出码：0 = 零外网（通过）；1 = 发现外部连接（失败）。
"""

from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../RADAR_inference/scripts
RADAR_DIR = HERE.parent                          # .../RADAR_inference
ROOT = RADAR_DIR.parent                          # 仓库根

# ---------------------------------------------------------------- 网络探针
_connections: list[tuple[str, int, str]] = []
_stage = "import"
_real_connect = socket.socket.connect
_real_create = socket.create_connection


def _is_local(host: str) -> bool:
    if host in ("127.0.0.1", "::1", "localhost", ""):
        return True
    return host.startswith(
        ("10.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.", "172.2", "172.3", "169.254.")
    )


def _record(addr, stage: str) -> None:
    try:
        host, port = str(addr[0]), int(addr[1])
    except Exception:
        host, port = str(addr), 0
    if not _is_local(host):
        _connections.append((host, port, stage))


def patched_connect(self, addr):
    _record(addr, _stage)
    return _real_connect(self, addr)


def patched_create_connection(addr, *args, **kwargs):
    _record(addr, _stage)
    return _real_create(addr, *args, **kwargs)


socket.socket.connect = patched_connect
socket.create_connection = patched_create_connection

# 清除代理：部署机通常没有代理，若代码真想联网会直接超时；有代理时则会被上面捕获
for _k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(_k, None)

sys.path.insert(0, str(RADAR_DIR))

# ---------------------------------------------------------------- 主体
model_type = sys.argv[1] if len(sys.argv) > 1 else "main"
items_mode = sys.argv[2] if len(sys.argv) > 2 else ("radar146" if model_type == "main" else "merlin20")

_stage = "import"
import torch  # noqa: E402

from radar.engine.items import items_spec  # noqa: E402
from radar.engine.loader import ModelRegistry, resolve_device  # noqa: E402
from radar.engine.runner import RunConfig, run_inference  # noqa: E402
from radar.schemas import ItemsMode, ModelType  # noqa: E402

print(f"=== 离线守卫：model={model_type} items_mode={items_mode} ===", flush=True)

_stage = "load_model"
device = resolve_device("auto")
dtype = torch.bfloat16 if device == "cuda" else torch.float32
t0 = time.perf_counter()
engine = ModelRegistry(ROOT / "ckpt").acquire(
    ModelType(model_type), ItemsMode(items_mode), device, dtype
)
print(f"[加载] {time.perf_counter() - t0:.2f}s  device={engine.device} dtype={engine.dtype}", flush=True)

_stage = "infer"
_demo = ROOT / "data" / "demo_cases"
if not any(_demo.glob("*.nii.gz")):
    print(
        f"缺少 demo 病例：{_demo}\n"
        "该数据由官方仓库 alibaba-damo-academy/damo-radar 的 data/demo_cases 提供，"
        "不随发布包分发；也可放入任意一例自己的 .nii.gz。",
        file=sys.stderr,
    )
    raise SystemExit(2)
csv_path = HERE / "_netprobe_case.csv"
csv_path.write_text("path,Anonymized Patient ID\nAC423ccbe.nii.gz,AC423ccbe\n", encoding="utf-8")
seg_path = HERE / "_netprobe_seg.nii.gz"
_item_mode = ItemsMode(items_mode)
_items, _english = items_spec(_item_mode)
cfg = RunConfig(
    input_dir=_demo,
    csv_path=csv_path,
    seg_path=seg_path,
    device=engine.device,
    dtype=engine.dtype,
    test_items=(None if _item_mode == ItemsMode.RADAR146 else _items),
    english_mapping=(None if _item_mode == ItemsMode.RADAR146 else _english),
)
t0 = time.perf_counter()
res = run_inference(engine, cfg)
print(
    f"[推理] {time.perf_counter() - t0:.2f}s  rows={len(res.rows)}  windows={res.num_windows}",
    flush=True,
)

csv_path.unlink(missing_ok=True)
seg_path.unlink(missing_ok=True)

# ---------------------------------------------------------------- 结论
print("\n=== 外部网络请求汇总 ===", flush=True)
if not _connections:
    print("PASS: 全程 0 次对外网连接 —— 纯离线可运行", flush=True)
    raise SystemExit(0)

seen: dict[tuple[str, int, str], int] = {}
for c in _connections:
    seen[c] = seen.get(c, 0) + 1
for (host, port, stage), cnt in sorted(seen.items(), key=lambda x: -x[1]):
    print(f"FAIL: {host}:{port}  阶段={stage}  次数={cnt}", flush=True)
raise SystemExit(1)
