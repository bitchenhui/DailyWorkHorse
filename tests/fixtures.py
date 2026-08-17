"""测试共用的内容夹具。"""

from __future__ import annotations

from core.models import ContentBundle, RepoItem


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
        title=f"开源升温榜｜今日增长最快的 {count} 个 GitHub 项目",
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
        alt_titles=["今日 GitHub 涨最快的项目", "备选标题二"],
        lede="每天扒一遍 GitHub Trending，两分钟看完今天的开源风向。",
        tags=["GitHub", "开源项目", "程序员"],
    )
