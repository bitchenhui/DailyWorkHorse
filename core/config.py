"""环境变量与项目路径。"""

from __future__ import annotations

import os
from datetime import timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "dist"
CST = timezone(timedelta(hours=8))


def load_dotenv() -> None:
    """可选加载本地 .env（不覆盖已有环境变量）。"""
    path = PROJECT_ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value.strip() == "":
        raise SystemExit(f"缺少环境变量: {name}")
    return value.strip()


PLATFORM_LABELS = {
    "wechat_mp": "微信公众号",
    "xhs": "小红书",
}
DEFAULT_PLATFORMS = ("wechat_mp", "xhs")
DEFAULT_TIER = "bundle"


def enabled_platforms() -> tuple[str, ...]:
    """由 ``ENABLED_PLATFORMS`` 控制启用哪些平台，逗号分隔，缺省全开。"""
    raw = os.environ.get("ENABLED_PLATFORMS", "").strip()
    if not raw:
        return DEFAULT_PLATFORMS
    names = tuple(item.strip() for item in raw.split(",") if item.strip())
    unknown = [name for name in names if name not in PLATFORM_LABELS]
    if unknown:
        raise SystemExit(
            f"ENABLED_PLATFORMS 含未知平台 {unknown}，"
            f"可选：{sorted(PLATFORM_LABELS)}"
        )
    return names or DEFAULT_PLATFORMS


def platform_tier(platform: str) -> str:
    """投递档位：bundle=成稿包，playwright=浏览器自动化，api=官方接口。"""
    return os.environ.get(
        f"{platform.upper()}_TIER", DEFAULT_TIER
    ).strip().lower() or DEFAULT_TIER
