"""编排：逐个信息源采集与加工 → 逐平台渲染 → 逐平台投递。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from html import escape as _esc
from typing import Callable

from channels import pushplus, report
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
from core.models import Bundle, ContentBundle, NothingToPublish
from enrich import editorial as editorial_enricher
from enrich import social as social_enricher
from renderers import article, carddeck, marketvideo
from renderers.base import RenderResult
from renderers.theme import ACCENT, ACCENT_SOFT, FONT
from sources import github_trending, market


def build_content_bundle(limit: int = 10) -> ContentBundle:
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


@dataclass(frozen=True)
class Feed:
    """一个信息源，以及它在各平台上的渲染器。

    ``build`` 延迟到确认有平台启用之后才调用：GitHub 那路要花 LLM 额度、
    行情那路要打几十个行情接口，两者都不该为一个关掉的平台白跑。
    """

    name: str
    build: Callable[[], Bundle]
    renderers: dict[str, Callable[[Bundle], RenderResult]]


FEEDS: tuple[Feed, ...] = (
    Feed(
        "github",
        lambda: build_content_bundle(10),
        {"wechat_mp": article.render, "xhs": carddeck.render},
    ),
    Feed("market", market.build_bundle, {"xhs_video": marketvideo.render}),
)


def resolve_channel(platform: str) -> Channel:
    tier = platform_tier(platform)
    if tier == "bundle":
        return BundleChannel(DIST_DIR)
    raise SystemExit(
        f"{PLATFORM_LABELS.get(platform, platform)} 的投递档位 '{tier}' 尚未实现，"
        f"当前仅支持 bundle（详见 docs/ARCHITECTURE.md）"
    )


@dataclass
class Outcome:
    """一次分发的结果。

    ``idle`` 与 ``failed`` 必须分开：行情源在周末本来就没内容，那是预期内的
    「今天没得发」；抓取超时才是故障。两者混在一起，要么周末天天亮红叉，
    要么真出事时没人知道。
    """

    date_text: str
    results: list[RenderResult] = field(default_factory=list)
    idle: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def distribute() -> Outcome:
    """跑完所有启用的平台。"""
    enabled = enabled_platforms()
    unclaimed = set(enabled) - {p for feed in FEEDS for p in feed.renderers}
    for platform in sorted(unclaimed):
        safe_print(f"  跳过 {platform}：尚无渲染器")

    outcome = Outcome(datetime.now(CST).strftime("%Y-%m-%d"))

    for feed in FEEDS:
        wanted = [p for p in enabled if p in feed.renderers]
        if not wanted:
            continue

        # 信息源之间相互隔离：行情接口在境外 runner 上未必稳，
        # 不该让它把当天的 GitHub 日报一起拖没。
        try:
            bundle = feed.build()
            outcome.date_text = bundle.date_text
            for platform in wanted:
                result = feed.renderers[platform](bundle)
                channel = resolve_channel(platform)
                channel.preflight()
                delivered: DeliveryResult = channel.deliver(bundle, result)
                safe_print(
                    f"  {result.platform_label} → {delivered.location}"
                    f" ({delivered.detail})"
                )
                outcome.results.append(result)
        except SystemExit:
            # 缺环境变量之类的配置错误，改了配置才有意义，不该被吞掉。
            raise
        except NothingToPublish as reason:
            safe_print(f"  信息源 {feed.name} 今天没有内容：{reason}")
            outcome.idle.append(f"{feed.name}（{reason}）")
        except Exception as error:  # noqa: BLE001 - 单个信息源失败不影响其余
            safe_print(f"  信息源 {feed.name} 失败，跳过：{type(error).__name__}: {error}")
            outcome.failed.append(f"{feed.name}（{type(error).__name__}: {error}）")
    return outcome


def notification_title(results: list[RenderResult]) -> str:
    """通知标题跟着正文走：正文取自哪个平台，标题就用哪个平台的。"""
    for result in results:
        if result.platform == "wechat_mp" and result.body_html:
            return result.title
    for result in results:
        if any(item.text for item in result.copy_fields):
            return result.title
    return results[0].title if results else "每日分发"


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
    outcome = distribute()
    results = outcome.results

    # 先落运行记录再判成败。收尾邮件在失败时也要发，而「哪个信息源没出内容、
    # 为什么」正是那封邮件唯一有价值的部分；写在 raise 之后就永远写不到。
    report.write_record(
        DIST_DIR,
        outcome.date_text,
        [
            {
                "platform": item.platform,
                "label": item.platform_label,
                "title": item.title,
            }
            for item in results
        ],
        outcome.idle,
        outcome.failed,
    )

    if not results:
        if outcome.failed:
            raise RuntimeError("信息源全部失败：" + "；".join(outcome.failed))
        if outcome.idle:
            # 正常收工：周末的行情流水线走的就是这一支，不该记成失败。
            safe_print("今天没有可发布的内容：" + "；".join(outcome.idle))
            return 0
        raise RuntimeError("没有任何平台产出成稿，请检查 ENABLED_PLATFORMS")

    # 总览页扫的是磁盘，所以会连带列出往次运行留在站点上的其它平台。
    write_overview(DIST_DIR)
    safe_print(f"已生成分发总览: {DIST_DIR / 'index.html'}")

    if dry_run:
        safe_print("--dry-run：跳过微信推送")
        return 0

    safe_print("推送到微信 …")
    push_content = notification_body(results)
    draft_url = os.environ.get("PUBLIC_DRAFT_URL", "").strip()
    if draft_url:
        push_content += _draft_link_card(draft_url)
    pushplus.send(notification_title(results), push_content)
    return 0
