"""人设主题选题：加载人设、确定今天的主题、组装 TopicBundle。

主题的优先级：显式指定（``--topic`` / ``TOPIC_OVERRIDE``，来自本地命令行或
workflow 手动触发的输入框）→ 自动选题。自动选题拿 ``persona.md`` 里的常聊
领域当池子、当天 GitHub Trending 前五当素材，并避开上一期刚发过的主题——
CI 会先把 gh-pages 取回 dist，上一期的 ``note.txt`` 就在那里。
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from core.config import CST, DIST_DIR, PROJECT_ROOT
from core.console import safe_print
from core.models import RepoItem, TopicBundle
from enrich import topic as topic_enricher
from sources import github_trending

PLATFORM = "xhs_topic"
DIST_SUBDIR = "xhs_topic"
PERSONA_FILENAME = "persona.md"
DEFAULT_KICKER = "今日主题"
FUEL_COUNT = 5


def persona_path() -> Path:
    return PROJECT_ROOT / PERSONA_FILENAME


def load_persona(path: Path | None = None) -> str:
    """读入人设全文。这是这条管线的配置项，缺失属于配置错误，要当场炸出来。"""
    path = path or persona_path()
    if not path.is_file():
        raise SystemExit(
            f"人设文件不存在：{path}\n"
            f"先照仓库里的 {PERSONA_FILENAME} 模板填写你自己的信息，再启用 {PLATFORM}"
        )
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit(f"人设文件是空的：{path} —— 至少写一句「我是谁」")
    return text


def extract_section(text: str, name: str) -> str:
    """取 persona.md 里 ``## name`` 小节的正文；模板没写就返回空串。"""
    match = re.search(
        rf"^##\s*{re.escape(name)}\s*$\n(.*?)(?=^##\s|\Z)", text, re.M | re.S
    )
    return match.group(1).strip() if match else ""


def first_line(text: str) -> str:
    """小节正文的第一行实值，跳过说明性质的行：模板占位（「（示例…）」）
    与 Markdown 引用（作者笔记）。"""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith(">"):
            continue
        line = line.lstrip(">").strip()
        if line and not line.startswith("（示例"):
            return line
    return ""


def resolve_topic() -> tuple[str, str]:
    """显式主题优先；没有就交给自动选题。返回 (主题原文, 来源备注)。"""
    override = os.environ.get("TOPIC_OVERRIDE", "").strip()
    if override:
        return override, "手动指定"
    return "", "自动选题"


def previous_topic() -> str:
    """上一期主题，用于自动选题时避重；本地首跑没有站点就是空串。"""
    note = DIST_DIR / DIST_SUBDIR / "note.txt"
    try:
        return note.read_text(encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        return ""


def fetch_fuel(limit: int = FUEL_COUNT) -> str:
    """当天的 GitHub Trending 前几名，给自动选题当引子。

    素材抓不到不该挡住出稿——自动选题退化为纯靠人设池子，只是少了
    「蹭今天正在发生的事」的机会。
    """
    try:
        repos: list[RepoItem] = github_trending.fetch(limit)
    except Exception as exc:  # noqa: BLE001 — 素材是锦上添花，不是必需品
        safe_print(f"  当日素材抓取失败，自动选题仅依赖人设：{exc}")
        return ""
    return "\n".join(
        f"- {r['full_name']}（{r['language'] or '未知语言'}，"
        f"近24h +{r['stars_today']}★）：{r['description']}"
        for r in repos
    )


def build_topic_bundle() -> TopicBundle:
    safe_print("加载人设 …")
    persona = load_persona()
    kicker = first_line(extract_section(persona, "固定栏目名")) or DEFAULT_KICKER
    disclaimer = " ".join(extract_section(persona, "免责声明").split())

    topic, source_note = resolve_topic()
    if topic:
        safe_print(f"本期主题（手动指定）：{topic}")
        fuel = ""
    else:
        safe_print("未指定主题，自动选题：抓当日素材 …")
        fuel = fetch_fuel()

    avoid = previous_topic()
    if avoid:
        safe_print(f"自动选题将避开上一期主题：{avoid}")

    safe_print("按人设生成主题内容 …")
    copy = topic_enricher.generate(persona=persona, topic=topic, fuel=fuel, avoid=avoid)

    date_text = datetime.now(CST).strftime("%Y-%m-%d")
    final_topic = topic or copy.topic
    return TopicBundle(
        slug=f"{date_text}-xhs-topic",
        date_text=date_text,
        title=final_topic,
        topic=final_topic,
        alt_titles=copy.titles,
        lede=copy.hook,
        tags=copy.tags,
        hook=copy.hook,
        points=copy.points,
        closing=copy.closing,
        kicker=kicker,
        disclaimer=disclaimer,
        source_note=source_note,
    )
