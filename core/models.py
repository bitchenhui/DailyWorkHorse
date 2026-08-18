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


class FlowPoint(TypedDict):
    """资金流分钟序列上的一个点。``net_inflow`` 是**当日累计**净流入（元）。"""

    time: str
    net_inflow: float


class IndexQuote(TypedDict):
    code: str
    name: str
    price: float
    change_pct: float


class Sector(TypedDict):
    """行业板块的当日资金流。``series`` 为空表示曲线没取到。"""

    code: str
    name: str
    change_pct: float
    net_inflow: float
    net_ratio: float
    series: list[FlowPoint]


class Stock(TypedDict):
    code: str
    name: str
    price: float
    change_pct: float
    net_inflow: float
    net_ratio: float
    series: list[FlowPoint]


EMPTY_EDITORIAL: Editorial = {"summary": "", "what": "", "why": "", "who": ""}


@dataclass
class Bundle:
    """所有信息源共有的部分：一期内容的身份与社交平台文案。

    子类补充各自的领域数据。因为基类已有带默认值的字段，
    **子类新增字段必须也带默认值**，否则 dataclass 会拒绝生成 __init__。
    """

    slug: str
    date_text: str
    title: str
    alt_titles: list[str] = field(default_factory=list)
    lede: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def social_title(self) -> str:
        """社交平台优先用钩子式标题，缺失时退回主标题。"""
        return self.alt_titles[0] if self.alt_titles else self.title


@dataclass
class ContentBundle(Bundle):
    """管线的腰：上游只负责填充它，下游所有平台只依赖它。"""

    repos: list[RepoItem] = field(default_factory=list)
    editorial: dict[int, Editorial] = field(default_factory=dict)

    def editorial_for(self, rank: int) -> Editorial | None:
        return self.editorial.get(rank)

    def summary_for(self, repo: RepoItem) -> str:
        item = self.editorial_for(repo["rank"]) or {}
        return item.get("summary") or repo.get("description") or "暂无简介"

    @property
    def social_title(self) -> str:
        """社交平台优先用钩子式标题，缺失时退回公众号主标题。"""
        return self.alt_titles[0] if self.alt_titles else self.title


@dataclass
class MarketBundle(Bundle):
    """行情日报的领域数据：指数快照，以及资金流的两端。

    流入与流出分开存而不是合成一张榜，是因为它们是两次不同的排序请求，
    合并后再想还原「哪些是榜首、哪些是榜尾」反而要重新判断。
    """

    indexes: list[IndexQuote] = field(default_factory=list)
    sector_inflow: list[Sector] = field(default_factory=list)
    sector_outflow: list[Sector] = field(default_factory=list)
    stock_inflow: list[Stock] = field(default_factory=list)
    stock_outflow: list[Stock] = field(default_factory=list)

    @property
    def sectors(self) -> list[Sector]:
        """按净流入从高到低排好的板块全集，画面按这个顺序入场。"""
        return self.sector_inflow + self.sector_outflow

    @property
    def stocks(self) -> list[Stock]:
        return self.stock_inflow + self.stock_outflow


def as_editorial(raw: dict[str, Any]) -> Editorial:
    """把任意 dict 规整成 Editorial，缺失字段补空串。"""
    return {
        "summary": str(raw.get("summary") or "").strip(),
        "what": str(raw.get("what") or "").strip(),
        "why": str(raw.get("why") or "").strip(),
        "who": str(raw.get("who") or "").strip(),
    }
