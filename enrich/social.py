"""生成社交平台文案：钩子标题、导语与话题标签。

与公众号编辑内容分开调用：小红书的标题调性和长度约束差异极大，事后改写不如
一次生成可控。这里的失败一律降级为模板兜底，不能因为社交文案影响公众号出稿。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from core import llm
from core.console import safe_print
from core.models import Editorial, RepoItem

# 小红书标题上限 20 字，超出会被截断。
TITLE_LIMIT = 20
FALLBACK_TAGS = ("GitHub", "开源项目", "程序员", "编程", "开发者", "AI工具")

# emoji 不必再禁：图片渲染前一律走 fonts.sanitize 剥掉，字形缺失画不出豆腐块，
# 而复制到小红书的那份文本里它们原样保留——两边各取所需。
SYSTEM_PROMPT = (
    "你为一份面向中文开发者的 GitHub 每日榜单撰写小红书文案。\n"
    "语气按小红书来：像跟朋友分享，短句、说人话、有具体信息，不端着也不浮夸。\n"
    "要求：\n"
    f"1. titles：3 个标题候选，每个 10–{TITLE_LIMIT} 个字（含标点与 emoji），"
    f"必须是完整通顺的短句，宁可写短也不要写满 {TITLE_LIMIT} 字后被截断。"
    "要有具体信息量的钩子，可点出榜上最突出的项目或趋势；"
    "可以用一个 emoji 起头或收尾，但不要堆砌；"
    "不要「震惊」「绝了」「速看」这类标题党用语\n"
    "2. lede：导语 40–60 字，说明这份榜单是什么、这一期值得看什么，"
    "口语但不浮夸，可穿插一两个 emoji\n"
    "3. tags：6–8 个话题标签，只写词本身不要 # 号，覆盖开源、编程语言、"
    "应用方向等维度，便于站内搜索\n"
    "4. 不得编造输入中不存在的事实\n"
    "5. 只输出 JSON 对象，不要代码块、不要解释：\n"
    '{"titles":["...","...","..."],"lede":"...","tags":["...","..."]}'
)


@dataclass
class SocialCopy:
    titles: list[str] = field(default_factory=list)
    lede: str = ""
    tags: list[str] = field(default_factory=list)


def _build_user_prompt(
    repos: list[RepoItem], editorial: dict[int, Editorial]
) -> str:
    payload = [
        {
            "rank": r["rank"],
            "full_name": r["full_name"],
            "language": r["language"],
            "stars_today": r["stars_today"],
            "summary": (editorial.get(r["rank"], {}) or {}).get("summary", ""),
        }
        for r in repos[:5]
    ]
    # stars_today 是东家的字段名，但含义是近 24 小时增量，给模型讲清楚，
    # 免得它照着字面写出「今天涨了 xxx」这种不准的文案。
    return (
        "榜单前五（stars_today 为近 24 小时新增星标）：\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


TITLE_MIN = 8
# 只认句子级分隔符：在空格或冒号处截断会留下「热榜：AI」这样的残句。
_BREAKPOINTS = "，,。！？!?、；;"


def _fit_title(text: str) -> str | None:
    """超长标题回退到最近的句子级断点，回退不了就丢弃，绝不留残句。"""
    text = " ".join(str(text).split())
    if not text:
        return None
    if len(text) <= TITLE_LIMIT:
        return text
    head = text[:TITLE_LIMIT]
    cut = max(head.rfind(ch) for ch in _BREAKPOINTS)
    if cut >= TITLE_MIN:
        return head[:cut].rstrip(_BREAKPOINTS)
    return None


def _clean_titles(raw: object) -> list[str]:
    titles: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        text = _fit_title(item)
        if text and text not in titles:
            titles.append(text)
    return titles


def _clean_tags(raw: object) -> list[str]:
    tags: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        text = str(item).strip().lstrip("#").strip()
        text = "".join(text.split())
        if text and text not in tags:
            tags.append(text)
    return tags[:8]


def fallback(repos: list[RepoItem]) -> SocialCopy:
    """LLM 不可用时的模板兜底，保证小红书成稿始终能出。"""
    top = repos[0]["full_name"].split("/")[-1] if repos else "开源项目"
    languages = []
    for repo in repos[:5]:
        lang = repo.get("language") or ""
        if lang and lang != "Unknown" and lang not in languages:
            languages.append(lang)
    return SocialCopy(
        titles=[
            "近 24h GitHub 涨最快的项目"[:TITLE_LIMIT],
            f"过去一天最火的开源项目是 {top}"[:TITLE_LIMIT],
        ],
        lede=(
            f"✨ 每天扒一遍 GitHub Trending，按近 24 小时新增 Star 排出前 {len(repos)} 名。"
            "图里有每个项目是什么、为什么突然涨，两分钟看完最新的开源风向 🚀"
        ),
        tags=list(FALLBACK_TAGS) + languages[:2],
    )


def generate(
    repos: list[RepoItem], editorial: dict[int, Editorial]
) -> SocialCopy:
    default = fallback(repos)
    try:
        raw = llm.complete(SYSTEM_PROMPT, _build_user_prompt(repos, editorial))
        body = llm.strip_code_fence(raw)
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError(f"期望 JSON 对象，实际得到 {type(data).__name__}")
    except Exception as exc:  # noqa: BLE001 — 社交文案失败不阻断主流程
        safe_print(f"  社交文案生成失败，使用模板兜底: {exc}")
        return default

    titles = _clean_titles(data.get("titles")) or default.titles
    lede = " ".join(str(data.get("lede") or "").split()) or default.lede
    tags = _clean_tags(data.get("tags")) or default.tags
    return SocialCopy(titles=titles, lede=lede, tags=tags)
