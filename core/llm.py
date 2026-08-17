"""LLM 客户端：按 API Base 自动适配 Anthropic 与 OpenAI 两种接口风格。"""

from __future__ import annotations

import re
from typing import Any

import requests

from core.config import env


def is_anthropic_base(api_base: str) -> bool:
    return "anthropic" in api_base.lower()


def _extract_anthropic_text(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for block in data.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text") or ""
            if text:
                parts.append(text)
    if not parts:
        raise RuntimeError(f"Anthropic 响应无 text 块: {data}")
    return "\n".join(parts).strip()


def complete(system: str, user: str) -> str:
    api_key = env("LLM_API_KEY")
    api_base = env("LLM_API_BASE").rstrip("/")
    model = env("LLM_MODEL")

    # MiniMax / Anthropic 兼容：POST {base}/v1/messages
    # OpenAI 兼容：POST {base}/chat/completions
    if is_anthropic_base(api_base):
        url = f"{api_base}/v1/messages"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": 4096,
            "temperature": 0.4,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
    else:
        url = f"{api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "temperature": 0.4,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

    resp = requests.post(url, headers=headers, json=body, timeout=120)
    if resp.status_code >= 400:
        raise RuntimeError(f"LLM 调用失败 HTTP {resp.status_code}: {resp.text[:500]}")
    data = resp.json()
    try:
        if is_anthropic_base(api_base):
            return _extract_anthropic_text(data)
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, RuntimeError) as exc:
        raise RuntimeError(f"LLM 响应格式异常: {data}") from exc


def strip_code_fence(text: str) -> str:
    body = text.strip()
    if body.startswith("```"):
        body = re.sub(r"^```[a-zA-Z]*\s*", "", body)
        body = re.sub(r"\s*```$", "", body)
    return body.strip()
