"""把本次运行的结果拼成邮件正文，供 Actions 的发信步骤读取。

    python -m tools.mailreport

单独一个步骤而不是并进 ``main.py``：生成失败时 main.py 根本走不到收尾，
而那封邮件恰恰是最该发出去的一封。
"""

from __future__ import annotations

import os
from pathlib import Path

from channels import report
from core.config import DIST_DIR

OUTPUT = Path("run-report.html")


def main() -> int:
    subject, body = report.build_email(
        DIST_DIR,
        os.environ.get("PUBLIC_DRAFT_URL", "").strip(),
        os.environ.get("RUN_URL", "").strip(),
    )
    OUTPUT.write_text(body, encoding="utf-8")

    # 主题经 step output 交给发信步骤；本地跑没有这个文件，打印出来即可。
    channel = os.environ.get("GITHUB_OUTPUT")
    if channel:
        with open(channel, "a", encoding="utf-8") as handle:
            handle.write(f"subject={subject}\n")
    print(subject)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
