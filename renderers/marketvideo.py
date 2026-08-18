"""行情竖屏视频：行业板块的主力资金赛跑。

数据是**当日累计**主力净流入的分钟序列，所以名次会真的随时间翻转——
开盘领先的板块常在尾盘被反超，这是静态榜单给不了的东西。

三段结构：封面预告 → 板块资金赛跑 → 结论定格页。个股不再单独走一段
赛跑（观众常反馈没注意到已经切到个股），改为把当日流入/流出前三收进
结论页一次给全，视频主线只剩「行业资金赛跑」一条。

一个排版上的判断：

- **单一标尺，不给流出组单独放大**。流入前五动辄几百亿、流出前五只有几十亿时，
  流出的条会短到几乎看不见——但这个悬殊本身就是当天最重要的信息（资金单边
  抢筹），双标尺会把它抹平。折中办法是给条形一个最小可见长度兜底。

板块段 31 行，行高按条目数自适应：写死行高必然要么挤出画布要么空半屏。
行矮到一定程度还要换掉整个行样式，见 ``COMPACT_CARD``。

帧以生成器逐帧吐出，不在内存里堆整段视频：1080×1920 一帧就是 6MB，
二十多秒的量足以把内存吃穿。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Sequence

from PIL import Image, ImageDraw

from core.models import MarketBundle
from renderers import encode
from renderers.base import CopyField, RenderResult, VideoAsset
from renderers.fonts import load_font, text_width
from renderers.theme import (
    ACCENT,
    FALL,
    FALL_SOFT,
    RISE,
    RISE_SOFT,
    STAGE,
    STAGE_INK,
    STAGE_LINE,
    STAGE_MUTED,
    STAGE_PANEL,
)

PLATFORM = "xhs_video"
PLATFORM_LABEL = "小红书视频"
TITLE_LIMIT = 20
TAGS = ("A股", "股市", "资金流向", "行情复盘")

WIDTH, HEIGHT = 1080, 1920
FPS = encode.FPS
MARGIN = 72
# 赛道上下都贴到极限：31 行摊下来每行不到 50px，省出来的每一点都是行高。
TRACK_TOP = 260
TRACK_BOTTOM = 1800
# 名次平滑：每帧向目标位置靠拢的比例。太大像瞬移，太小追不上收盘排名。
GLIDE = 0.3
# 滑行收尾的帧数上限。正常十来帧就位，这里只是防止阈值取太严时空转。
SETTLE_FRAMES = 30
# 卡片高占行距的比例。留出的空隙决定了两行挨多近才会看着糊在一起。
CARD_RATIO = 0.72
# 卡片矮于此值就改走单行样式。
#
# 两行式（名称在上、色条在下）需要卡片高到能上下分层：色条从 0.62 高处起画，
# 而名称字号有 24px 的下限（再小手机上读不清），卡片一矮于 56px 两者就必然
# 相交。31 个行业摊下来卡片只有 35px，所以板块段整段走单行样式。
COMPACT_CARD = 56
# 标尺平滑：跟着当前峰值走但不逐帧跳变，否则整屏条形一直在抖。
SCALE_GLIDE = 0.12
# 条形的最小可见长度。数值太小时至少留一截，让人知道它存在而不是渲染坏了。
MIN_BAR = 26
# 名次交换的迟滞阈值，按当前标尺的比例取。见 _reorder。
# 取小值：够大才压得住数值接近时的每帧抖动，但太大会让榜尾长期停在错误顺序上
# ——流入头部动辄几百亿，而流出组彼此只差几千万，阈值跟着峰值走很容易过粗。
SWAP_MARGIN = 0.0025


@dataclass(frozen=True)
class LayoutFrame:
    """某一时刻的画面状态。``slots`` 是各行的名次位置（可为小数，即滑行中）。"""

    moment: str
    values: list[float]
    slots: list[float]
    scale: float


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


def _header(draw: ImageDraw.ImageDraw, title: str, subtitle: str = "") -> None:
    draw.text((MARGIN, 96), title, font=load_font(60, bold=True), fill=STAGE_INK)
    if subtitle:
        draw.text((MARGIN, 186), subtitle, font=load_font(32), fill=STAGE_MUTED)


# 交易时段（分钟）：上午 09:31–11:30、下午 13:01–15:00，各 119 分钟。
# 午休那段没有数据点，时刻会从 11:30 直接跳到 13:01，映射到进度条上就是
# 停在正中，正好当成「上半场打完」。
_AM_START, _AM_END = 9 * 60 + 31, 11 * 60 + 30
_PM_START, _PM_END = 13 * 60 + 1, 15 * 60
_AM_LEN = _AM_END - _AM_START
_SESSION_LEN = _AM_LEN + (_PM_END - _PM_START)


def _session_progress(moment: str) -> float:
    """把 "HH:MM" 映射到当日交易进度 [0,1]，午休按半场处理。"""
    try:
        minutes = int(moment[:2]) * 60 + int(moment[3:5])
    except (ValueError, IndexError):
        return 0.0
    if minutes <= _AM_START:
        return 0.0
    if minutes <= _AM_END:
        return (minutes - _AM_START) / _SESSION_LEN
    if minutes < _PM_START:
        return _AM_LEN / _SESSION_LEN
    if minutes >= _PM_END:
        return 1.0
    return (_AM_LEN + (minutes - _PM_START)) / _SESSION_LEN


def _session_bar(draw: ImageDraw.ImageDraw, moment: str) -> None:
    """会话进度条：9:31 ━━●──── 15:00，当前时刻浮在滑块正上方。

    比一个裸的 HH:MM 数字多给一层「离收盘还有多远」的进度感——越往后
    条越满，收盘时填满，观众能感到这一天在往前走。
    """
    end_font = load_font(26)
    left, right = "9:31", "15:00"
    left_w = text_width(left, end_font)
    right_w = text_width(right, end_font)

    x0, x1 = MARGIN, WIDTH - MARGIN
    track_left = x0 + left_w + 20
    track_right = x1 - right_w - 20
    y = 232
    height = 8
    radius = height // 2

    frac = _session_progress(moment)
    mark_x = int(track_left + (track_right - track_left) * frac)

    draw.text((x0, y - 9), left, font=end_font, fill=STAGE_MUTED)
    draw.text((x1 - right_w, y - 9), right, font=end_font, fill=STAGE_MUTED)

    draw.rounded_rectangle(
        (track_left, y, track_right, y + height), radius=radius, fill=STAGE_LINE
    )
    draw.rounded_rectangle(
        (track_left, y, max(track_left + height, mark_x), y + height),
        radius=radius, fill=ACCENT,
    )
    dot = 12
    cy = y + height // 2
    draw.ellipse(
        (mark_x - dot, cy - dot, mark_x + dot, cy + dot),
        fill=ACCENT, outline=STAGE, width=3,
    )

    time_font = load_font(36, bold=True)
    time_w = text_width(moment, time_font)
    time_x = min(max(mark_x - time_w // 2, x0), x1 - time_w)
    draw.text((time_x, 172), moment, font=time_font, fill=ACCENT)


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
    """把可用高度摊给 ``count`` 行，返回（行距，卡片高）。

    卡片高按行距的固定比例取，而不是「行距减去固定间隙」：后者在行多的时候
    （板块段 31 行）几乎把间隙吃光，两行只要挨近一点就糊成一片。
    """
    span = (TRACK_BOTTOM - TRACK_TOP) / max(count, 1)
    card = int(min(104, span * CARD_RATIO))
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
        fill=STAGE_PANEL, outline=STAGE_LINE, width=1,
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


def _slim_row(
    draw: ImageDraw.ImageDraw,
    y: float,
    card: int,
    name: str,
    value_text: str,
    ratio: float,
    color: str,
    soft: str,
) -> None:
    """单行样式：名称、色条、数值横向排开，三者共用一条基线。

    行数多到卡片只剩三十几个像素时，两行式的名称与色条会直接压在一起。
    这里把纵向分层改成横向分栏，代价是色条短了一截，换来的是每行都读得清。
    """
    top = int(y)
    draw.rounded_rectangle(
        (MARGIN, top, WIDTH - MARGIN, top + card), radius=int(card * 0.28),
        fill=STAGE_PANEL, outline=STAGE_LINE, width=1,
    )

    size = max(20, int(card * 0.52))
    font = load_font(size, bold=True)
    # 字形基本落在字号高度内，居中就按字号算；再往上提一点点补视觉重心。
    text_top = top + (card - size) // 2 - int(size * 0.12)

    pad = 16
    left, right = MARGIN + pad, WIDTH - MARGIN - pad
    draw.text((left, text_top), name, font=font, fill=STAGE_INK)
    draw.text(
        (right - text_width(value_text, font), text_top),
        value_text,
        font=font,
        fill=color,
    )

    # 两侧留固定列宽而不是按实测文字宽度让位：列宽一致，各行的色条才起止对齐，
    # 长短才可比。申万一级行业名最长四个字（如「农林牧渔」），4.4 个字宽够用；
    # 右侧数值最宽形如「-172.3亿」，给到 5.2 个字宽。
    bar_left = left + int(size * 4.4)
    bar_right = right - int(size * 5.2)
    if bar_right <= bar_left:
        return

    height = max(8, int(card * 0.30))
    bar_top = top + (card - height) // 2
    bar_bottom = bar_top + height
    radius = height // 2

    draw.rounded_rectangle(
        (bar_left, bar_top, bar_right, bar_bottom), radius=radius, fill=soft
    )
    span = max(MIN_BAR, int((bar_right - bar_left) * max(0.0, min(ratio, 1.0))))
    draw.rounded_rectangle(
        (bar_left, bar_top, bar_left + span, bar_bottom), radius=radius, fill=color
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


def layout(rows: Sequence[dict]) -> Iterator[LayoutFrame]:
    """逐帧推演画面状态，不碰像素。

    抽出来是为了能直接断言「同一帧里没有两行叠在一起」——
    这类毛病在成片里只表现为「少了一行」，靠看视频很难定位。
    """
    axis, lookup = _timeline(rows)
    count = len(rows)
    values = [0.0] * count
    order = list(range(count))
    # 初始名次即入场顺序，各就各位不做开场动画。
    slots = [float(index) for index in range(count)]
    scale = 0.0

    for moment in axis:
        for index in range(count):
            value = lookup[index].get(moment)
            if value is not None:
                values[index] = value

        peak = max((abs(value) for value in values), default=1.0) or 1.0
        scale = peak if scale <= 0 else scale + (peak - scale) * SCALE_GLIDE

        _reorder(order, values, peak * SWAP_MARGIN)
        for rank, index in enumerate(order):
            slots[index] += (rank - slots[index]) * GLIDE

        yield LayoutFrame(moment, list(values), list(slots), scale)

    if not axis:
        return

    # 数据放完后继续滑行到各就各位，再交给定格。
    # 收盘那一刻名次往往刚翻转，直接定格就会把观众唯一会认真读的一帧
    # 停在两张卡片叠着的半路上。
    for _ in range(SETTLE_FRAMES):
        if max(abs(slots[index] - rank) for rank, index in enumerate(order)) < 0.01:
            break
        for rank, index in enumerate(order):
            slots[index] += (rank - slots[index]) * GLIDE
        yield LayoutFrame(axis[-1], list(values), list(slots), scale)


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

    span, card = _row_metrics(len(tracked))
    paint = _bar_row if card >= COMPACT_CARD else _slim_row
    image = None

    for frame in layout(tracked):
        image, draw = _canvas()
        _header(draw, title, subtitle)
        _session_bar(draw, frame.moment)

        # 从下往上画：名次靠前的后画，交换过程中榜首永远压在最上层，
        # 不会被正在上升的那张卡片盖住。
        for index in sorted(range(len(tracked)), key=lambda i: frame.slots[i], reverse=True):
            value = frame.values[index]
            color, soft = _tone(value)
            paint(
                draw,
                TRACK_TOP + frame.slots[index] * span,
                card,
                tracked[index]["name"],
                _fmt_yi(value),
                abs(value) / frame.scale,
                color,
                soft,
            )
        _disclaimer(draw)
        yield image

    if image is None:
        return

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
    """封面：标题 + 大盘变化 + 当日资金之最（流入/流出各前二）。

    预告放两端各前二的板块，既填满版面，也让划到这一帧的人立刻知道
    接下来要讲什么。封面只停很短一下就切进赛跑，别让开头卡着不动。
    """
    image, draw = _canvas()

    draw.text((MARGIN, 196), "A 股日报", font=load_font(32, bold=True), fill=ACCENT)
    draw.text(
        (MARGIN, 248), "今日资金流向", font=load_font(88, bold=True), fill=STAGE_INK
    )
    draw.text(
        (MARGIN, 372),
        f"{date_text} · 主力资金当日累计净流入",
        font=load_font(40),
        fill=STAGE_MUTED,
    )

    draw.rounded_rectangle(
        (MARGIN, 452, WIDTH - MARGIN, 772), radius=44,
        fill=STAGE_PANEL, outline=STAGE_LINE, width=1,
    )
    draw.text((MARGIN + 40, 486), "大盘变化", font=load_font(32, bold=True), fill=STAGE_MUTED)
    _index_strip(draw, indexes, 592)

    draw.rounded_rectangle(
        (MARGIN, 822, WIDTH - MARGIN, 1560), radius=44,
        fill=STAGE_PANEL, outline=STAGE_LINE, width=1,
    )
    draw.text((MARGIN + 40, 856), "今日之最", font=load_font(32, bold=True), fill=STAGE_MUTED)

    picks = [(label, row) for label, row in zip(("流入榜首", "流入第二"), list(inflow)[:2])]
    picks += [(label, row) for label, row in zip(("流出榜首", "流出第二"), list(outflow)[:2])]
    for order, (label, row) in enumerate(picks):
        _highlight(draw, 944 + order * 150, label, row["name"], row["net_inflow"])

    draw.text(
        (MARGIN, 1610),
        "钱从哪个行业流出，又流进了谁",
        font=load_font(38),
        fill=STAGE_MUTED,
    )
    _disclaimer(draw)

    for _ in range(max(1, int(seconds * FPS))):
        yield image


def _flow_line(
    draw: ImageDraw.ImageDraw,
    y: int,
    name: str,
    value: float,
    *,
    size: int = 40,
    rank: int | None = None,
    tag: str | None = None,
) -> None:
    """结论页里的一行：可选序号/标签 + 名称在左，金额在右按红绿着色。"""
    color, _ = _tone(value)
    font = load_font(size, bold=True)
    x = MARGIN + 40
    if rank is not None:
        draw.text(
            (x, y + int(size * 0.08)),
            str(rank),
            font=load_font(size - 6, bold=True),
            fill=STAGE_MUTED,
        )
        x += 46
    if tag is not None:
        tag_font = load_font(26)
        draw.text((x, y + int(size * 0.2)), tag, font=tag_font, fill=STAGE_MUTED)
        x += int(text_width(tag, tag_font)) + 20
    draw.text((x, y), name, font=font, fill=STAGE_INK)
    text = _fmt_yi(value)
    draw.text(
        (WIDTH - MARGIN - 40 - text_width(text, font), y),
        text,
        font=font,
        fill=color,
    )


# 结论页个股块固定高度：标题一行 + 前三三行，够装且两块不至于挤在一起。
CLOSING_TOP3 = 3


def _stock_block(
    draw: ImageDraw.ImageDraw,
    top: int,
    label: str,
    label_color: str,
    soft: str,
    stocks: Sequence[dict],
) -> None:
    """结论页的个股块：标题 + 前三。抢筹用红块、抛售用绿块。"""
    draw.rounded_rectangle(
        (MARGIN, top, WIDTH - MARGIN, top + 380),
        radius=44, fill=soft, outline=STAGE_LINE, width=1,
    )
    draw.text((MARGIN + 40, top + 30), label, font=load_font(30, bold=True), fill=label_color)
    for order, stock in enumerate(list(stocks)[:CLOSING_TOP3]):
        _flow_line(
            draw, top + 100 + order * 88, stock["name"], stock["net_inflow"],
            size=42, rank=order + 1,
        )


def _closing_frames(bundle: MarketBundle, seconds: float) -> Iterator[Image.Image]:
    """结尾结论定格页：一句话主线 → 板块两端（呼应主线）→ 个股前三。

    板块结论在上、个股前三在下，分区呈现：先用板块两端坐实「今日结论」那
    句话，再把当日抢筹/抛售的个股前三附在下面。个股不再单独走赛跑，最终
    名次都收在这里一次给全。视频号/抖音会把最后这一帧当封面缩略图，所以
    要能独立成图、一眼读懂。
    """
    top_in = bundle.sector_inflow[0] if bundle.sector_inflow else None
    top_out = bundle.sector_outflow[0] if bundle.sector_outflow else None

    image, draw = _canvas()

    draw.text((MARGIN, 196), "今日结论", font=load_font(32, bold=True), fill=ACCENT)
    # 一句话主线：钱从哪流到哪。缺一端就退成半句，不硬凑。
    if top_in and top_out:
        headline = f"{top_in['name']}吸金，{top_out['name']}失血"
    elif top_in:
        headline = f"{top_in['name']}吸金领跑"
    else:
        headline = "今日资金主线"
    draw.text((MARGIN, 256), headline, font=load_font(72, bold=True), fill=STAGE_INK)

    # 板块两端：坐实上面那句结论，给出行业榜首的具体数字。
    draw.rounded_rectangle(
        (MARGIN, 440, WIDTH - MARGIN, 700), radius=44,
        fill=STAGE_PANEL, outline=STAGE_LINE, width=1,
    )
    draw.text((MARGIN + 40, 470), "板块资金两端", font=load_font(30, bold=True), fill=STAGE_MUTED)
    if top_in:
        _flow_line(draw, 534, top_in["name"], top_in["net_inflow"], size=52, tag="流入")
    if top_out:
        _flow_line(draw, 616, top_out["name"], top_out["net_inflow"], size=52, tag="流出")

    # 个股前三：附在板块结论下面，抢筹一块、抛售一块。
    _stock_block(draw, 736, "个股抢筹前三", RISE, RISE_SOFT, bundle.stock_inflow)
    _stock_block(draw, 1148, "个股抛售前三", FALL, FALL_SOFT, bundle.stock_outflow)

    draw.text(
        (MARGIN, 1566),
        "红为主力净流入，绿为净流出",
        font=load_font(30),
        fill=STAGE_MUTED,
    )
    draw.text(
        (MARGIN, 1626),
        "关注一下，每天一分钟看懂 A 股资金去向",
        font=load_font(38, bold=True),
        fill=STAGE_INK,
    )
    _disclaimer(draw)

    for _ in range(max(1, int(seconds * FPS))):
        yield image


def frames(bundle: MarketBundle) -> Iterator[Image.Image]:
    """整支视频的帧序列：封面 → 板块赛跑 → 结论页。

    个股不再单独走一段动态赛跑——早先那一段跟在板块后面，观众常反馈没
    注意到已经切到个股。现在把个股收进结论页的 TOP3，视频主线只剩「行业
    资金赛跑」一条，个股作为结论落点一次给全。
    """
    yield from _cover_frames(
        bundle.indexes,
        bundle.sector_inflow,
        bundle.sector_outflow,
        bundle.date_text,
        # 封面只当个引子，很快切进赛跑——停太久开头会像卡住不动。
        seconds=0.2,
    )
    yield from _race_frames(
        bundle.sectors,
        "A股各板块资金流向",
        # 不带副标题：多一行小字反而挤，标题一句已说清是什么。
        "",
        # 31 行需要给够读完的时间。
        hold_seconds=2.5,
    )
    yield from _closing_frames(bundle, seconds=1.0)


def build_social_title(bundle: MarketBundle) -> str:
    """小红书标题上限 20 字，所以按信息量从多到少试，取第一个装得下的。"""
    candidates: list[str] = []
    top_in = bundle.sector_inflow[0] if bundle.sector_inflow else None
    top_out = bundle.sector_outflow[0] if bundle.sector_outflow else None

    if top_in and top_out:
        candidates.append(
            f"{top_in['name']}吸金{top_in['net_inflow'] / 1e8:.0f}亿，"
            f"{top_out['name']}被砸{abs(top_out['net_inflow']) / 1e8:.0f}亿"
        )
    if top_in:
        candidates.append(f"{top_in['name']}吸金{top_in['net_inflow'] / 1e8:.0f}亿")
    candidates.append(f"{bundle.date_text} A股资金流向")

    for candidate in candidates:
        if len(candidate) <= TITLE_LIMIT:
            return candidate
    return candidates[-1][:TITLE_LIMIT]


def _flow_lines(rows: Sequence[dict]) -> list[str]:
    return [f"{row['name']} {_fmt_yi(row['net_inflow'])}" for row in rows]


def build_note(bundle: MarketBundle) -> str:
    """笔记正文，不含标题与话题——这两样在小红书是独立输入框。"""
    lines = [f"📈 {bundle.date_text} A股主力资金流向。", ""]

    if bundle.indexes:
        lines.append(
            " · ".join(
                f"{index['name']} {_fmt_pct(index['change_pct'])}"
                for index in bundle.indexes
            )
        )
        lines.append("")

    for emoji, label, rows in (
        ("🔥", "资金流入最多的行业", bundle.sector_inflow),
        ("💸", "资金流出最多的行业", bundle.sector_outflow),
        ("🚀", "被抢筹最多的个股", bundle.stock_inflow),
        ("📉", "被抛售最多的个股", bundle.stock_outflow),
    ):
        if not rows:
            continue
        lines.append(f"{emoji} {label}")
        lines.extend(_flow_lines(rows))
        lines.append("")

    lines.append("⚠️ 主力资金指特大单与大单的净额，数据来自公开行情接口。")
    lines.append("仅作信息展示，不构成投资建议。")
    return "\n".join(lines).strip()


def render(bundle: MarketBundle) -> RenderResult:
    """行情日报的成品：一支竖屏视频，外加发布用的三段文案。"""
    note = build_note(bundle)
    social_title = build_social_title(bundle)

    # 帧工厂而不是帧列表：整段视频放不进内存，见 VideoAsset 的说明。
    video = VideoAsset(f"market{encode.preferred_suffix()}", lambda: frames(bundle))

    copy_fields = [
        CopyField("标题", social_title, f"小红书标题上限 {TITLE_LIMIT} 字", rows=2),
        CopyField("正文", note, rows=18),
        CopyField(
            "话题标签",
            " ".join(f"#{tag}" for tag in TAGS),
            "粘贴过去只是普通文字；想进话题页得在正文末尾逐个敲 # 再从下拉里选。",
            rows=2,
        ),
    ]

    return RenderResult(
        platform=PLATFORM,
        platform_label=PLATFORM_LABEL,
        title=social_title,
        copy_fields=copy_fields,
        videos=[video],
        text_files={"note.txt": f"{social_title}\n\n{note}\n"},
        hint=(
            "先下载视频再上传，发布时选「视频笔记」；"
            "封面用视频首帧即可，不必另配图。"
        ),
        target_label="打开小红书创作服务平台",
        target_url="https://creator.xiaohongshu.com/publish/publish",
    )
