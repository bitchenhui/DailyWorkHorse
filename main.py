#!/usr/bin/env python3
"""GitHub Trending Top10 → LLM 精选解读 → PushPlus 微信推送."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


def _load_dotenv() -> None:
    """可选加载本地 .env（不覆盖已有环境变量）。"""
    path = Path(__file__).resolve().parent / ".env"
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


_load_dotenv()

TRENDING_URL = "https://github.com/trending?since=daily"
PUSHPLUS_URL = "https://www.pushplus.plus/send"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
CST = timezone(timedelta(hours=8))


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value.strip() == "":
        raise SystemExit(f"缺少环境变量: {name}")
    return value.strip()


def parse_int(text: str | None) -> int:
    if not text:
        return 0
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def fetch_trending(limit: int = 10) -> list[dict[str, Any]]:
    resp = requests.get(
        TRENDING_URL,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        timeout=30,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    repos: list[dict[str, Any]] = []

    for card in soup.select("article.Box-row"):
        link = card.select_one("h2 a")
        if not link or not link.get("href"):
            continue
        href = link["href"].strip()
        full_name = href.strip("/")
        desc_el = card.select_one("p")
        lang_el = card.select_one('[itemprop="programmingLanguage"]')
        muted = card.select("a.Link--muted")
        today_el = card.select_one("span.d-inline-block.float-sm-right")
        if today_el is None:
            # GitHub 偶发改 class，兜底找含 "stars today" 的节点
            for span in card.select("span"):
                if "star" in span.get_text(" ", strip=True).lower() and "today" in span.get_text(
                    " ", strip=True
                ).lower():
                    today_el = span
                    break

        stars_total = parse_int(muted[0].get_text(" ", strip=True)) if muted else 0
        forks_total = parse_int(muted[1].get_text(" ", strip=True)) if len(muted) >= 2 else 0
        stars_today = parse_int(today_el.get_text(" ", strip=True) if today_el else "0")

        repos.append(
            {
                "rank": len(repos) + 1,
                "full_name": full_name,
                "url": urljoin("https://github.com", href),
                "description": desc_el.get_text(" ", strip=True) if desc_el else "",
                "language": lang_el.get_text(strip=True) if lang_el else "Unknown",
                "stars_total": stars_total,
                "forks_total": forks_total,
                "stars_today": stars_today,
            }
        )
        if len(repos) >= limit:
            break

    if not repos:
        raise RuntimeError("未能解析到任何 Trending 仓库，页面结构可能已变化")
    return repos


def _is_anthropic_base(api_base: str) -> bool:
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


def llm_deep_dive(top3: list[dict[str, Any]]) -> str:
    api_key = env("LLM_API_KEY")
    api_base = env("LLM_API_BASE").rstrip("/")
    model = env("LLM_MODEL")

    payload_repos = [
        {
            "rank": r["rank"],
            "full_name": r["full_name"],
            "url": r["url"],
            "description": r["description"],
            "language": r["language"],
            "stars_total": r["stars_total"],
            "stars_today": r["stars_today"],
        }
        for r in top3
    ]

    system = (
        "你是资深开源观察编辑。根据给定的 GitHub Trending 仓库信息，"
        "为前三名各写一段中文深度解读。要求：\n"
        "1. 每条包含：它是什么、为什么今天火、适合谁关注\n"
        "2. 语气专业简洁，少营销腔，不要编造不存在的功能\n"
        "3. 每条 80–140 字，使用 Markdown\n"
        "4. 格式严格如下：\n"
        "### N. owner/repo（+日增★）\n"
        "- **是什么**：...\n"
        "- **为何火**：...\n"
        "- **适合谁**：...\n"
    )
    user = "今日 Top3 数据：\n" + json.dumps(payload_repos, ensure_ascii=False, indent=2)

    # MiniMax / Anthropic 兼容：POST {base}/v1/messages
    # OpenAI 兼容：POST {base}/chat/completions
    if _is_anthropic_base(api_base):
        url = f"{api_base}/v1/messages"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": 2048,
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
        if _is_anthropic_base(api_base):
            return _extract_anthropic_text(data)
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, RuntimeError) as exc:
        raise RuntimeError(f"LLM 响应格式异常: {data}") from exc


def build_message(repos: list[dict[str, Any]], deep_dive: str) -> tuple[str, str]:
    today = datetime.now(CST).strftime("%Y-%m-%d")
    title = f"🔥 GitHub 今日热榜 · {today}"

    lines = [
        f"# {title}",
        "",
        "> 数据来源：[GitHub Trending · Today](https://github.com/trending?since=daily)",
        "",
        "## 深度精选 · Top3",
        "",
        deep_dive,
        "",
        "## 完整榜单 · Top10",
        "",
    ]
    for r in repos:
        desc = r["description"] or "（暂无简介）"
        lines.append(
            f"{r['rank']}. [{r['full_name']}]({r['url']})  "
            f"**+{r['stars_today']}★** · {r['language']} · 总计 {r['stars_total']:,}★  \n"
            f"   {desc}"
        )
        lines.append("")

    lines.extend(
        [
            "---",
            "_由 wechatInforPush 自动推送 · PushPlus_",
        ]
    )
    return title, "\n".join(lines)


def push_wechat(title: str, content: str) -> None:
    token = env("PUSHPLUS_TOKEN")
    resp = requests.post(
        PUSHPLUS_URL,
        json={
            "token": token,
            "title": title,
            "content": content,
            "template": "markdown",
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


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(enc, errors="replace").decode(enc, errors="replace"))


def main() -> int:
    _safe_print("抓取 GitHub Trending …")
    repos = fetch_trending(10)
    for r in repos:
        _safe_print(
            f"  #{r['rank']} {r['full_name']} +{r['stars_today']} "
            f"({r['language']})"
        )

    _safe_print("生成 Top3 深度解读 …")
    deep_dive = llm_deep_dive(repos[:3])

    title, content = build_message(repos, deep_dive)
    _safe_print("--- 消息预览 ---")
    _safe_print(content[:1200])
    _safe_print("---")

    _safe_print("推送到微信 …")
    push_wechat(title, content)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 — 定时任务需要明确失败退出码
        try:
            print(f"ERROR: {exc}", file=sys.stderr)
        except UnicodeEncodeError:
            print(f"ERROR: {exc!r}", file=sys.stderr)
        raise SystemExit(1)
