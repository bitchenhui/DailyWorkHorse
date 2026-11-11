"""本次运行的自述（``dist/last-run.json``），以及据此拼出的推送内容。

为什么不复用总览页：总览页扫的是磁盘，列的是**站点上现有的一切**；推送要说
的却是「这一趟干了什么」。上午那趟的成品原样留在站点上，下午这趟的推送把它
算成自己的产出就成了误报。所以本次运行的平台清单必须单独留一份。

推送文案只依赖标准库，不碰 Pillow、不碰 requests：Actions 在装依赖失败时
也得推得出去——那恰恰是最需要被通知的一次运行。
"""

from __future__ import annotations

import json
from pathlib import Path

RECORD = "last-run.json"


def write_record(
    root: Path,
    date_text: str,
    platforms: list[dict],
    idle: list[str],
    failed: list[str],
) -> Path:
    """把这一趟的结果落到 ``dist/last-run.json``。"""
    root.mkdir(parents=True, exist_ok=True)
    path = root / RECORD
    path.write_text(
        json.dumps(
            {
                "date": date_text,
                "platforms": platforms,
                "idle": idle,
                "failed": failed,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def read_record(root: Path) -> dict | None:
    """读回运行记录；文件不在或读坏了都当作「没跑到收尾」。"""
    try:
        record = json.loads((root / RECORD).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def subject_for(record: dict | None) -> str:
    """标题一眼说清这趟的结论，正文才有人点开。"""
    if record is None:
        return "DailyWorkHorse · 生成失败"

    prefix = f"DailyWorkHorse {record.get('date') or ''}".strip()
    platforms = record.get("platforms") or []
    failed = record.get("failed") or []

    if platforms and failed:
        return f"{prefix} · {len(platforms)} 项就绪，{len(failed)} 项失败"
    if platforms:
        labels = "、".join(
            str(item.get("label") or item.get("platform")) for item in platforms
        )
        return f"{prefix} · {labels} 已就绪"
    if failed:
        return f"{prefix} · 生成失败"
    return f"{prefix} · 今天没有可发布的内容"


def body_for(record: dict | None) -> str:
    """推送正文：成稿各一行，没得发与失败分开列，下一步动作各不相同。"""
    if record is None:
        return "本次运行在收尾之前就中断了（依赖安装、测试或采集阶段），点开查看日志。"

    lines: list[str] = []
    for item in record.get("platforms") or []:
        label = str(item.get("label") or item.get("platform") or "")
        title = str(item.get("title") or "")
        lines.append(f"{label}：{title}" if title else label)
    for label, key in (("没有内容", "idle"), ("失败", "failed")):
        for item in record.get(key) or []:
            lines.append(f"{label}｜{item}")

    if not lines:
        lines.append("这一趟没有产出成稿。")
    return "\n".join(lines)


def url_for(record: dict | None, draft_url: str, run_url: str) -> str:
    """点击通知跳哪里：有成稿去分发总览，没有就去运行日志排查。"""
    if record and record.get("platforms") and draft_url:
        return draft_url
    return run_url


def level_for(record: dict | None) -> str:
    """Bark 的打扰级别：失败要穿透专注模式，空跑不该亮屏。"""
    if record is None or record.get("failed"):
        return "timeSensitive"
    if not record.get("platforms"):
        return "passive"
    return "active"


def build_push(
    root: Path, draft_url: str, run_url: str
) -> dict:
    """读回记录拼出 Bark 推送的完整载荷。"""
    record = read_record(root)
    return {
        "title": subject_for(record),
        "body": body_for(record),
        "url": url_for(record, draft_url, run_url),
        "group": "DailyWorkHorse",
        "level": level_for(record),
    }
