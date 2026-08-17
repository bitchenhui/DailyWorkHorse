"""行情竖屏视频：行业板块与个股的主力资金赛跑。

数据是**当日累计**主力净流入的分钟序列，所以名次会真的随时间翻转——
开盘领先的板块常在尾盘被反超，这是静态榜单给不了的东西。

两段结构：先板块讲「钱从哪个行业流到哪个行业」，再个股落到具体标的。
先宏观后微观，符合日报的信息层次。

两个排版上的判断：

- **单一标尺，不给流出组单独放大**。流入前五动辄几百亿、流出前五只有几十亿时，
  流出的条会短到几乎看不见——但这个悬殊本身就是当天最重要的信息（资金单边
  抢筹），双标尺会把它抹平。折中办法是给条形一个最小可见长度兜底。
- **行高按条目数自适应**。板块段 10 行、个股段 12 行，写死行高必然有一段
  要么挤出画布要么空半屏。

帧以生成器逐帧吐出，不在内存里堆整段视频：1080×1920 一帧就是 6MB，
二十多秒的量足以把内存吃穿。
"""

from __future__ import annotations

from typing import Iterator, Sequence

from PIL import Image, ImageDraw

from renderers.fonts import load_font, text_width
from renderers.theme import (
    FALL,
    FALL_SOFT,
    RISE,
    RISE_SOFT,
    STAGE,
    STAGE_INK,
    STAGE_MUTED,
    STAGE_PANEL,
)

WIDTH, HEIGHT = 1080, 1920
FPS = 25
MARGIN = 72
TRACK_TOP = 330
TRACK_BOTTOM = 1790
# 名次平滑：每帧向目标位置靠拢的比例。太大像瞬移，太小追不上收盘排名。
GLIDE = 0.3
# 标尺平滑：跟着当前峰值走但不逐帧跳变，否则整屏条形一直在抖。
SCALE_GLIDE = 0.12
# 条形的最小可见长度。数值太小时至少留一截，让人知道它存在而不是渲染坏了。
MIN_BAR = 26
# 名次交换的迟滞阈值，按当前标尺的比例取。见 _reorder。
# 取小值：够大才压得住数值接近时的每帧抖动，但太大会让榜尾长期停在错误顺序上
# ——流入头部动辄几百亿，而流出组彼此只差几千万，阈值跟着峰值走很容易过粗。
SWAP_MARGIN = 0.0025


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), STAGE)
    return image, ImageDraw.Draw(image)


def _fmt_pct(value: float) -> str:
    return f"{value:+.2f}%"


def _fmt_yi(value: float) -> str:
    """元 → 亿元。资金流的量级只有亿看得懂。"""
    return f"{value / 1e8:+.1f}亿"


def _tone(value: float) -> tuple[str, str]:
    """A 股红涨绿跌，与欧美相反，别照搬配色。"""
    return (RISE, RISE_SOFT) if value >= 0 else (FALL, FALL_SOFT)


def _header(draw: ImageDraw.ImageDraw, title: str, subtitle: str) -> None:
    draw.text((MARGIN, 96), title, font=load_font(60, bold=True), fill=STAGE_INK)
    draw.text((MARGIN, 186), subtitle, font=load_font(32), fill=STAGE_MUTED)


def _clock(draw: ImageDraw.ImageDraw, moment: str) -> None:
    font = load_font(52, bold=True)
    draw.text(
        (WIDTH - MARGIN - text_width(moment, font), 100),
        moment,
        font=font,
        fill=STAGE_INK,
    )


def _disclaimer(draw: ImageDraw.ImageDraw) -> None:
    """行情内容必须挂免责声明，且要每帧都在——观众可能从任意一帧划入。"""
    draw.text(
        (MARGIN, HEIGHT - 88),
        "数据来自公开行情接口，仅作信息展示，不构成投资建议",
        font=load_font(26),
        fill=STAGE_MUTED,
    )


def _index_strip(draw: ImageDraw.ImageDraw, indexes: Sequence[dict], y: int) -> None:
    """三大指数并排，作为全天基调的背景板。"""
    if not indexes:
        return
    slot = (WIDTH - MARGIN * 2) // len(indexes)
    for position, index in enumerate(indexes):
        x = MARGIN + slot * position
        color, _ = _tone(index["change_pct"])
        draw.text((x, y), index["name"], font=load_font(28), fill=STAGE_MUTED)
        draw.text(
            (x, y + 42),
            _fmt_pct(index["change_pct"]),
            font=load_font(40, bold=True),
            fill=color,
        )


