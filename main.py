#!/usr/bin/env python3
"""GitHub Trending / A股资金流 / 人设主题 → 各平台成稿 → 微信通知.

入口只负责解析命令行与错误退出码，实际逻辑见 ``pipeline`` 与各分层模块。
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback

import pipeline
from core.config import load_dotenv

load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser(description="每日内容分发")
    parser.add_argument("--dry-run", action="store_true", help="跳过微信推送")
    parser.add_argument(
        "--topic",
        default="",
        help="今天想聊的主题（仅 xhs_topic 管线用）；不传则自动选题",
    )
    args = parser.parse_args()

    if args.topic.strip():
        os.environ["TOPIC_OVERRIDE"] = args.topic.strip()
    return pipeline.run(dry_run=args.dry_run)


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
