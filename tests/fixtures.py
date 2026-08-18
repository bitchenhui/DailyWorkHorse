"""测试共用的内容夹具。"""

from __future__ import annotations

from core.models import (
    ContentBundle,
    FlowPoint,
    MarketBundle,
    RepoItem,
    Sector,
    Stock,
)


def make_repos(count: int = 10) -> list[RepoItem]:
    return [
        {
            "rank": i,
            "full_name": f"acme/project-{i}",
            "url": f"https://github.com/acme/project-{i}",
            "description": f"An example repository number {i}",
            "language": ["Python", "Rust", "Go", "TypeScript"][i % 4],
            "stars_today": 2000 - i * 137,
            "stars_total": 50000 - i * 3111,
        }
        for i in range(1, count + 1)
    ]


def make_bundle(count: int = 10) -> ContentBundle:
    repos = make_repos(count)
    return ContentBundle(
        slug="2026-08-17-github-trending",
        date_text="2026-08-17",
        title=f"开源升温榜｜近 24 小时增长最快的 {count} 个 GitHub 项目",
        repos=repos,
        editorial={
            repo["rank"]: {
                "summary": f"第 {repo['rank']} 个项目的中文摘要文本",
                "what": "这个项目是什么的说明" if repo["rank"] <= 3 else "",
                "why": "这个项目上涨原因的说明" if repo["rank"] <= 3 else "",
                "who": "这个项目适合关注的人群" if repo["rank"] <= 3 else "",
            }
            for repo in repos
        },
        alt_titles=["近 24h GitHub 涨最快的项目", "备选标题二"],
        lede="每天扒一遍 GitHub Trending，两分钟看完最新的开源风向。",
        tags=["GitHub", "开源项目", "程序员"],
    )


def make_series(
    final: float, minutes: int = 30, shape: float = 1.0
) -> list[FlowPoint]:
    """一条从 0 走到 ``final`` 的累计净流入曲线。

    真实数据是累计值，所以夹具也必须单调累加，否则测不出真实的名次行为。

    ``shape`` 是进度的指数：小于 1 开盘就冲高后走平，大于 1 全天按兵不动、
    尾盘才拉起来。**必须让不同行拿到不同的 shape**，否则所有曲线成比例、
    名次从第一帧起就固定，一切与「名次会变」相关的测试都会变成空转。
    """
    return [
        {
            "time": f"{9 + (index + 31) // 60:02d}:{(index + 31) % 60:02d}",
            "net_inflow": final * ((index + 1) / minutes) ** shape,
        }
        for index in range(minutes)
    ]


# 煤炭与基础化工的形状是刻意配的：前者全天垫底、最后两分钟才超过后者。
# 这个尾盘反超正是「定格帧停在换位半路上」的复现条件。
SECTOR_INFLOW = (
    ("农林牧渔", 22.5e8, 0.8),
    ("石油石化", 4.1e8, 1.0),
    ("房地产", 2.0e8, 0.5),
    ("煤炭", 1.8e8, 27.0),
    ("基础化工", 0.8e8, 0.4),
)
SECTOR_OUTFLOW = (
    ("电子", -172.3e8, 1.4),
    ("通信", -111.6e8, 0.9),
    ("计算机", -66.6e8, 1.1),
    ("电力设备", -45.9e8, 2.0),
    ("有色金属", -44.8e8, 0.6),
)
STOCK_INFLOW = (
    ("京东方Ａ", 5.5e8, 0.7), ("立昂微", 4.1e8, 1.3), ("彩虹股份", 3.7e8, 0.9),
    ("盈新发展", 3.5e8, 1.8), ("金牛化工", 3.5e8, 0.6), ("拓荆科技", 3.2e8, 1.0),
)
STOCK_OUTFLOW = (
    ("中际旭创", -15.8e8, 1.2), ("新易盛", -14.0e8, 0.8), ("工业富联", -12.8e8, 1.6),
    ("长鑫科技", -12.5e8, 0.5), ("紫光股份", -10.9e8, 1.1), ("东山精密", -10.7e8, 0.9),
)


def make_market_bundle(minutes: int = 30) -> MarketBundle:
    """一期行情日报。

    ``minutes`` 是分钟曲线的长度。默认远短于真实的 242 分钟——渲染一帧是
    1080×1920，测试里没必要跑满一整天。
    """

    def sectors(rows, base: int) -> list[Sector]:
        return [
            {
                "code": f"BK{base + index}",
                "name": name,
                "change_pct": 1.2 - index * 0.3,
                "net_inflow": value,
                "net_ratio": 3.1 - index * 0.4,
                "series": make_series(value, minutes, shape),
            }
            for index, (name, value, shape) in enumerate(rows)
        ]

    def stocks(rows, base: int) -> list[Stock]:
        return [
            {
                "code": f"{base + index}",
                "name": name,
                "price": 12.3 + index,
                "change_pct": 2.0 - index * 0.6,
                "net_inflow": value,
                "net_ratio": 1.5 - index * 0.2,
                "series": make_series(value, minutes, shape),
            }
            for index, (name, value, shape) in enumerate(rows)
        ]

    return MarketBundle(
        slug="2026-08-18-market-flow",
        date_text="2026-08-18",
        title="2026-08-18 A股主力资金：农林牧渔净流入 23 亿",
        indexes=[
            {"code": "000001", "name": "上证指数", "price": 3963.2, "change_pct": -0.49},
            {"code": "399001", "name": "深证成指", "price": 14505.0, "change_pct": -1.36},
            {"code": "399006", "name": "创业板指", "price": 3678.0, "change_pct": -1.66},
        ],
        sector_inflow=sectors(SECTOR_INFLOW, 900),
        sector_outflow=sectors(SECTOR_OUTFLOW, 800),
        stock_inflow=stocks(STOCK_INFLOW, 600000),
        stock_outflow=stocks(STOCK_OUTFLOW, 600100),
    )
