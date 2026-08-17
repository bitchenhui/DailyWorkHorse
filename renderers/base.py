"""渲染层协议：所有平台渲染器都产出同一种 ``RenderResult``。

渲染器只描述「成品长什么样」，不决定「写到哪里、怎么发出去」——那是投递层的事。
图片以 PIL 对象形式携带、由投递层落盘，这样将来浏览器自动化投递可以直接复用，
不必假设产物一定先出现在 dist 目录。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from PIL import Image

from core.models import ContentBundle


@dataclass
class ImageAsset:
    name: str
    image: Image.Image

    def save(self, path: Path) -> None:
        self.image.save(path, format="PNG", optimize=True)


@dataclass
class RenderResult:
    """某平台的完整成品。

    ``body_html`` 与 ``body_text`` 按平台取舍：公众号需要富文本，小红书需要纯文本。
    两者都填时，成稿页会同时给出两个复制按钮。
    """

    platform: str
    platform_label: str
    title: str
    body_html: str = ""
    body_text: str = ""
    images: list[ImageAsset] = field(default_factory=list)
    text_files: dict[str, str] = field(default_factory=dict)
    hint: str = ""
    target_label: str = ""
    target_url: str = ""


class Renderer(Protocol):
    platform: str

    def render(self, bundle: ContentBundle) -> RenderResult: ...
