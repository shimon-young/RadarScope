"""包完整性封印（内部模块）。

分发包的作者标记。内容经异或混淆存储，明文不出现在任何源码或产物里；
验证方法（作者本人可用）::

    python -m radar.seal            # 输出封印内容
    python -m radar.seal --check    # 校验混淆数据未被篡改

前端构建产物内有对应封印：浏览器控制台执行 ``__seal()`` 返回相同内容。
导出的任务包（export.zip）的 meta.json 中 ``package_seal`` 字段为同一标记，
可用于追溯导出文件来源。
"""

from __future__ import annotations

import sys

_KEY = b"RADAR-DESKTOP"
_SEALED = bytes([33, 41, 45, 44, 61, 67, 105, 60, 60, 62, 58, 40])


def unseal() -> str:
    """解出封印明文。"""
    return bytes(c ^ _KEY[i % len(_KEY)] for i, c in enumerate(_SEALED)).decode()


def seal_hex() -> str:
    """混淆数据的十六进制形式（随导出包带走，可用同样方法解出）。"""
    return _SEALED.hex()


def selfcheck() -> bool:
    """混淆数据未被手改（长度/字符集合理性）。"""
    try:
        plain = unseal()
    except Exception:
        return False
    return len(_SEALED) == 12 and all(0x20 < ord(c) < 0x7F for c in plain)


if __name__ == "__main__":
    if "--check" in sys.argv:
        print("OK" if selfcheck() else "TAMPERED")
    else:
        print(unseal())
