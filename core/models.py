"""平台无关的统一内容模型。

`RepoItem` 与 `Editorial` 是 TypedDict：运行时就是普通 dict，因此采集、渲染、
投递各层可以直接互传，无需序列化，同时又有明确的字段契约。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict


class RepoItem(TypedDict):
    """信息源产出的单条领域对象。"""

    rank: int
    full_name: str
    url: str
    description: str
    language: str
    stars_total: int
    stars_today: int


class Editorial(TypedDict):
    """LLM 为单条内容生成的编辑信息，rank 4 起 what/why/who 为空串。"""

    summary: str
    what: str
    why: str
    who: str


EMPTY_EDITORIAL: Editorial = {"summary": "", "what": "", "why": "", "who": ""}


@dataclass
class ContentBundle:
    """管线的腰：上游只负责填充它，下游所有平台只依赖它。

    后续阶段会补充小红书/短视频所需的 ``alt_titles``、``lede``、``tags``，
    当前阶段仅包含公众号长图文实际用到的字段。
    """

    slug: str
    date_text: str
    title: str
    repos: list[RepoItem] = field(default_factory=list)
    editorial: dict[int, Editorial] = field(default_factory=dict)
    alt_titles: list[str] = field(default_factory=list)
    lede: str = ""
    tags: list[str] = field(default_factory=list)

    def editorial_for(self, rank: int) -> Editorial | None:
        return self.editorial.get(rank)

    def summary_for(self, repo: RepoItem) -> str:
        item = self.editorial_for(repo["rank"]) or {}
        return item.get("summary") or repo.get("description") or "暂无简介"

    @property
    def social_title(self) -> str:
        """社交平台优先用钩子式标题，缺失时退回公众号主标题。"""
        return self.alt_titles[0] if self.alt_titles else self.title


def as_editorial(raw: dict[str, Any]) -> Editorial:
    """把任意 dict 规整成 Editorial，缺失字段补空串。"""
    return {
        "summary": str(raw.get("summary") or "").strip(),
        "what": str(raw.get("what") or "").strip(),
        "why": str(raw.get("why") or "").strip(),
        "who": str(raw.get("who") or "").strip(),
    }
