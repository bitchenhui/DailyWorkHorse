#!/usr/bin/env python3
"""GitHub Trending 日榜 → LLM 解读 → 公众号与小红书成稿 → 微信通知.

入口只负责解析命令行与错误退出码，实际逻辑见 ``pipeline`` 与各分层模块。
"""

from __future__ import annotations

import sys
import traceback

import pipeline
from core.config import load_dotenv

load_dotenv()


def main() -> int:
    return pipeline.run(dry_run="--dry-run" in sys.argv)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 — 定时任务需要明确失败退出码
        try:
            print(f"ERROR: {exc}", file=sys.stderr)
            traceback.print_exc()
        except UnicodeEncodeError:
            print(f"ERROR: {exc!r}", file=sys.stderr)
        raise SystemExit(1)
