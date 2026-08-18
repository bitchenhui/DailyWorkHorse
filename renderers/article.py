"""公众号长图文渲染：正文 HTML、Markdown 成稿与头条封面。

正文按**微信公众号编辑器**的粘贴规则来写，而不是按浏览器预览来写。
编辑器会剥掉 ``border-radius``、``float``、``font`` 简写和大部分嵌套 ``div``，
预览里好看的卡片贴进去就只剩乱掉的结构。所以这里统一用 ``section`` + ``p``
+ 内联 ``span``，预览区看到的就是粘贴后能得到的样子。
"""

from __future__ import annotations

import html
from html import escape as _esc

from PIL import Image, ImageDraw

from core.models import ContentBundle, Editorial, RepoItem
from renderers.base import CopyField, ImageAsset, RenderResult
from renderers.fonts import center_text, load_font
from renderers.format import fmt_count, fmt_delta, fmt_delta_num
from renderers.theme import (
    ACCENT,
    BODY_TEXT,
    FONT,
    INK,
    MUTED,
    PAPER,
    STAR_GOLD,
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


def _star_html() -> str:
    return f'<span style="color:{STAR_GOLD};">★</span>'


def _delta_html(n: int) -> str:
    return (
        f'<span style="color:{ACCENT};font-weight:bold;">{_esc(fmt_delta_num(n))}</span>'
        f"{_star_html()}"
    )


def _meta_row(r: RepoItem) -> str:
    lang = _esc(r["language"])
    total = _esc(fmt_count(r["stars_total"]))
    return (
        f'<p style="margin:10px 0 0;font-size:12px;line-height:1.6;color:{MUTED};">'
        f"{_delta_html(r['stars_today'])}"
        f'<span style="color:{ACCENT};"> 近24h</span>'
        f"<span> · {lang}</span>"
        f"<span> · 累计 {total}</span>{_star_html()}"
        "</p>"
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
                f'<p style="margin:10px 0 0;font-size:14px;line-height:1.75;'
                f'color:{BODY_TEXT};">'
                f'<span style="color:{MUTED};font-size:13px;">{label}</span><br>'
                f"{_esc(value)}</p>"
            )

    return (
        f'<section style="margin:0 0 14px;padding:16px;background-color:{SURFACE};'
        f'border:1px solid #e8eaef;">'
        f'<p style="margin:0;font-size:11px;line-height:1;color:{MUTED};'
        f'letter-spacing:0.12em;">RANK {rank}</p>'
        f'<p style="margin:8px 0 0;font-size:17px;line-height:1.5;font-weight:bold;">'
        f'<a href="{url}" style="color:{INK};text-decoration:none;">{name}</a></p>'
        f'<p style="margin:8px 0 0;font-size:14px;line-height:1.7;color:{BODY_TEXT};">'
        f"{summary}</p>"
        f"{_meta_row(r)}"
        f"{rows}"
        f'<p style="margin:14px 0 0;font-size:13px;line-height:1;">'
        f'<a href="{url}" style="color:{ACCENT};text-decoration:none;">打开仓库 →</a></p>'
        "</section>"
    )


def _compact_row(r: RepoItem, editorial: Editorial | None, last: bool) -> str:
    border = "" if last else "border-bottom:1px solid #e8eaef;"
    name = _esc(r["full_name"])
    url = _esc(r["url"], quote=True)
    summary = (
        editorial.get("summary", "") if editorial else ""
    ) or _clip(r["description"] or "暂无简介", 42)
    summary = _esc(summary)
    return (
        f'<section style="padding:12px 0;{border}">'
        f'<p style="margin:0;font-size:14px;line-height:1.6;color:{INK};">'
        f'<span style="color:{MUTED};font-weight:bold;">{r["rank"]:02d}</span> '
        f'<a href="{url}" style="color:{INK};text-decoration:none;font-weight:bold;">'
        f"{name}</a> "
        f"{_delta_html(r['stars_today'])}"
        "</p>"
        f'<p style="margin:4px 0 0 26px;font-size:12px;line-height:1.6;color:{MUTED};">'
        f"{summary}</p>"
        f'<p style="margin:2px 0 0 26px;font-size:11px;line-height:1.5;color:#a0a6b2;">'
        f'{_esc(r["language"])} · 累计 {_esc(fmt_count(r["stars_total"]))}{_star_html()}'
        "</p>"
        "</section>"
    )


def build_title(repos: list[RepoItem]) -> str:
    return f"开源升温榜｜近 24 小时增长最快的 {len(repos)} 个 GitHub 项目"


def _section(label: str, note: str = "") -> str:
    note_html = (
        f'<span style="margin-left:8px;font-size:12px;color:{MUTED};">{note}</span>'
        if note
        else ""
    )
    return (
        f'<section style="margin:24px 0 12px;">'
        f'<p style="margin:0;font-size:15px;line-height:1;font-weight:bold;color:{INK};">'
        f"{_esc(label)}{note_html}</p>"
        "</section>"
    )


def render_body(bundle: ContentBundle) -> str:
    """渲染可直接粘贴进公众号编辑器的正文 HTML。"""
    repos = bundle.repos
    peak = repos[0]["stars_today"] if repos else 0

    header = (
        f'<section style="padding:22px 16px;background-color:{INK};text-align:center;">'
        f'<p style="margin:0;font-size:11px;line-height:1;color:#8f97ad;'
        f'letter-spacing:0.18em;">GITHUB DAILY RADAR</p>'
        f'<p style="margin:10px 0 0;font-size:22px;line-height:1.4;font-weight:bold;'
        f'color:#ffffff;">开源升温榜</p>'
        f'<p style="margin:5px 0 0;font-size:15px;line-height:1.6;color:#d9dce5;">'
        f"过去一天，哪些 GitHub 项目正在快速获得关注？</p>"
        f'<p style="margin:12px 0 0;font-size:12px;line-height:1.7;color:#9aa2b8;">'
        f"{_esc(bundle.date_text)} · 近 24h 最高 {_delta_html(peak)} · "
        f"{_esc(_lang_summary(repos))}"
        "</p></section>"
    )

    parts = [
        f'<section style="max-width:100%;padding:16px 12px;background-color:{PAPER};'
        f'font-family:{FONT};color:{BODY_TEXT};">',
        header,
        _section("前三观察", "不止看数字，也看项目价值"),
    ]
    for r in repos[:3]:
        parts.append(_detail_card(r, bundle.editorial_for(r["rank"])))

    rest = repos[3:]
    if rest:
        parts.append(_section("继续升温", f"第 {rest[0]['rank']}–{rest[-1]['rank']} 名"))
        parts.append(
            f'<section style="padding:4px 16px;background-color:{SURFACE};'
            f'border:1px solid #e8eaef;">'
            + "".join(
                _compact_row(r, bundle.editorial_for(r["rank"]), r is rest[-1])
                for r in rest
            )
            + "</section>"
        )

    parts.append(
        f'<section style="margin:24px 0 4px;">'
        f'<p style="margin:0;font-size:12px;line-height:1.8;color:{MUTED};">'
        f"数据来自 GitHub Trending 日榜（综合榜 + 8 个主流语言榜），"
        f"按各项目的新增星标降序重排。<br>"
        f"口径说明：Trending 的「stars today」是抓取时刻往前回溯约 24 小时的"
        f"滚动窗口，并非自然日切片；排名取自上述候选池，"
        f"未覆盖的语言榜可能有遗漏。<br>"
        f'<a href="https://github.com/trending?since=daily" '
        f'style="color:{ACCENT};text-decoration:none;">查看源页 →</a>'
        "</p></section>"
    )
    parts.append("</section>")
    return "".join(parts)


def render_cover(bundle: ContentBundle) -> Image.Image:
    """生成 900×383 头条封面，核心标题位于中央方形安全区。"""
    image = Image.new("RGB", (900, 383), INK)
    draw = ImageDraw.Draw(image)

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
        signal += f"  {fmt_delta(delta)}"
    if len(signal) > 44:
        signal = signal[:43] + "…"
    center_text(draw, (center_x, 304), signal, load_font(18, bold=True), "#cde5e1")

    return image


def build_markdown(bundle: ContentBundle) -> str:
    """备用 Markdown 成稿，便于粘贴到其他编辑器。"""
    lines = [
        f"# {bundle.title}",
        "",
        f"> {bundle.date_text} · 按近 24 小时新增 Stars 降序",
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
                    f"**+{repo['stars_today']}★ 近24h** · {repo['language']} · "
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
        copy_fields=[CopyField("标题", bundle.title, "公众号标题上限 64 字", rows=2)],
        images=[ImageAsset("cover.png", render_cover(bundle))],
        text_files={
            "article.html": _standalone_document(bundle.title, body_html),
            "article.md": build_markdown(bundle),
        },
        hint=(
            "先点「复制正文」粘贴到公众号编辑器，再上传封面。"
            "粘贴后若样式有偏差，可在编辑器里微调字号与段距。"
        ),
        target_label="打开公众号后台",
        target_url="https://mp.weixin.qq.com/",
    )
