"""为榜单生成中文摘要与 Top3 深度解读。"""

from __future__ import annotations

import json
import re
from typing import Any

from core import llm
from core.console import safe_print
from core.models import EMPTY_EDITORIAL, Editorial, RepoItem, as_editorial

SYSTEM_PROMPT = (
    "你是面向中文开发者的开源观察编辑。根据给定仓库信息生成编辑内容。\n"
    "要求：\n"
    "1. 所有项目都写 summary：中文一句话说明项目是什么，18–32 字，"
    "信息具体，不逐字翻译英文简介\n"
    "2. 仅 rank 1–3 额外写 what/why/who，各 25–45 字；"
    "rank 4 以后这三项填空字符串\n"
    "3. why 只能基于输入合理概括其关注价值，不要声称已知社交媒体传播、"
    "版本发布等未提供事实\n"
    "4. 语气专业克制，不用营销腔，不得编造功能，句末不加句号\n"
    "5. 只输出 JSON 数组，不要代码块、不要解释：\n"
    '[{"rank":1,"summary":"...","what":"...","why":"...","who":"..."}]\n'
    "6. 每个输入 rank 必须且只能出现一次"
)


def _load_items(raw: str) -> list[Any]:
    body = llm.strip_code_fence(raw)
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", body, re.S)
        if not match:
            raise RuntimeError(f"LLM 未返回可解析 JSON: {body[:500]}")
        return json.loads(match.group(0))


def _collect(items: list[Any], expected_ranks: set[int]) -> dict[int, Editorial]:
    result: dict[int, Editorial] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            rank = int(item.get("rank"))
        except (TypeError, ValueError):
            continue
        if rank not in expected_ranks:
            continue
        result[rank] = as_editorial(item)
    return result


def parse_editorial(raw: str, expected_ranks: set[int]) -> dict[int, Editorial]:
    """解析并校验模型返回的 TopN 中文编辑内容。"""
    result = _collect(_load_items(raw), expected_ranks)

    missing = expected_ranks - result.keys()
    no_summary = [rank for rank, item in result.items() if not item["summary"]]
    if missing or no_summary:
        raise RuntimeError(
            f"LLM 编辑内容不完整，缺少排名={sorted(missing)}，"
            f"缺少摘要={sorted(no_summary)}"
        )
    return result


def _fallback_summary(repo: RepoItem) -> str:
    desc = " ".join((repo.get("description") or "").split())
    if desc:
        return desc[:48] + ("…" if len(desc) > 48 else "")
    return f"{repo.get('full_name', '未知仓库')} 近期新增关注"


def _build_user_prompt(repos: list[RepoItem]) -> str:
    payload = [
        {
            "rank": r["rank"],
            "full_name": r["full_name"],
            "description": r["description"],
            "language": r["language"],
            "stars_total": r["stars_total"],
            "stars_today": r["stars_today"],
        }
        for r in repos
    ]
    return (
        "榜单数据（stars_today 为近 24 小时新增星标，非自然日）：\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def generate(repos: list[RepoItem]) -> dict[int, Editorial]:
    """为 Top10 生成一句话摘要，并为前三名补充结构化深读。"""
    user = _build_user_prompt(repos)
    expected = {r["rank"] for r in repos}

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            return parse_editorial(llm.complete(SYSTEM_PROMPT, user), expected)
        except Exception as exc:  # noqa: BLE001 — 允许一次重试
            last_error = exc
            safe_print(f"  编辑内容解析失败，重试中（{attempt + 1}/2）: {exc}")

    # 最后兜底：尽量用已解析部分 + 英文简介填空，避免 Actions 整单失败
    try:
        raw = llm.complete(SYSTEM_PROMPT, user)
        try:
            items = _load_items(raw)
        except RuntimeError:
            items = []
        partial = _collect(items if isinstance(items, list) else [], expected)
        for repo in repos:
            item = partial.setdefault(repo["rank"], dict(EMPTY_EDITORIAL))  # type: ignore[arg-type]
            if not item["summary"]:
                item["summary"] = _fallback_summary(repo)
        safe_print("  已启用摘要兜底，保证榜单可推送")
        return partial
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"LLM 编辑内容连续失败: {last_error}; 兜底也失败: {exc}"
        ) from exc
