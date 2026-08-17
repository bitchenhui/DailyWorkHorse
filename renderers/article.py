"""公众号长图文渲染：正文 HTML、Markdown 成稿与头条封面。"""

from __future__ import annotations

import html
from html import escape as _esc

from PIL import Image, ImageDraw

from core.models import ContentBundle, Editorial, RepoItem
from renderers.base import ImageAsset, RenderResult
from renderers.fonts import center_text, load_font
from renderers.format import fmt_count, fmt_delta
from renderers.theme import (
    ACCENT,
    ACCENT_SOFT,
    BODY_TEXT,
    FONT,
    HAIRLINE,
    INK,
    MONO,
    MUTED,
    PAPER,
    SURFACE,
)

PLATFORM = "wechat_mp"
PLATFORM_LABEL = "微信公众号"


def _lang_summary(repos: list[RepoItem]) -> str:
    counts: dict[str, int] = {}
    for r in repos:
        lang = r.get("language") or "Unknown"
        counts[lang] = counts.get(lang, 0) + 1
    top = sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:3]
    return " · ".join(f"{lang} {n}" for lang, n in top)


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _meta_row(r: RepoItem) -> str:
    delta = _esc(fmt_delta(r["stars_today"]))
    lang = _esc(r["language"])
    total = _esc(fmt_count(r["stars_total"]))
    return (
        f'<div style="margin:10px 0 0;font:500 12px/1.4 {MONO};color:{MUTED};">'
        f'<span style="display:inline-block;padding:3px 8px;border-radius:4px;'
        f'background:{ACCENT_SOFT};color:{ACCENT};font-weight:600;">{delta} 今日</span>'
        f'<span style="margin-left:10px;">{lang}</span>'
        f'<span style="margin-left:10px;">累计 {total}★</span>'
        "</div>"
    )


def _detail_card(r: RepoItem, editorial: Editorial | None) -> str:
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


def _compact_row(r: RepoItem, editorial: Editorial | None, last: bool) -> str:
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
        f'{_esc(fmt_delta(r["stars_today"]))}</span></div>'
        f'<div style="margin:4px 0 0 26px;font:400 12px/1.6 {FONT};color:{MUTED};">'
        f'{summary}</div>'
        f'<div style="margin:2px 0 0 26px;font:400 11px/1.5 {MONO};color:#a0a6b2;">'
        f'{_esc(r["language"])} · 累计 {_esc(fmt_count(r["stars_total"]))}★</div>'
        "</div>"
    )


def build_title(repos: list[RepoItem]) -> str:
    return f"开源升温榜｜今日增长最快的 {len(repos)} 个 GitHub 项目"


def _section(label: str, note: str = "") -> str:
    note_html = (
        f'<span style="margin-left:8px;font:400 12px/1 {FONT};color:{MUTED};">{note}</span>'
        if note
        else ""
    )
    return (
        f'<div style="margin:26px 0 12px;font:600 14px/1 {FONT};color:{INK};">'
        f"{_esc(label)}{note_html}</div>"
    )


