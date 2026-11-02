"""人设主题图卡渲染：1080×1440 竖版「封面 + 观点页 + 结尾互动」。

与榜单图卡「信息主体在图里」不同，这里的图是**观点的载体**：封面给钩子，
中间每页一个论点，结尾一张互动卡收束。正文（note）保留主题原句与全部
小标题，命中站内搜索。

版式沿用同一套纪律：所有绘制文本先 ``sanitize``，内容高度先测量再居中，
留白落在版面结构之外而不是卡片内部。
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from core.models import TopicBundle, TopicPoint
from renderers.base import CopyField, ImageAsset, RenderResult
from renderers.fonts import fit_font_size, load_font, sanitize, text_width, wrap
from renderers.theme import (
    TOPIC_ACCENT,
    TOPIC_ACCENT_SOFT,
    TOPIC_BG,
    TOPIC_BODY,
    TOPIC_INK,
    TOPIC_LINE,
    TOPIC_MUTED,
)

PLATFORM = "xhs_topic"
PLATFORM_LABEL = "小红书·主题"

WIDTH = 1080
HEIGHT = 1440
MARGIN = 84
CONTENT_WIDTH = WIDTH - MARGIN * 2

# 深色结尾卡上的浅字，仅此处使用。
CLOSING_TEXT = "#f7f1e5"
CLOSING_DIM = "#c4b294"
CLOSING_FAINT = "#8d7c62"

HEADING_MAX_LINES = 2
BODY_MAX_LINES = 10
HEADING_LINE_HEIGHT = 86
BODY_LINE_HEIGHT = 62
HEADING_BODY_GAP = 52
# 观点页内容块的上下界：大序号水印和页码占掉两头，中间留给正文居中。
POINT_TOP_LIMIT = 350
POINT_BOTTOM_LIMIT = HEIGHT - 210


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


def _big_title_font(text: str, tiers: tuple[tuple[int, int, int], ...]):
    """按长度分档字号：短句放大号才撑得起封面，长句缩小避免三行装不下。"""
    for max_len, size, line_height in tiers:
        if len(text) <= max_len:
            return load_font(size, bold=True), line_height
    return load_font(tiers[-1][1], bold=True), tiers[-1][2]


def _pill(
    draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, background: str, color: str
) -> None:
    """左上角的栏目标签，超长时缩字号，绝不顶出画布。"""
    x, y = xy
    font = fit_font_size(text, CONTENT_WIDTH - 120, 28, 18, bold=True)
    pad_x, pad_y = 26, 13
    width = int(text_width(text, font)) + pad_x * 2
    height = font.size + pad_y * 2
    draw.rounded_rectangle((x, y, x + width, y + height), radius=height / 2, fill=background)
    draw.text((x + pad_x, y + pad_y - 2), text, font=font, fill=color)


def _cover_card(bundle: TopicBundle) -> Image.Image:
    image, draw = _canvas(TOPIC_BG)

    draw.ellipse((790, -260, 1390, 340), fill=TOPIC_ACCENT_SOFT)
    draw.ellipse((-200, 1120, 360, 1680), fill=TOPIC_ACCENT_SOFT)

    _pill(draw, (MARGIN, 128), sanitize(bundle.kicker), TOPIC_ACCENT, "#ffffff")

    title = sanitize(bundle.social_title)
    title_font, title_line_height = _big_title_font(
        title, ((8, 100, 136), (13, 88, 120), (20, 76, 104))
    )
    title_lines = wrap(title, title_font, CONTENT_WIDTH, max_lines=3)
    y = _draw_lines(draw, (MARGIN, 260), title_lines, title_font, TOPIC_INK, title_line_height)

    rule_y = min(y + 40, 700)
    draw.line((MARGIN, rule_y, WIDTH - MARGIN, rule_y), fill=TOPIC_LINE, width=3)

    # 主题原文与钩子标题相同（自动选题常如此）时不再重复一遍。
    topic_line = sanitize(
        bundle.topic if bundle.topic != bundle.social_title else bundle.hook
    )
    hook_lines = wrap(topic_line, load_font(36), CONTENT_WIDTH, max_lines=3)
    _draw_lines(
        draw, (MARGIN, rule_y + 52), hook_lines, load_font(36), TOPIC_BODY, 56
    )

    footer = f"{bundle.date_text} · {bundle.source_note}"
    draw.text(
        (MARGIN, 1310),
        sanitize(footer),
        font=load_font(26),
        fill=TOPIC_MUTED,
    )
    return image


def _point_card(point: TopicPoint, index: int, total: int) -> Image.Image:
    image, draw = _canvas(TOPIC_BG)

    watermark = f"{index:02d}"
    watermark_font = load_font(240, bold=True)
    draw.text((MARGIN - 10, 60), watermark, font=watermark_font, fill=TOPIC_ACCENT_SOFT)

    heading_font = load_font(64, bold=True)
    heading_lines = wrap(
        sanitize(point["heading"]), heading_font, CONTENT_WIDTH, max_lines=HEADING_MAX_LINES
    )
    body_font = load_font(40)
    body_lines = wrap(
        sanitize(point["body"]), body_font, CONTENT_WIDTH, max_lines=BODY_MAX_LINES
    )

    block_height = (
        len(heading_lines) * HEADING_LINE_HEIGHT
        + HEADING_BODY_GAP
        + len(body_lines) * BODY_LINE_HEIGHT
    )
    # 短内容在上下界之间居中：空白沉到版面结构外的均匀呼吸感里，
    # 而不是全部堆在卡片底部。
    y = POINT_TOP_LIMIT + max(
        0, (POINT_BOTTOM_LIMIT - POINT_TOP_LIMIT - block_height) // 2
    )

    draw.rounded_rectangle(
        (MARGIN, y + 14, MARGIN + 10, y + 14 + HEADING_LINE_HEIGHT * len(heading_lines) - 30),
        radius=5,
        fill=TOPIC_ACCENT,
    )
    y = _draw_lines(
        draw,
        (MARGIN + 34, y),
        heading_lines,
        heading_font,
        TOPIC_INK,
        HEADING_LINE_HEIGHT,
    )
    _draw_lines(
        draw, (MARGIN + 34, y + HEADING_BODY_GAP), body_lines, body_font, TOPIC_BODY, BODY_LINE_HEIGHT
    )

    progress = f"{index:02d} / {total:02d}"
    draw.text(
        (MARGIN, 1310),
        progress,
        font=load_font(26, bold=True),
        fill=TOPIC_MUTED,
    )
    return image


def _closing_card(bundle: TopicBundle) -> Image.Image:
    image, draw = _canvas(TOPIC_INK)

    draw.ellipse((760, -220, 1360, 380), fill="#453a2d")
    draw.ellipse((-180, 1080, 400, 1660), fill="#453a2d")

    _pill(draw, (MARGIN, 150), sanitize("聊一聊"), TOPIC_ACCENT, "#ffffff")

    closing = sanitize(bundle.closing)
    closing_font, closing_line_height = _big_title_font(
        closing, ((12, 84, 116), (20, 72, 100), (30, 60, 86))
    )
    closing_lines = wrap(closing, closing_font, CONTENT_WIDTH, max_lines=3)
    y = _draw_lines(
        draw, (MARGIN, 330), closing_lines, closing_font, CLOSING_TEXT, closing_line_height
    )

    draw.text(
        (MARGIN, y + 60),
        "评论区聊聊你的情况",
        font=load_font(36, bold=True),
        fill=CLOSING_DIM,
    )

    if bundle.disclaimer:
        disclaimer_lines = wrap(
            sanitize(bundle.disclaimer), load_font(26), CONTENT_WIDTH, max_lines=2
        )
        _draw_lines(
            draw,
            (MARGIN, 1240),
            disclaimer_lines,
            load_font(26),
            CLOSING_FAINT,
            40,
        )
    else:
        draw.text(
            (MARGIN, 1240), bundle.date_text, font=load_font(26), fill=CLOSING_FAINT
        )
    return image


def build_note_body(bundle: TopicBundle) -> str:
    """笔记正文，不含标题与话题——这两样在小红书是独立输入框。

    emoji 只出现在复制到小红书的文本里，图卡渲染前会被 ``sanitize`` 剥掉。
    """
    lines: list[str] = []
    if bundle.hook:
        lines.extend([bundle.hook, ""])
    # 主题原句与钩子标题不同时补进正文，命中站内搜索；相同则标题框里已有。
    if bundle.topic and bundle.topic != bundle.social_title:
        lines.extend([bundle.topic, ""])
    for index, point in enumerate(bundle.points, start=1):
        lines.append(f"{index:02d}｜{point['heading']}")
        lines.append(point["body"])
        lines.append("")
    if bundle.closing:
        lines.extend([f"💬 {bundle.closing}", ""])
    if bundle.disclaimer:
        lines.append(bundle.disclaimer)
    return "\n".join(lines).strip()


def build_note(bundle: TopicBundle) -> str:
    """存档用的完整笔记：标题、正文、话题拼成一份，便于事后回看。"""
    parts = [bundle.social_title, "", build_note_body(bundle)]
    if bundle.tags:
        parts.extend(["", " ".join(f"#{tag}" for tag in bundle.tags)])
    return "\n".join(parts).strip() + "\n"


def render(bundle: TopicBundle) -> RenderResult:
    images = [ImageAsset("card_01.png", _cover_card(bundle))]
    total = len(bundle.points)
    for index, point in enumerate(bundle.points, start=1):
        images.append(
            ImageAsset(f"card_{len(images) + 1:02d}.png", _point_card(point, index, total))
        )
    images.append(ImageAsset(f"card_{len(images) + 1:02d}.png", _closing_card(bundle)))

    note = build_note(bundle)
    hint = f"共 {len(images)} 张图卡，按序号顺序上传，第 1 张即封面。"
    if len(bundle.alt_titles) > 1:
        hint += "\n备选标题：" + " / ".join(bundle.alt_titles[1:])

    copy_fields = [
        CopyField("标题", bundle.social_title, "小红书标题上限 20 字", rows=2),
        CopyField("正文", build_note_body(bundle), rows=14),
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
