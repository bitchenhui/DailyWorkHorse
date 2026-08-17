"""GitHub Trending 采集：聚合综合榜与主流语言榜，按今日新增 stars 重排。"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from core.console import safe_print
from core.models import RepoItem

TRENDING_URL = "https://github.com/trending?since=daily"
TRENDING_LANGUAGES = (
    "python",
    "typescript",
    "javascript",
    "go",
    "rust",
    "java",
    "c++",
    "shell",
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def parse_int(text: str | None) -> int:
    if not text:
        return 0
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def parse_trending_html(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
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
                "full_name": full_name,
                "url": urljoin("https://github.com", href),
                "description": desc_el.get_text(" ", strip=True) if desc_el else "",
                "language": lang_el.get_text(strip=True) if lang_el else "Unknown",
                "stars_total": stars_total,
                "forks_total": forks_total,
                "stars_today": stars_today,
            }
        )
    return repos


def merge_rank_repos(
    repos: list[dict[str, Any]], limit: int = 10
) -> list[dict[str, Any]]:
    """按仓库去重，并按日增 stars、总 stars 降序取 TopN。"""
    unique: dict[str, dict[str, Any]] = {}
    for repo in repos:
        name = str(repo.get("full_name") or "").lower()
        if not name:
            continue
        previous = unique.get(name)
        if previous is None or (
            repo.get("stars_today", 0),
            repo.get("stars_total", 0),
        ) > (
            previous.get("stars_today", 0),
            previous.get("stars_total", 0),
        ):
            unique[name] = repo.copy()

    ranked = sorted(
        unique.values(),
        key=lambda r: (r.get("stars_today", 0), r.get("stars_total", 0)),
        reverse=True,
    )
    top = ranked[:limit]
    for i, r in enumerate(top, start=1):
        r["rank"] = i
    return top


def _fetch_page(url: str, retries: int = 3) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Cache-Control": "no-cache",
                },
                timeout=30,
            )
            if resp.status_code in {429, 502, 503}:
                raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
            resp.raise_for_status()
            repos = parse_trending_html(resp.text)
            if repos:
                return repos
            # 空结果常见于被拦截的登录墙页，重试一次
            last_error = RuntimeError("页面未解析出仓库卡片")
        except (requests.RequestException, RuntimeError) as exc:
            last_error = exc
        time.sleep(1.2 * (attempt + 1))
    if last_error:
        raise last_error
    return []


def fetch(limit: int = 10) -> list[RepoItem]:
    """聚合综合榜和主流语言榜，按日增 stars 严格降序取 TopN。

    GitHub 综合 Trending 有时少于 10 条。语言榜用于扩大候选池，不改变
    排序口径；最终仍统一按各卡片的 ``stars today`` 数值排名。

    Actions 环境对 github.com 并发更敏感，改为串行抓取并容忍部分失败。
    """
    urls = [TRENDING_URL] + [
        f"https://github.com/trending/{language}?since=daily"
        for language in TRENDING_LANGUAGES
    ]
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    for url in urls:
        try:
            page_repos = _fetch_page(url)
            candidates.extend(page_repos)
            safe_print(f"  抓取成功 {url} → {len(page_repos)} 条")
        except Exception as exc:  # noqa: BLE001 — 单页失败不阻断
            errors.append(f"{url}: {exc}")
            safe_print(f"  抓取失败 {url}: {exc}")
        time.sleep(0.6)

    ranked = merge_rank_repos(candidates, limit)
    if not ranked:
        details = "; ".join(errors[:3])
        raise RuntimeError(
            f"未能解析到 Trending 仓库，页面结构或网络可能异常：{details}"
        )
    if len(ranked) < limit:
        safe_print(f"  警告：仅得到 {len(ranked)}/{limit} 个仓库，将按实际数量出榜")
    return ranked  # type: ignore[return-value]
