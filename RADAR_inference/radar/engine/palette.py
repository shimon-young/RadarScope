"""器官色板（后端下发的唯一来源，前端仅作兜底）。

必须与 `frontend/src/core/colors.ts` 的 ORGAN_COLORS 逐一一致：
索引即 label，索引 0 = 背景（黑），label i (1..36) = ORGANS[i-1]。
"""

from __future__ import annotations

from .items import ORGANS

BACKGROUND: tuple[int, int, int] = (0, 0, 0)

# 与前端 ORGAN_COLORS 逐一对齐
ORGAN_COLORS: tuple[tuple[int, int, int], ...] = (
    (0, 0, 0),
    (233, 30, 99), (76, 175, 80), (255, 235, 59), (33, 150, 243), (255, 152, 0),
    (156, 39, 176), (0, 188, 212), (255, 87, 34), (121, 85, 72), (63, 81, 181),
    (96, 125, 139), (255, 193, 7), (205, 220, 57), (175, 180, 43), (0, 150, 136),
    (33, 33, 33), (72, 52, 212), (255, 112, 67), (244, 67, 54), (139, 195, 74),
    (66, 165, 245), (255, 167, 38), (171, 71, 188), (102, 187, 106), (0, 137, 123),
    (255, 204, 128), (197, 225, 165), (255, 138, 101), (255, 83, 73), (229, 57, 53),
    (26, 35, 126), (158, 158, 158), (106, 27, 154), (46, 125, 50), (255, 183, 77),
    (3, 169, 244),
)

assert len(ORGAN_COLORS) == len(ORGANS) + 1 == 37, "色板必须覆盖背景 + 36 个器官"


def color_of_label(label: int) -> list[int]:
    """label 1..36 → RGB 列表；越界返回背景色。"""
    if 0 <= label < len(ORGAN_COLORS):
        return list(ORGAN_COLORS[label])
    return list(BACKGROUND)
