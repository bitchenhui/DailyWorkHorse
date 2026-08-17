"""T0 通知：经 PushPlus 公众号推一条微信消息。"""

from __future__ import annotations

import requests

from core.config import env

PUSHPLUS_URL = "https://www.pushplus.plus/send"


def send(title: str, content: str) -> None:
    token = env("PUSHPLUS_TOKEN")
    resp = requests.post(
        PUSHPLUS_URL,
        json={
            "token": token,
            "title": title,
            "content": content,
            "template": "html",
            "channel": "wechat",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    # PushPlus: code == 200 表示成功
    if str(data.get("code")) != "200":
        raise RuntimeError(f"PushPlus 推送失败: {data}")
    print("PushPlus 推送成功:", data.get("msg", "ok"))