def _row_metrics(count: int) -> tuple[float, int]:
    """把可用高度摊给 ``count`` 行，返回（行距，卡片高）。"""
    span = (TRACK_BOTTOM - TRACK_TOP) / max(count, 1)
    card = int(min(104, span - 14))
    return span, card


def _bar_row(
    draw: ImageDraw.ImageDraw,
    y: float,
    card: int,
    name: str,
    value_text: str,
    ratio: float,
    color: str,
    soft: str,
) -> None:
    """一整张不透明卡片：名称在左、数值在右，下方一条按 ratio 伸缩的色条。

    做成卡片而不是裸文字，是因为名次交换时相邻两行会短暂重叠——
    裸文字重叠会被切成半截，卡片重叠只是一张压着另一张，观感能接受。
    """
    top = int(y)
    draw.rounded_rectangle(
        (MARGIN, top, WIDTH - MARGIN, top + card), radius=int(card * 0.22),
        fill=STAGE_PANEL,
    )

    pad = 22
    left, right = MARGIN + pad, WIDTH - MARGIN - pad
    bar_top = top + int(card * 0.62)
    bar_bottom = bar_top + max(10, int(card * 0.16))
    radius = (bar_bottom - bar_top) // 2

    draw.rounded_rectangle((left, bar_top, right, bar_bottom), radius=radius, fill=soft)
    span = max(MIN_BAR, int((right - left) * max(0.0, min(ratio, 1.0))))
    draw.rounded_rectangle(
        (left, bar_top, left + span, bar_bottom), radius=radius, fill=color
    )

    font = load_font(max(24, int(card * 0.36)), bold=True)
    text_top = top + int(card * 0.12)
    draw.text((left, text_top), name, font=font, fill=STAGE_INK)
    draw.text(
        (right - text_width(value_text, font), text_top),
        value_text,
        font=font,
        fill=color,
    )


def _reorder(order: list[int], latest: Sequence[float], margin: float) -> None:
    """就地维护名次，只有差距超过 ``margin`` 才交换。

    直接按数值排序会出事：两个数值接近的条目（比如同为 -18 亿出头的两个板块）
    会每帧互换名次，各自向中点收敛后叠在一起，画面上表现为「少了一行、
    另一处空出一格」。加一道迟滞就稳住了，代价只是名次更新慢半拍。
    """
    swapped = True
    while swapped:
        swapped = False
        for position in range(len(order) - 1):
            upper, lower = order[position], order[position + 1]
            if latest[lower] > latest[upper] + margin:
                order[position], order[position + 1] = lower, upper
                swapped = True


def _timeline(rows: Sequence[dict]) -> tuple[list[str], list[dict[str, float]]]:
    """统一时间轴，以及每行「时刻 → 累计净流入」的查找表。

    各标的的分时长度未必一致（停牌、上市首日等），所以取并集再各自查，
    查不到就沿用上一时刻的值。
    """
    axis = sorted({point["time"] for row in rows for point in row["series"]})
    lookup = [
        {point["time"]: point["net_inflow"] for point in row["series"]}
        for row in rows
    ]
    return axis, lookup


def _race_frames(
    rows: Sequence[dict],
    title: str,
    subtitle: str,
    hold_seconds: float,
) -> Iterator[Image.Image]:
    """一段资金赛跑：逐分钟重排名次，条长按当前累计值。"""
    tracked = [row for row in rows if row.get("series")]
    if not tracked:
        return

    axis, lookup = _timeline(tracked)
    if not axis:
        return

    span, card = _row_metrics(len(tracked))
    glided = [float(index) for index in range(len(tracked))]
    latest = [0.0] * len(tracked)
    order = list(range(len(tracked)))
    scale = 0.0
    image = None

    for moment in axis:
        for index in range(len(tracked)):
            value = lookup[index].get(moment)
            if value is not None:
                latest[index] = value

        peak = max((abs(value) for value in latest), default=1.0) or 1.0
        scale = peak if scale <= 0 else scale + (peak - scale) * SCALE_GLIDE

        _reorder(order, latest, peak * SWAP_MARGIN)
        for rank, index in enumerate(order):
            glided[index] += (rank - glided[index]) * GLIDE

        image, draw = _canvas()
        _header(draw, title, subtitle)
        _clock(draw, moment)

        # 从下往上画：名次靠前的后画，交换过程中榜首永远压在最上层，
        # 不会被正在上升的那张卡片盖住。
        for index in sorted(range(len(tracked)), key=lambda i: glided[i], reverse=True):
            value = latest[index]
            color, soft = _tone(value)
            _bar_row(
                draw,
                TRACK_TOP + glided[index] * span,
                card,
                tracked[index]["name"],
                _fmt_yi(value),
                abs(value) / scale,
                color,
                soft,
            )
        _disclaimer(draw)
        yield image

    # 定格若干秒，给观众读完最终排名的时间。
    for _ in range(int(hold_seconds * FPS)):
        yield image


