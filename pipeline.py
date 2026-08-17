"""编排：采集 → LLM 加工 → 逐平台渲染 → 逐平台投递。"""

from __future__ import annotations

import os
from datetime import datetime
from html import escape as _esc
from typing import Callable

from channels import pushplus
from channels.base import Channel, DeliveryResult
from channels.bundle import BundleChannel
from channels.overview import write_overview
from core.config import (
    CST,
    DIST_DIR,
    PLATFORM_LABELS,
    enabled_platforms,
    platform_tier,
)
from core.console import safe_print
from core.models import ContentBundle
from enrich import editorial as editorial_enricher
from enrich import social as social_enricher
from renderers import article, carddeck
from renderers.base import RenderResult
from renderers.theme import ACCENT, ACCENT_SOFT, FONT
from sources import github_trending

RENDERERS: dict[str, Callable[[ContentBundle], RenderResult]] = {
    "wechat_mp": article.render,
    "xhs": carddeck.render,
}


def build_bundle(limit: int = 10) -> ContentBundle:
    safe_print("抓取 GitHub Trending …")
    repos = github_trending.fetch(limit)
    for r in repos:
        safe_print(
            f"  #{r['rank']} {r['full_name']} +{r['stars_today']} ({r['language']})"
        )

    safe_print(f"生成 Top{len(repos)} 中文摘要与 Top3 深度解读 …")
    editorial = editorial_enricher.generate(repos)

    safe_print("生成社交平台文案 …")
    copy = social_enricher.generate(repos, editorial)

    date_text = datetime.now(CST).strftime("%Y-%m-%d")
    return ContentBundle(
        slug=f"{date_text}-github-trending",
        date_text=date_text,
        title=article.build_title(repos),
        repos=repos,
        editorial=editorial,
        alt_titles=copy.titles,
        lede=copy.lede,
        tags=copy.tags,
    )


def resolve_channel(platform: str) -> Channel:
    tier = platform_tier(platform)
    if tier == "bundle":
        return BundleChannel(DIST_DIR)
    raise SystemExit(
        f"{PLATFORM_LABELS.get(platform, platform)} 的投递档位 '{tier}' 尚未实现，"
        f"当前仅支持 bundle（详见 docs/ARCHITECTURE.md）"
    )


def distribute(bundle: ContentBundle) -> list[RenderResult]:
    results: list[RenderResult] = []
    for platform in enabled_platforms():
        renderer = RENDERERS.get(platform)
        if renderer is None:
            safe_print(f"  跳过 {platform}：尚无渲染器")
            continue
        result = renderer(bundle)
        channel = resolve_channel(platform)
        channel.preflight()
        delivered: DeliveryResult = channel.deliver(bundle, result)
        safe_print(
            f"  {result.platform_label} → {delivered.location} ({delivered.detail})"
        )
        results.append(result)
    return results


def notification_body(results: list[RenderResult]) -> str:
    """挑一份适合塞进微信通知的正文。

    优先公众号的富文本；没有就退回任意平台的第一个非空文本字段，
    保证即使只启用了小红书，通知也不会是空的。
    """
    for result in results:
        if result.platform == "wechat_mp" and result.body_html:
            return result.body_html
    for result in results:
        for item in result.copy_fields:
            if item.text:
                return _esc(item.text).replace("\n", "<br>")
    return ""


def _draft_link_card(draft_url: str) -> str:
    """通知消息末尾的跳转按钮，引导到在线成稿页完成发布。"""
    safe_url = _esc(draft_url, quote=True)
    return (
        f'<div style="margin:18px 12px;padding:15px;border-radius:9px;'
        f'background:{ACCENT_SOFT};font:600 14px/1.5 {FONT};text-align:center;">'
        f'<a href="{safe_url}" style="color:{ACCENT};text-decoration:none;">'
        "打开分发总览 · 逐平台发布 →</a></div>"
    )


def run(dry_run: bool = False) -> int:
    content = build_bundle(10)

    safe_print("渲染并投递各平台成稿 …")
    results = distribute(content)
    if not results:
        raise RuntimeError("没有任何平台产出成稿，请检查 ENABLED_PLATFORMS")
    write_overview(DIST_DIR, content, results)
    safe_print(f"已生成分发总览: {DIST_DIR / 'index.html'}")

    if dry_run:
        safe_print("--dry-run：跳过微信推送")
        return 0

    safe_print("推送到微信 …")
    push_content = notification_body(results)
    draft_url = os.environ.get("PUBLIC_DRAFT_URL", "").strip()
    if draft_url:
        push_content += _draft_link_card(draft_url)
    pushplus.send(content.title, push_content)
    return 0
