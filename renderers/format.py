"""各平台共用的数值格式化。"""

from __future__ import annotations


def fmt_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".rstrip("0").rstrip(".")
    if n >= 10_000:
        return f"{n / 1000:.0f}k"
    if n >= 1000:
        return f"{n / 1000:.1f}k".rstrip("0").rstrip(".")
    return str(n)


def fmt_delta(n: int) -> str:
    return f"+{fmt_count(n)}★"