def render_body(bundle: ContentBundle) -> str:
    """渲染公众号正文 HTML。渲染器不读时钟，日期一律取自 bundle。"""
    repos = bundle.repos
    peak = repos[0]["stars_today"] if repos else 0

    header = (
        f'<div style="padding:22px 18px;background:{INK};border-radius:10px;">'
        f'<div style="font:600 11px/1 {MONO};color:#8f97ad;letter-spacing:.18em;">'
        f"GITHUB DAILY RADAR</div>"
        f'<div style="margin:10px 0 0;font:600 22px/1.4 {FONT};color:#ffffff;">'
        f"开源升温榜</div>"
        f'<div style="margin:5px 0 0;font:400 15px/1.6 {FONT};color:#d9dce5;">'
        f"今天，哪些 GitHub 项目正在快速获得关注？</div>"
        f'<div style="margin:12px 0 0;font:400 12px/1.7 {MONO};color:#9aa2b8;">'
        f"{_esc(bundle.date_text)} · 最高日增 {_esc(fmt_delta(peak))} · "
        f"{_esc(_lang_summary(repos))}"
        "</div></div>"
    )

    parts = [
        f'<div style="max-width:600px;margin:0 auto;padding:16px 12px;'
        f'background:{PAPER};font-family:{FONT};color:{BODY_TEXT};">',
        header,
        _section("前三观察", "不止看数字，也看项目价值"),
    ]
    for r in repos[:3]:
        parts.append(_detail_card(r, bundle.editorial_for(r["rank"])))

    rest = repos[3:]
    if rest:
        parts.append(_section("继续升温", f"第 {rest[0]['rank']}–{rest[-1]['rank']} 名"))
        parts.append(
            f'<div style="padding:4px 16px;background:{SURFACE};'
            f'border:1px solid {HAIRLINE};border-radius:10px;">'
            + "".join(
                _compact_row(r, bundle.editorial_for(r["rank"]), r is rest[-1])
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
    return "".join(parts)


def render_cover(bundle: ContentBundle) -> Image.Image:
    """生成 900×383 头条封面，核心标题位于中央方形安全区。"""
    image = Image.new("RGB", (900, 383), INK)
    draw = ImageDraw.Draw(image)

    # 两侧图形即使被微信裁成方图也不影响核心信息。
    draw.ellipse((-105, 40, 235, 380), fill="#202538")
    draw.ellipse((705, -120, 1020, 195), fill="#123f3b")
    draw.rounded_rectangle((54, 54, 154, 82), radius=14, fill=ACCENT)
    draw.text((72, 60), "DAILY", font=load_font(14, bold=True), fill="#ffffff")

    center_x = 450
    center_text(draw, (center_x, 132), "开源升温榜", load_font(54, bold=True), "#ffffff")
    center_text(
        draw,
        (center_x, 190),
        "GITHUB DAILY RADAR",
        load_font(17, bold=True),
        "#93a0b8",
    )
    center_text(draw, (center_x, 228), bundle.date_text, load_font(18), "#d6dae4")

    top_repo = bundle.repos[0] if bundle.repos else None
    repo_name = (top_repo or {}).get("full_name") or "今日开源趋势"
    delta = (top_repo or {}).get("stars_today")
    signal = f"TOP 1  {repo_name}"
    if delta:
        signal += f"  +{delta}★"
    if len(signal) > 44:
        signal = signal[:43] + "…"
    center_text(draw, (center_x, 304), signal, load_font(18, bold=True), "#cde5e1")

    return image


def build_markdown(bundle: ContentBundle) -> str:
    """备用 Markdown 成稿，便于粘贴到其他编辑器。"""
    lines = [
        f"# {bundle.title}",
        "",
        f"> {bundle.date_text} · 按今日新增 Stars 降序",
        "",
    ]
    for repo in bundle.repos:
        rank = repo["rank"]
        item = bundle.editorial_for(rank) or {}
        summary = item.get("summary") or repo.get("description") or "暂无简介"
        lines.extend(
            [
                f"## {rank:02d}. [{repo['full_name']}]({repo['url']})",
                (
                    f"**+{repo['stars_today']}★ 今日** · {repo['language']} · "
                    f"累计 {repo['stars_total']:,}★"
                ),
                "",
                summary,
                "",
            ]
        )
        if rank <= 3:
            for label, key in (
                ("是什么", "what"),
                ("上涨原因", "why"),
                ("适合关注", "who"),
            ):
                value = item.get(key)
                if value:
                    lines.append(f"- **{label}**：{value}")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def _standalone_document(title: str, body: str) -> str:
    safe_title = html.escape(title)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{safe_title}</title>
</head>
<body style="margin:0;background:{PAPER};">{body}</body>
</html>
"""


def render(bundle: ContentBundle) -> RenderResult:
    body_html = render_body(bundle)
    return RenderResult(
        platform=PLATFORM,
        platform_label=PLATFORM_LABEL,
        title=bundle.title,
        body_html=body_html,
        images=[ImageAsset("cover.png", render_cover(bundle))],
        text_files={
            "article.html": _standalone_document(bundle.title, body_html),
            "article.md": build_markdown(bundle),
        },
        hint="复制正文粘贴到公众号编辑器，再上传封面、预览并群发。",
        target_label="打开公众号后台",
        target_url="https://mp.weixin.qq.com/",
    )