def _highlight(
    draw: ImageDraw.ImageDraw, y: int, label: str, name: str, value: float
) -> None:
    """封面预告里的一行：左边说明，中间板块名，右边金额。"""
    color, _ = _tone(value)
    draw.text((MARGIN + 40, y), label, font=load_font(28), fill=STAGE_MUTED)
    draw.text((MARGIN + 40, y + 40), name, font=load_font(48, bold=True), fill=STAGE_INK)

    font = load_font(48, bold=True)
    text = _fmt_yi(value)
    draw.text(
        (WIDTH - MARGIN - 40 - text_width(text, font), y + 40),
        text,
        font=font,
        fill=color,
    )


def _cover_frames(
    indexes: Sequence[dict],
    inflow: Sequence[dict],
    outflow: Sequence[dict],
    date_text: str,
    seconds: float,
) -> Iterator[Image.Image]:
    """封面：标题 + 三大指数 + 当日资金之最。

    预告放最大流入与最大流出板块，既填满版面，也让划到这一帧的人
    立刻知道接下来要讲什么。
    """
    image, draw = _canvas()

    draw.text((MARGIN, 196), "A 股日报", font=load_font(30), fill=STAGE_MUTED)
    draw.text(
        (MARGIN, 244), "今日资金流向", font=load_font(78, bold=True), fill=STAGE_INK
    )
    draw.text(
        (MARGIN, 368),
        f"{date_text} · 主力资金当日累计净流入",
        font=load_font(32),
        fill=STAGE_MUTED,
    )

    draw.rounded_rectangle(
        (MARGIN, 470, WIDTH - MARGIN, 790), radius=44, fill=STAGE_PANEL
    )
    _index_strip(draw, indexes, 560)

    draw.rounded_rectangle(
        (MARGIN, 850, WIDTH - MARGIN, 1500), radius=44, fill=STAGE_PANEL
    )
    draw.text((MARGIN + 40, 896), "今日之最", font=load_font(32), fill=STAGE_MUTED)

    labels = ("流入榜首", "流入第二")
    picks = [(labels[order], row) for order, row in enumerate(list(inflow)[:2])]
    picks += [("流出榜首", row) for row in list(outflow)[:1]]
    for order, (label, row) in enumerate(picks):
        _highlight(draw, 986 + order * 160, label, row["name"], row["net_inflow"])

    draw.text(
        (MARGIN, 1596),
        "钱从哪个行业流出，又流进了谁",
        font=load_font(38),
        fill=STAGE_MUTED,
    )
    _disclaimer(draw)

    for _ in range(max(1, int(seconds * FPS))):
        yield image


def frames(data: dict, date_text: str) -> Iterator[Image.Image]:
    """整支视频的帧序列：封面 → 板块赛跑 → 个股赛跑。"""
    indexes = data.get("indexes") or []
    sector_inflow = list(data.get("sector_inflow") or [])
    sector_outflow = list(data.get("sector_outflow") or [])
    sectors = sector_inflow + sector_outflow
    stocks = list(data.get("stock_inflow") or []) + list(
        data.get("stock_outflow") or []
    )

    yield from _cover_frames(
        indexes, sector_inflow, sector_outflow, date_text, seconds=2.4
    )
    yield from _race_frames(
        sectors,
        "钱流进了哪些行业",
        f"{date_text} · 主力资金当日累计净流入",
        hold_seconds=1.6,
    )
    yield from _race_frames(
        stocks,
        "哪些个股在被抢筹",
        f"{date_text} · 主力资金当日累计净流入",
        hold_seconds=2.0,
    )
