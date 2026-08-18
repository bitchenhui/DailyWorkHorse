"""视觉规范：正文 HTML、封面图与成稿页共用同一套色板与字体栈。"""

from __future__ import annotations

INK = "#1a1d29"
BODY_TEXT = "#3d4351"
MUTED = "#8b93a3"
HAIRLINE = "#e8eaef"
SURFACE = "#ffffff"
PAPER = "#f5f6f8"
ACCENT = "#0f6f63"
ACCENT_SOFT = "#e7f2f0"

# 行情视频走白底财经风：刻意与 GitHub 深色图卡拉开距离，两个信息源摆在一起
# 不至于像同一个号发的。A 股约定红涨绿跌，与欧美股市正好相反，别照搬配色。
STAGE = "#ffffff"
STAGE_PANEL = "#f4f6f9"
STAGE_INK = "#1a1d29"
STAGE_MUTED = "#8b93a3"
# 白底描边：卡片和白画布之间要一条极淡的界线，否则浅灰卡片会糊进背景。
STAGE_LINE = "#e6e9ef"
RISE = "#e23c3c"
RISE_SOFT = "#fdecec"
FALL = "#0f9d58"
FALL_SOFT = "#e6f5ee"
# 图卡与公众号正文里的星标色。Pillow 画不出 emoji 星，用字形 ★ 着金色。
STAR_GOLD = "#f5a623"

FONT = (
    "-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB',"
    "'Microsoft YaHei',sans-serif"
)
MONO = "'SF Mono',SFMono-Regular,Menlo,Consolas,monospace"
