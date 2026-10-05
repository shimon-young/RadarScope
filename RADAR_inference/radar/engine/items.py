"""
测试项 / 器官的唯一数据源。

- ORGANS / ORGANS_EN：36 个分割器官（label 1..36，0 为背景），顺序与
  `inference_demo.py` 的 `DataFolder.organs` 严格一致，**顺序不可更改**（分割通道索引依赖它）。
- TEST_ITEMS / ENGLISH_MAPPING：146 项"器官_病症"，从 `items146.py` 导入（唯一副本）。

前端 `frontend/src/core/colors.ts` 的 ORGANS 必须与本文件一致。
"""

from __future__ import annotations

import os
import sys

# RADAR_inference/radar/engine/items.py → 上三级 = RADAR_inference
_RADAR_INF_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _RADAR_INF_DIR not in sys.path:
    sys.path.insert(0, _RADAR_INF_DIR)

from items146 import ENGLISH_MAPPING, TEST_ITEMS  # noqa: E402
from items_merlin20 import MERLIN20_ENGLISH, MERLIN20_ITEMS, MERLIN20_ORGANS  # noqa: E402

from ..schemas import ItemsMode  # noqa: E402

__all__ = [
    "ORGANS",
    "ORGANS_EN",
    "NUM_ORGANS",
    "LABEL_OF_ORGAN",
    "TEST_ITEMS",
    "ENGLISH_MAPPING",
    "MERLIN20_ITEMS",
    "MERLIN20_ENGLISH",
    "items_spec",
    "organs_of_items",
    "split_finding_key",
    "organ_of",
]

# ── 分割器官（顺序 = 分割通道 label-1，勿改）──
ORGANS: tuple[str, ...] = (
    "肾上腺", "主动脉", "竖脊肌", "脑", "锁骨", "大肠", "十二指肠", "食管", "面部", "股骨",
    "胆囊", "臀肌", "心脏", "髋关节", "肱骨", "髂动脉", "髂静脉", "髂腰肌", "下腔静脉", "肾",
    "肝", "肺", "胰腺", "门静脉", "肺动脉", "肋骨", "骶骨", "肩胛骨", "小肠", "脾",
    "胃", "气管", "膀胱", "颈椎", "腰椎", "胸椎",
)

ORGANS_EN: tuple[str, ...] = (
    "Adrenal gland", "Aorta", "Erector spinae muscle", "Brain", "Clavicle", "Large bowel",
    "Duodenum", "Esophagus", "Face", "Femur", "Gallbladder", "Gluteus muscle", "Heart",
    "Hip joint", "Humerus", "Iliac artery", "Iliac vena", "Iliopsoas muscle",
    "Inferior vena cava", "Kidney", "Liver", "Lung", "Pancreas", "Portal vein",
    "Pulmonary artery", "Rib", "Sacrum", "Scapula", "Small bowel", "Spleen", "Stomach",
    "Trachea", "Bladder", "Cervical vertebrae", "Lumbar vertebrae", "Thoracic vertebrae",
)

NUM_ORGANS = len(ORGANS)  # 36

LABEL_OF_ORGAN: dict[str, int] = {name: i + 1 for i, name in enumerate(ORGANS)}

assert len(ORGANS) == len(ORGANS_EN) == 36, "器官表必须为 36 项"
assert len(TEST_ITEMS) == len(ENGLISH_MAPPING) == 146, "146 项表数量不符"
assert len(MERLIN20_ITEMS) == len(MERLIN20_ENGLISH) == 20, "merlin20 项表数量不符"
assert set(MERLIN20_ORGANS).issubset(set(ORGANS)), "merlin20 的器官必须都在 36 器官表内"

# items_mode → (测试项元组, 英文映射)
_ITEMS_SPEC: dict[str, tuple[tuple[str, ...], dict[str, str]]] = {
    ItemsMode.RADAR146.value: (tuple(TEST_ITEMS), dict(ENGLISH_MAPPING)),
    ItemsMode.MERLIN20.value: (MERLIN20_ITEMS, dict(MERLIN20_ENGLISH)),
}


def items_spec(mode: "ItemsMode | str") -> tuple[tuple[str, ...], dict[str, str]]:
    """按 items_mode 返回（测试项, 英文映射）。未知模式按 radar146 处理。"""
    key = mode.value if isinstance(mode, ItemsMode) else str(mode)
    return _ITEMS_SPEC.get(key, _ITEMS_SPEC[ItemsMode.RADAR146.value])


def organs_of_items(items) -> list[str]:
    """测试项 → 参与评分的器官名去重列表（顺序稳定，源自 DataFolder.test_organs）。"""
    seen: dict[str, None] = {}
    for item in items:
        seen.setdefault(str(item).split("_")[0], None)
    return list(seen)


def split_finding_key(key: str) -> tuple[str, str]:
    """`"肝_肝囊肿"` → `("肝", "肝囊肿")`。

    已核实：146 个 key 的器官名内部不含下划线，split 一次是安全的。
    """
    organ, _, finding = key.partition("_")
    return organ, finding or organ


def organ_of(key: str) -> str:
    return split_finding_key(key)[0]
