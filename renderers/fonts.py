"""图片渲染共用的字体加载与中英混排排版工具。"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from PIL import ImageDraw, ImageFont

# 连续的 ASCII 单词（含常见标识符字符）视为不可断开的最小单元，
# 避免把 owner/repo-name 这类项目名从中间截断。
_WORD = re.compile(r"[A-Za-z0-9]+(?:[._\-+/][A-Za-z0-9]+)*")

# 中文字体没有 emoji 字形，直接绘制会出现豆腐块。这里剥离 emoji 区段，
# 但避开自己在用的 ★(U+2605)、→(U+2192)、·(U+00B7) 等符号。
_EMOJI = re.compile(
    "[\U0001f000-\U0001ffff"
    "\ufe00-\ufe0f\u200d"
    "\u2600-\u2604\u2606-\u27bf"
    "\u2b00-\u2bff]"
)


def sanitize(text: str) -> str:
    """剥离无法渲染的字符并折叠空白，供图片渲染使用。"""
    return " ".join(_EMOJI.sub("", text or "").split())


def _candidates(bold: bool) -> list[str]:
    windows = os.environ.get("WINDIR", r"C:\Windows")
    if bold:
        return [
            str(Path(windows) / "Fonts" / "msyhbd.ttc"),
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    return [
        str(Path(windows) / "Fonts" / "msyh.ttc"),
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]


@lru_cache(maxsize=64)
def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for candidate in _candidates(bold):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def text_width(text: str, font: ImageFont.ImageFont) -> float:
    return font.getlength(text)


def center_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: str,
) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    width = box[2] - box[0]
    height = box[3] - box[1]
    draw.text((xy[0] - width / 2, xy[1] - height / 2), text, font=font, fill=fill)


def _tokenize(text: str) -> list[str]:
    """切成最小换行单元：英文单词整体保留，中文逐字。"""
    tokens: list[str] = []
    index = 0
    for match in _WORD.finditer(text):
        tokens.extend(text[index : match.start()])
        tokens.append(match.group(0))
        index = match.end()
    tokens.extend(text[index:])
    return tokens


def wrap(
    text: str,
    font: ImageFont.ImageFont,
    max_width: float,
    max_lines: int | None = None,
) -> list[str]:
    """按像素宽度折行，超出 ``max_lines`` 时在末行加省略号。"""
    lines: list[str] = []
    current = ""
    for token in _tokenize(sanitize(text)):
        if token == "\n":
            lines.append(current.rstrip())
            current = ""
            continue
        candidate = current + token
        if current and text_width(candidate, font) > max_width:
            lines.append(current.rstrip())
            current = token.lstrip() if token.strip() else ""
        else:
            current = candidate
    if current.strip():
        lines.append(current.rstrip())

    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and text_width(last + "…", font) > max_width:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines


def fit_font_size(
    text: str, max_width: float, start: int, minimum: int, bold: bool = False
) -> ImageFont.FreeTypeFont:
    """单行不折行场景：从 ``start`` 逐级缩小字号直到放得下。"""
    size = start
    while size > minimum:
        font = load_font(size, bold=bold)
        if text_width(text, font) <= max_width:
            return font
        size -= 2
    return load_font(minimum, bold=bold)
