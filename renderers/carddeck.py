"""小红书图卡组渲染：1080×1440 竖版图卡 + 笔记正文。

小红书是「封面决定点击、图卡决定停留」的场域，正文主要承担搜索关键词，
因此信息主体放在图里，正文保留完整项目名以便站内搜索命中。

图卡尺寸固定而内容长度不定，各卡都先测量文本行数再整体垂直居中，
避免出现下半张空白的失衡版面。
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from core.models import ContentBundle, RepoItem
from renderers.base import CopyField, ImageAsset, RenderResult
from renderers.fonts import fit_font_size, load_font, sanitize, text_width, wrap
from renderers.format import fmt_count, fmt_delta
from renderers.theme import (
    ACCENT,
    ACCENT_SOFT,
    BODY_TEXT,
    INK,
    MUTED,
    PAPER,
    SURFACE,
)

PLATFORM = "xhs"
PLATFORM_LABEL = "小红书"

# 小红书推荐的 3:4 竖版，在信息流里占位最大。
WIDTH = 1080
HEIGHT = 1440
MARGIN = 72
CONTENT_WIDTH = WIDTH - MARGIN * 2

# 深色封面上的辅助色，仅此处使用，不进主题表。
COVER_DIM = "#9aa2b8"
COVER_FAINT = "#6e768c"
COVER_RULE = "#2b3042"
COVER_HIGHLIGHT = "#cde5e1"

COVER_PREVIEW_COUNT = 5
COVER_ROW_HEIGHT = 112
DETAIL_COUNT = 3
ITEMS_PER_LIST_CARD = 4

# 详情卡的白卡高度随内容伸缩后整体居中：留白落在卡片外面像是设计，
# 落在卡片里面就只是没填满。
DETAIL_CARD_MIN_HEIGHT = 700
DETAIL_CARD_MAX_HEIGHT = 1320
DETAIL_TOP_PAD = 194  # 白卡顶到正文顶，中间是 RANK 行
DETAIL_BOTTOM_PAD = 164  # 正文底到白卡底，中间是仓库地址


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def _canvas(background: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), background)
    return image, ImageDraw.Draw(image)


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    lines: list[str],
    font,
    fill: str,
    line_height: int,
) -> int:
    """逐行绘制，返回下一行的 y 坐标。"""
    x, y = xy
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height
    return y


def _pill(
    draw: ImageDraw.ImageDraw,
    right: int,
    top: int,
    text: str,
    font,
    background: str,
    color: str,
) -> None:
    """右对齐的圆角标签。"""
    pad_x, pad_y = 22, 12
    width = text_width(text, font) + pad_x * 2
    height = font.size + pad_y * 2
    left = right - width
    draw.rounded_rectangle(
        (left, top, right, top + height), radius=height / 2, fill=background
    )
    draw.text((left + pad_x, top + pad_y - 2), text, font=font, fill=color)


def _spaced(text: str) -> str:
    return " ".join(text)


def _cover_title_font(text: str):
    """短标题用更大字号，避免封面上半部分显得空。"""
    if len(text) <= 10:
        return load_font(96, bold=True), 134
    if len(text) <= 16:
        return load_font(84, bold=True), 118
    return load_font(72, bold=True), 100


def _cover_card(bundle: ContentBundle) -> Image.Image:
    image, draw = _canvas(INK)

    draw.ellipse((760, -220, 1340, 360), fill="#123f3b")
    draw.ellipse((-240, 1080, 420, 1740), fill="#202538")

    draw.rounded_rectangle((MARGIN, 118, MARGIN + 236, 176), radius=29, fill=ACCENT)
    draw.text(
        (MARGIN + 30, 134), _spaced("DAILY"), font=load_font(24, bold=True), fill="#ffffff"
    )

    title = sanitize(bundle.social_title)
    title_font, title_line_height = _cover_title_font(title)
    title_lines = wrap(title, title_font, CONTENT_WIDTH, max_lines=3)
    y = _draw_lines(
        draw, (MARGIN, 232), title_lines, title_font, "#ffffff", title_line_height
    )

    draw.text(
        (MARGIN, y + 24),
        f"{bundle.date_text} · 按近 24 小时新增 Star 排名",
        font=load_font(30),
        fill=COVER_DIM,
    )

    preview = bundle.repos[:COVER_PREVIEW_COUNT]
    # 上界保证 5 行预告不会撞上底部说明，下界避免短标题时中段过空。
    rule_y = _clamp(y + 114, 560, 640)
    draw.line((MARGIN, rule_y, WIDTH - MARGIN, rule_y), fill=COVER_RULE, width=2)

    rank_font = load_font(32, bold=True)
    delta_font = load_font(30, bold=True)
    row_y = rule_y + 52
    for repo in preview:
        draw.text((MARGIN, row_y + 6), f"{repo['rank']:02d}", font=rank_font, fill=ACCENT)
        delta = fmt_delta(repo["stars_today"])
        delta_width = text_width(delta, delta_font)
        draw.text(
            (WIDTH - MARGIN - delta_width, row_y + 4),
            delta,
            font=delta_font,
            fill=COVER_HIGHLIGHT,
        )
        name = repo["full_name"].split("/")[-1]
        name_font = fit_font_size(
            name, CONTENT_WIDTH - delta_width - 130, 42, 26, bold=True
        )
        draw.text((MARGIN + 82, row_y), name, font=name_font, fill="#ffffff")
        row_y += COVER_ROW_HEIGHT

    draw.text(
        (MARGIN, 1300),
        "数据来自 GitHub Trending 日榜 · 每天更新",
        font=load_font(26),
        fill=COVER_FAINT,
    )
    return image


def _detail_card(bundle: ContentBundle, repo: RepoItem) -> Image.Image:
    image, draw = _canvas(PAPER)

    inner_x = 112
    inner_width = WIDTH - inner_x * 2

    name_font = load_font(54, bold=True)
    summary_font = load_font(38)
    label_font = load_font(26, bold=True)
    value_font = load_font(32)
    name_lh, summary_lh, value_lh = 74, 58, 50
    # meta_block 要容下 12px 上间距 + 28 号字行高 + 段后留白，取小了会压住摘要。
    meta_block, summary_gap, section_gap = 96, 40, 34

    name_lines = wrap(repo["full_name"], name_font, inner_width, max_lines=2)
    summary_lines = wrap(
        bundle.summary_for(repo), summary_font, inner_width, max_lines=3
    )
    editorial = bundle.editorial_for(repo["rank"]) or {}
    sections = [
        (label, wrap(editorial[key], value_font, inner_width, max_lines=2))
        for label, key in (("是什么", "what"), ("上涨原因", "why"), ("适合关注", "who"))
        if editorial.get(key)
    ]

    content_height = (
        len(name_lines) * name_lh
        + meta_block
        + len(summary_lines) * summary_lh
        + summary_gap
        + sum(44 + len(lines) * value_lh + section_gap for _, lines in sections)
    )
    if sections:
        content_height -= section_gap  # 末段不需要段后间距

    card_height = _clamp(
        DETAIL_TOP_PAD + content_height + DETAIL_BOTTOM_PAD,
        DETAIL_CARD_MIN_HEIGHT,
        DETAIL_CARD_MAX_HEIGHT,
    )
    card_top = (HEIGHT - card_height) // 2
    card_bottom = card_top + card_height
    draw.rounded_rectangle(
        (56, card_top, WIDTH - 56, card_bottom), radius=44, fill=SURFACE
    )

    draw.text(
        (inner_x, card_top + 72),
        _spaced(f"RANK {repo['rank']:02d}"),
        font=load_font(26, bold=True),
        fill=MUTED,
    )
    _pill(
        draw,
        WIDTH - inner_x,
        card_top + 60,
        f"{fmt_delta(repo['stars_today'])} 近24h",
        load_font(28, bold=True),
        ACCENT_SOFT,
        ACCENT,
    )

    y = card_top + DETAIL_TOP_PAD
    y = _draw_lines(draw, (inner_x, y), name_lines, name_font, INK, name_lh)
    draw.text(
        (inner_x, y + 12),
        f"{repo['language']} · 累计 {fmt_count(repo['stars_total'])}★",
        font=load_font(28),
        fill=MUTED,
    )
    y += meta_block

    y = _draw_lines(
        draw, (inner_x, y), summary_lines, summary_font, BODY_TEXT, summary_lh
    )
    y += summary_gap

    for label, lines in sections:
        draw.text((inner_x, y), label, font=label_font, fill=ACCENT)
        y = _draw_lines(
            draw, (inner_x, y + 44), lines, value_font, BODY_TEXT, value_lh
        )
        y += section_gap

    url = repo["url"].replace("https://", "")
    draw.text(
        (inner_x, card_bottom - 104),
        url,
        font=fit_font_size(url, inner_width, 26, 16),
        fill=MUTED,
    )
    return image


def _list_card(
    bundle: ContentBundle, repos: list[RepoItem], part: int, total_parts: int
) -> Image.Image:
    image, draw = _canvas(PAPER)

    draw.text((MARGIN, 108), "继续升温", font=load_font(52, bold=True), fill=INK)
    span = f"第 {repos[0]['rank']:02d}–{repos[-1]['rank']:02d} 名"
    if total_parts > 1:
        span += f" · {part}/{total_parts}"
    draw.text((MARGIN, 182), span, font=load_font(30), fill=MUTED)

    rank_font = load_font(34, bold=True)
    delta_font = load_font(30, bold=True)
    summary_font = load_font(28)
    inner_width = WIDTH - 104 * 2

    # 统一用本卡最长的摘要决定卡片高度，条目等高才整齐；富余空间摊进间距，
    # 条目少时靠拉开间距填满，而不是留一大块底部空白。
    summaries = [
        wrap(bundle.summary_for(repo), summary_font, inner_width, max_lines=2)
        for repo in repos
    ]
    card_height = 118 + max(len(lines) for lines in summaries) * 44 + 46
    available = (HEIGHT - 60) - 262
    gap = _clamp(
        (available - len(repos) * card_height) // (len(repos) + 1), 20, 120
    )
    y = 262 + gap

    for repo, summary_lines in zip(repos, summaries):
        draw.rounded_rectangle(
            (56, y, WIDTH - 56, y + card_height), radius=32, fill=SURFACE
        )
        inner_x = 104

        draw.text((inner_x, y + 44), f"{repo['rank']:02d}", font=rank_font, fill=ACCENT)
        delta = fmt_delta(repo["stars_today"])
        delta_width = text_width(delta, delta_font)
        draw.text(
            (WIDTH - inner_x - delta_width, y + 42),
            delta,
            font=delta_font,
            fill=ACCENT,
        )

        name_font = fit_font_size(
            repo["full_name"], inner_width - delta_width - 110, 38, 22, bold=True
        )
        draw.text((inner_x + 74, y + 40), repo["full_name"], font=name_font, fill=INK)

        _draw_lines(
            draw, (inner_x, y + 118), summary_lines, summary_font, BODY_TEXT, 44
        )
        y += card_height + gap

    return image


def _chunk(items: list[RepoItem], size: int) -> list[list[RepoItem]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def build_note(bundle: ContentBundle) -> str:
    """存档用的完整笔记：标题、正文、话题拼成一份，便于事后回看。"""
    parts = [bundle.social_title, "", build_note_body(bundle)]
    if bundle.tags:
        parts.extend(["", " ".join(f"#{tag}" for tag in bundle.tags)])
    return "\n".join(parts).strip() + "\n"


def build_note_body(bundle: ContentBundle) -> str:
    """笔记正文，不含标题与话题——这两样在小红书是独立输入框。

    保留完整项目名以命中站内搜索。
    """
    lines: list[str] = []
    if bundle.lede:
        lines.extend([bundle.lede, ""])

    for repo in bundle.repos:
        lines.append(
            f"{repo['rank']:02d}｜{repo['full_name']}  "
            f"{fmt_delta(repo['stars_today'])}"
        )
        lines.append(bundle.summary_for(repo))
        lines.append("")

    lines.append(
        "数据来自 GitHub Trending 日榜，按近 24 小时新增 Star 排序，每天更新。"
    )
    return "\n".join(lines).strip()


def render(bundle: ContentBundle) -> RenderResult:
    images = [ImageAsset("card_01.png", _cover_card(bundle))]
    for repo in bundle.repos[:DETAIL_COUNT]:
        images.append(
            ImageAsset(f"card_{len(images) + 1:02d}.png", _detail_card(bundle, repo))
        )

    chunks = _chunk(bundle.repos[DETAIL_COUNT:], ITEMS_PER_LIST_CARD)
    for part, chunk in enumerate(chunks, start=1):
        images.append(
            ImageAsset(
                f"card_{len(images) + 1:02d}.png",
                _list_card(bundle, chunk, part, len(chunks)),
            )
        )

    note = build_note(bundle)
    hint = f"共 {len(images)} 张图卡，按序号顺序上传，第 1 张即封面。"
    if len(bundle.alt_titles) > 1:
        hint += "\n备选标题：" + " / ".join(bundle.alt_titles[1:])

    copy_fields = [
        CopyField("标题", bundle.social_title, "小红书标题上限 20 字", rows=2),
        CopyField("正文", build_note_body(bundle), rows=16),
    ]
    if bundle.tags:
        copy_fields.append(
            CopyField(
                "话题标签",
                " ".join(f"#{tag}" for tag in bundle.tags),
                "粘贴过去只是普通文字；想进话题页得在正文末尾逐个敲 # 再从下拉里选。",
                rows=2,
            )
        )

    return RenderResult(
        platform=PLATFORM,
        platform_label=PLATFORM_LABEL,
        title=bundle.social_title,
        copy_fields=copy_fields,
        images=images,
        text_files={"note.txt": note},
        hint=hint,
        target_label="打开小红书创作服务平台",
        target_url="https://creator.xiaohongshu.com/publish/publish",
    )
