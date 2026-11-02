"""为人设主题图卡生成内容：定题、钩子、观点展开、收尾互动与话题标签。

与 ``social.py`` 的模板兜底不同，这里失败就抛错：整期内容都是按人设写出来
的，没有人设口吻的兜底稿毫无意义——宁可让当天这趟标红、由运行报告提醒，
也不能发一篇「谁写的都行」的东西充数。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from core import llm
from core.console import safe_print
from core.models import TopicPoint
from enrich.social import clean_tags, fit_title

# 卡面小标题最多两行，超过会被渲染层截断，这里在源头就压住。
HEADING_LIMIT = 18
BODY_MIN = 20
MIN_POINTS, MAX_POINTS = 3, 5

SYSTEM_PROMPT = (
    "你是一位中文自媒体写手，严格按照给定的人设为小红书写一期主题图文。\n"
    "要求：\n"
    "1. topic：本期主题的一句话表述。要具体、有小切口（聊一个场景、一种现象、\n"
    "一个决定），不写「论 X 的重要性」这类大而空的题\n"
    "2. titles：3 个标题候选，每个 10–20 字（含标点），必须是完整通顺的短句，\n"
    "有具体信息量的钩子；不堆砌 emoji，不用「震惊」「速看」这类标题党用语\n"
    "3. hook：开场导语 40–60 字，口语但不浮夸，把读者带进主题\n"
    f"4. points：{MIN_POINTS}–{MAX_POINTS} 个观点，按递进排列；heading 不超过 "
    f"{HEADING_LIMIT} 字，body 60–130 字——口语化、有具体信息或例子，\n"
    "每条独立成页，不要写成目录式的空话\n"
    "5. closing：结尾抛给读者的互动问题，15–40 字，让人有话可答\n"
    "6. tags：6–8 个话题词，只写词本身不要 # 号，覆盖主题领域与目标人群\n"
    "7. 人设说什么就是什么：不编造人设之外的经历、数据与断言；给定素材只作\n"
    "引入参考，不得声称其为实时数据\n"
    "8. 只输出 JSON 对象，不要代码块、不要解释：\n"
    '{"topic":"...","titles":["...","...","..."],"hook":"...",'
    '"points":[{"heading":"...","body":"..."}],"closing":"...","tags":["..."]}'
)


@dataclass
class TopicCopy:
    """LLM 产出的一期主题内容，字段与 TopicBundle 一一对应。"""

    topic: str = ""
    titles: list[str] = field(default_factory=list)
    hook: str = ""
    points: list[TopicPoint] = field(default_factory=list)
    closing: str = ""
    tags: list[str] = field(default_factory=list)


def _load_object(raw: str) -> dict:
    body = llm.strip_code_fence(raw)
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", body, re.S)
        if not match:
            raise RuntimeError(f"LLM 未返回可解析 JSON: {body[:500]}")
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise RuntimeError(f"期望 JSON 对象，实际得到 {type(data).__name__}")
    return data


def _clean_points(raw: object) -> list[TopicPoint]:
    points: list[TopicPoint] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        heading = " ".join(str(item.get("heading") or "").split())
        body = " ".join(str(item.get("body") or "").split())
        if not heading or len(body) < BODY_MIN:
            continue
        points.append({"heading": heading[:HEADING_LIMIT], "body": body})
    return points[:MAX_POINTS]


def parse_topic(raw: str) -> TopicCopy:
    """解析并校验模型返回的一期内容，任何关键件缺失都算整单失败。"""
    data = _load_object(raw)

    topic = " ".join(str(data.get("topic") or "").split())
    titles = [t for t in (fit_title(item) for item in data.get("titles") or []) if t]
    hook = " ".join(str(data.get("hook") or "").split())
    points = _clean_points(data.get("points"))
    closing = " ".join(str(data.get("closing") or "").split())
    tags = clean_tags(data.get("tags"))

    problems = []
    if not topic:
        problems.append("缺 topic")
    if not titles:
        problems.append("缺可用 titles")
    if not hook:
        problems.append("缺 hook")
    if len(points) < MIN_POINTS:
        problems.append(f"可用观点不足 {MIN_POINTS} 个（{len(points)}）")
    if not closing:
        problems.append("缺 closing")
    if len(tags) < 3:
        problems.append("话题标签不足 3 个")
    if problems:
        raise RuntimeError("LLM 主题内容不完整：" + "；".join(problems))

    return TopicCopy(
        topic=topic, titles=titles, hook=hook, points=points, closing=closing, tags=tags
    )


def _build_user_prompt(persona: str, topic: str, fuel: str, avoid: str) -> str:
    sections = [f"=== 人设 ===\n{persona}", "=== 今日安排 ==="]
    if topic:
        sections.append(f"指定主题：{topic}（topic 字段照抄或微调这句话）")
    else:
        sections.append(
            "今天没有指定主题：请从人设的常聊领域里，结合下面的当日素材"
            "（如有）找一个相关的具体切入点，自己定题。"
        )
    if fuel:
        sections.append(f"=== 当日素材（仅作选题与引入参考） ===\n{fuel}")
    if avoid:
        sections.append(f"=== 必须避开 ===\n这个主题最近刚发过：{avoid}")
    return "\n\n".join(sections)


def generate(persona: str, topic: str, fuel: str, avoid: str) -> TopicCopy:
    """按人设写一期内容；两次尝试都失败就抛错，不做无人设的兜底。"""
    user = _build_user_prompt(persona, topic, fuel, avoid)

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            return parse_topic(llm.complete(SYSTEM_PROMPT, user))
        except Exception as exc:  # noqa: BLE001 — 允许一次重试
            last_error = exc
            safe_print(f"  主题内容解析失败，重试中（{attempt + 1}/2）: {exc}")

    raise RuntimeError(f"LLM 主题内容连续失败: {last_error}")
