"""投递层协议。

Channel 与 Renderer 正交：同一份渲染产物既可以走 T1 成稿包让人工发布，
也可以在资质或工具就绪后换成 T2 浏览器自动化、T3 官方 API，渲染代码不动。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.models import ContentBundle
from renderers.base import RenderResult


@dataclass
class DeliveryResult:
    channel: str
    ok: bool
    detail: str = ""
    location: str = ""


class Channel(Protocol):
    name: str

    def preflight(self) -> None:
        """校验凭证或登录态，不可用时抛出可读错误。"""
        ...

    def deliver(
        self, bundle: ContentBundle, result: RenderResult
    ) -> DeliveryResult: ...
