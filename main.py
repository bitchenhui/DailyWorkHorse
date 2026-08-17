#!/usr/bin/env python3
"""GitHub Trending Top10 → LLM 精选解读 → PushPlus 微信推送."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta
from html import escape as _esc
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


def _parse_trending_html(html: str) -> list[dict[str, Any]]:
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


def _fetch_trending_page(url: str, retries: int = 3) -> list[dict[str, Any]]:
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
            repos = _parse_trending_html(resp.text)
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


def fetch_trending(limit: int = 10) -> list[dict[str, Any]]:
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
            page_repos = _fetch_trending_page(url)
            candidates.extend(page_repos)
            _safe_print(f"  抓取成功 {url} → {len(page_repos)} 条")
        except Exception as exc:  # noqa: BLE001 — 单页失败不阻断
            errors.append(f"{url}: {exc}")
            _safe_print(f"  抓取失败 {url}: {exc}")
        time.sleep(0.6)

    ranked = merge_rank_repos(candidates, limit)
    if not ranked:
        details = "; ".join(errors[:3])
        raise RuntimeError(
            f"未能解析到 Trending 仓库，页面结构或网络可能异常：{details}"
        )
    if len(ranked) < limit:
        _safe_print(f"  警告：仅得到 {len(ranked)}/{limit} 个仓库，将按实际数量出榜")
    return ranked


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


def _llm_complete(system: str, user: str) -> str:
    api_key = env("LLM_API_KEY")
    api_base = env("LLM_API_BASE").rstrip("/")
    model = env("LLM_MODEL")

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
        if _is_anthropic_base(api_base):
            return _extract_anthropic_text(data)
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, RuntimeError) as exc:
        raise RuntimeError(f"LLM 响应格式异常: {data}") from exc


def _strip_code_fence(text: str) -> str:
    body = text.strip()
    if body.startswith("```"):
        body = re.sub(r"^```[a-zA-Z]*\s*", "", body)
        body = re.sub(r"\s*```$", "", body)
    return body.strip()


def parse_editorial(
    raw: str, expected_ranks: set[int]
) -> dict[int, dict[str, str]]:
    """解析并校验模型返回的 TopN 中文编辑内容。"""
    body = _strip_code_fence(raw)
    try:
        items = json.loads(body)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", body, re.S)
        if not match:
            raise RuntimeError(f"LLM 未返回可解析 JSON: {body[:500]}")
        items = json.loads(match.group(0))

    result: dict[int, dict[str, str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            rank = int(item.get("rank"))
        except (TypeError, ValueError):
            continue
        if rank not in expected_ranks:
            continue
        result[rank] = {
            "summary": str(item.get("summary") or "").strip(),
            "what": str(item.get("what") or "").strip(),
            "why": str(item.get("why") or "").strip(),
            "who": str(item.get("who") or "").strip(),
        }

    missing = expected_ranks - result.keys()
    no_summary = [rank for rank, item in result.items() if not item["summary"]]
    if missing or no_summary:
        raise RuntimeError(
            f"LLM 编辑内容不完整，缺少排名={sorted(missing)}，"
            f"缺少摘要={sorted(no_summary)}"
        )
    return result


def _fallback_summary(repo: dict[str, Any]) -> str:
    desc = " ".join((repo.get("description") or "").split())
    if desc:
        return desc[:48] + ("…" if len(desc) > 48 else "")
    return f"{repo.get('full_name', '未知仓库')} 今日新增关注"


def llm_editorial(repos: list[dict[str, Any]]) -> dict[int, dict[str, str]]:
    """为 Top10 生成一句话摘要，并为前三名补充结构化深读。"""
    payload_repos = [
        {
            "rank": r["rank"],
            "full_name": r["full_name"],
            "description": r["description"],
            "language": r["language"],
            "stars_total": r["stars_total"],
            "stars_today": r["stars_today"],
        }
        for r in repos
    ]

    system = (
        "你是面向中文开发者的开源观察编辑。根据给定仓库信息生成编辑内容。\n"
        "要求：\n"
        "1. 所有项目都写 summary：中文一句话说明项目是什么，18–32 字，"
        "信息具体，不逐字翻译英文简介\n"
        "2. 仅 rank 1–3 额外写 what/why/who，各 25–45 字；"
        "rank 4 以后这三项填空字符串\n"
        "3. why 只能基于输入合理概括其关注价值，不要声称已知社交媒体传播、"
        "版本发布等未提供事实\n"
        "4. 语气专业克制，不用营销腔，不得编造功能，句末不加句号\n"
        "5. 只输出 JSON 数组，不要代码块、不要解释：\n"
        '[{"rank":1,"summary":"...","what":"...","why":"...","who":"..."}]\n'
        "6. 每个输入 rank 必须且只能出现一次"
    )
    user = "今日榜单数据：\n" + json.dumps(
        payload_repos, ensure_ascii=False, indent=2
    )

    expected = {r["rank"] for r in repos}
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            raw = _llm_complete(system, user)
            return parse_editorial(raw, expected)
        except Exception as exc:  # noqa: BLE001 — 允许一次重试
            last_error = exc
            _safe_print(f"  编辑内容解析失败，重试中（{attempt + 1}/2）: {exc}")

    # 最后兜底：尽量用已解析部分 + 英文简介填空，避免 Actions 整单失败
    try:
        raw = _llm_complete(system, user)
        body = _strip_code_fence(raw)
        try:
            items = json.loads(body)
        except json.JSONDecodeError:
            match = re.search(r"\[.*\]", body, re.S)
            items = json.loads(match.group(0)) if match else []
        partial: dict[int, dict[str, str]] = {}
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            try:
                rank = int(item.get("rank"))
            except (TypeError, ValueError):
                continue
            if rank not in expected:
                continue
            partial[rank] = {
                "summary": str(item.get("summary") or "").strip(),
                "what": str(item.get("what") or "").strip(),
                "why": str(item.get("why") or "").strip(),
                "who": str(item.get("who") or "").strip(),
            }
        for repo in repos:
            rank = repo["rank"]
            item = partial.setdefault(
                rank, {"summary": "", "what": "", "why": "", "who": ""}
            )
            if not item["summary"]:
                item["summary"] = _fallback_summary(repo)
        _safe_print("  已启用摘要兜底，保证榜单可推送")
        return partial
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"LLM 编辑内容连续失败: {last_error}; 兜底也失败: {exc}"
        ) from exc


def _fmt_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".rstrip("0").rstrip(".")
    if n >= 10_000:
        return f"{n / 1000:.0f}k"
    if n >= 1000:
        return f"{n / 1000:.1f}k".rstrip("0").rstrip(".")
    return str(n)


def _fmt_delta(n: int) -> str:
    return f"+{_fmt_count(n)}★"


def _lang_summary(repos: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for r in repos:
        lang = r.get("language") or "Unknown"
        counts[lang] = counts.get(lang, 0) + 1
    top = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:3]
    return " · ".join(f"{lang} {n}" for lang, n in top)


INK = "#1a1d29"
BODY_TEXT = "#3d4351"
MUTED = "#8b93a3"
HAIRLINE = "#e8eaef"
SURFACE = "#ffffff"
ACCENT = "#0f6f63"
ACCENT_SOFT = "#e7f2f0"
FONT = (
    "-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB',"
    "'Microsoft YaHei',sans-serif"
)
MONO = "'SF Mono',SFMono-Regular,Menlo,Consolas,monospace"


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _meta_row(r: dict[str, Any]) -> str:
    delta = _esc(_fmt_delta(r["stars_today"]))
    lang = _esc(r["language"])
    total = _esc(_fmt_count(r["stars_total"]))
    return (
        f'<div style="margin:10px 0 0;font:500 12px/1.4 {MONO};color:{MUTED};">'
        f'<span style="display:inline-block;padding:3px 8px;border-radius:4px;'
        f'background:{ACCENT_SOFT};color:{ACCENT};font-weight:600;">{delta} 今日</span>'
        f'<span style="margin-left:10px;">{lang}</span>'
        f'<span style="margin-left:10px;">累计 {total}★</span>'
        "</div>"
    )


def _detail_card(r: dict[str, Any], editorial: dict[str, str] | None) -> str:
    rank = f"{r['rank']:02d}"
    name = _esc(r["full_name"])
    url = _esc(r["url"], quote=True)
    summary = (
        editorial.get("summary", "") if editorial else ""
    ) or _clip(r["description"] or "暂无简介", 110)
    summary = _esc(summary)

    rows = ""
    if editorial:
        for label, key in (("是什么", "what"), ("上涨原因", "why"), ("适合关注", "who")):
            value = editorial.get(key)
            if not value:
                continue
            rows += (
                f'<div style="margin:9px 0 0;font:400 14px/1.75 {FONT};color:{BODY_TEXT};">'
                f'<span style="color:{MUTED};font-size:13px;">{label}</span>'
                f'<br>{_esc(value)}</div>'
            )

    return (
        f'<div style="margin:0 0 12px;padding:18px 16px;background:{SURFACE};'
        f'border:1px solid {HAIRLINE};border-radius:10px;">'
        f'<div style="font:600 11px/1 {MONO};color:{MUTED};letter-spacing:.12em;">'
        f"RANK {rank}</div>"
        f'<div style="margin:8px 0 0;font:600 17px/1.4 {FONT};">'
        f'<a href="{url}" style="color:{INK};text-decoration:none;">{name}</a></div>'
        f'<div style="margin:7px 0 0;font:400 14px/1.7 {FONT};color:{BODY_TEXT};">{summary}</div>'
        f"{_meta_row(r)}"
        f"{rows}"
        f'<div style="margin:14px 0 0;font:600 13px/1 {FONT};">'
        f'<a href="{url}" style="color:{ACCENT};text-decoration:none;">打开仓库 →</a></div>'
        "</div>"
    )


def _compact_row(
    r: dict[str, Any], editorial: dict[str, str] | None, last: bool
) -> str:
    border = "" if last else f"border-bottom:1px solid {HAIRLINE};"
    name = _esc(r["full_name"])
    url = _esc(r["url"], quote=True)
    summary = (
        editorial.get("summary", "") if editorial else ""
    ) or _clip(r["description"] or "暂无简介", 42)
    summary = _esc(summary)
    return (
        f'<div style="padding:12px 0;{border}">'
        f'<div style="font:400 14px/1.5 {FONT};">'
        f'<span style="display:inline-block;min-width:26px;font:600 12px/1.5 {MONO};'
        f'color:{MUTED};">{r["rank"]:02d}</span>'
        f'<a href="{url}" style="color:{INK};text-decoration:none;font-weight:600;">{name}</a>'
        f'<span style="float:right;font:600 12px/1.6 {MONO};color:{ACCENT};">'
        f'{_esc(_fmt_delta(r["stars_today"]))}</span></div>'
        f'<div style="margin:4px 0 0 26px;font:400 12px/1.6 {FONT};color:{MUTED};">'
        f'{summary}</div>'
        f'<div style="margin:2px 0 0 26px;font:400 11px/1.5 {MONO};color:#a0a6b2;">'
        f'{_esc(r["language"])} · 累计 {_esc(_fmt_count(r["stars_total"]))}★</div>'
        "</div>"
    )


def build_message(
    repos: list[dict[str, Any]], editorial: dict[int, dict[str, str]]
) -> tuple[str, str]:
    today = datetime.now(CST).strftime("%Y-%m-%d")
    n = len(repos)
    peak = repos[0]["stars_today"] if repos else 0
    title = f"开源升温榜｜今日增长最快的 {n} 个 GitHub 项目"

    header = (
        f'<div style="padding:22px 18px;background:{INK};border-radius:10px;">'
        f'<div style="font:600 11px/1 {MONO};color:#8f97ad;letter-spacing:.18em;">'
        f"GITHUB DAILY RADAR</div>"
        f'<div style="margin:10px 0 0;font:600 22px/1.4 {FONT};color:#ffffff;">'
        f"开源升温榜</div>"
        f'<div style="margin:5px 0 0;font:400 15px/1.6 {FONT};color:#d9dce5;">'
        f"今天，哪些 GitHub 项目正在快速获得关注？</div>"
        f'<div style="margin:12px 0 0;font:400 12px/1.7 {MONO};color:#9aa2b8;">'
        f"{_esc(today)} · 最高日增 {_esc(_fmt_delta(peak))} · {_esc(_lang_summary(repos))}"
        "</div></div>"
    )

    def section(label: str, note: str = "") -> str:
        note_html = (
            f'<span style="margin-left:8px;font:400 12px/1 {FONT};color:{MUTED};">{note}</span>'
            if note
            else ""
        )
        return (
            f'<div style="margin:26px 0 12px;font:600 14px/1 {FONT};color:{INK};">'
            f"{_esc(label)}{note_html}</div>"
        )

    parts = [
        f'<div style="max-width:600px;margin:0 auto;padding:16px 12px;'
        f'background:#f5f6f8;font-family:{FONT};color:{BODY_TEXT};">',
        header,
        section("前三观察", "不止看数字，也看项目价值"),
    ]
    for r in repos[:3]:
        parts.append(_detail_card(r, editorial.get(r["rank"])))

    rest = repos[3:]
    if rest:
        parts.append(section("继续升温", f"第 {rest[0]['rank']}–{rest[-1]['rank']} 名"))
        parts.append(
            f'<div style="padding:4px 16px;background:{SURFACE};'
            f'border:1px solid {HAIRLINE};border-radius:10px;">'
            + "".join(
                _compact_row(r, editorial.get(r["rank"]), r is rest[-1])
                for r in rest
            )
            + "</div>"
        )

    parts.append(
        f'<div style="margin:24px 0 4px;font:400 12px/1.8 {FONT};color:{MUTED};">'
        f"数据来自 GitHub Trending 日榜候选，按今日新增星标降序重排。<br>"
        f'<a href="https://github.com/trending?since=daily" '
        f'style="color:{ACCENT};text-decoration:none;">查看源页 →</a>'
        "</div>"
    )
    parts.append("</div>")
    return title, "".join(parts)


def push_wechat(title: str, content: str) -> None:
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


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(enc, errors="replace").decode(enc, errors="replace"))


def main() -> int:
    dry_run = "--dry-run" in sys.argv

    _safe_print("抓取 GitHub Trending …")
    repos = fetch_trending(10)
    for r in repos:
        _safe_print(
            f"  #{r['rank']} {r['full_name']} +{r['stars_today']} "
            f"({r['language']})"
        )

    _safe_print(f"生成 Top{len(repos)} 中文摘要与 Top3 深度解读 …")
    editorial = llm_editorial(repos)

    title, content = build_message(repos, editorial)

    preview = Path(__file__).resolve().parent / "preview.html"
    preview.write_text(content, encoding="utf-8")
    _safe_print(f"已写出本地预览: {preview}")

    if dry_run:
        _safe_print("--dry-run：跳过微信推送")
        return 0

    _safe_print("推送到微信 …")
    push_wechat(title, content)
    return 0


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
