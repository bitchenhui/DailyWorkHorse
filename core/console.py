"""控制台输出：兼容 Windows 终端的非 UTF-8 编码。"""

from __future__ import annotations

import sys


def safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(enc, errors="replace").decode(enc, errors="replace"))
