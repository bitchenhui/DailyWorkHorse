"""把本次运行的结果推到 Bark（iOS App），替代原先的邮件报告。

    python -m tools.bark

单独一个步骤而不是并进 ``main.py``：生成失败时 main.py 根本走不到收尾，
而那条推送恰恰是最该发出去的一条。

BARK_URL 是 Bark 服务地址带设备 key（形如 https://api.day.app/<key>），
配在仓库 Secrets 里；未配置时安静跳过，不影响运行结果。
"""

from __future__ import annotations

import json
import os
import urllib.request

from channels import report
from core.config import DIST_DIR

TIMEOUT = 15


def send(url: str, payload: dict) -> None:
    """POST JSON 到 Bark。返回体 ``{"code":200}`` 之外一律视为失败。"""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        body = json.loads(response.read().decode("utf-8"))
        if body.get("code") != 200:
            raise RuntimeError(f"Bark 返回异常: {body}")


def main() -> int:
    url = os.environ.get("BARK_URL", "").strip()
    if not url:
        print("未配置 BARK_URL，跳过 Bark 推送")
        return 0

    payload = report.build_push(
        DIST_DIR,
        os.environ.get("PUBLIC_DRAFT_URL", "").strip(),
        os.environ.get("RUN_URL", "").strip(),
    )
    print(f"Bark → {payload['title']}")
    send(url, payload)
    print(f"Bark 推送成功（level={payload['level']}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
