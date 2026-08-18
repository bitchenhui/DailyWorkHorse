"""本次运行的自述，以及据此拼出的邮件正文。

为什么不复用总览页：总览页扫的是磁盘，列的是**站点上现有的一切**；邮件要说
的却是「这一趟干了什么」。上午那趟的成品原样留在站点上，下午这趟的邮件把它
算成自己的产出就成了误报。所以本次运行的平台清单必须单独留一份。

模块只依赖标准库与色板常量，不碰 Pillow：邮件在装依赖失败时也得发得出去。
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from renderers.theme import ACCENT, INK, MUTED

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


def _platform_url(draft_url: str, platform: str) -> str:
    if not draft_url:
        return ""
    return f"{draft_url.rstrip('/')}/{platform}/index.html"


def subject_for(record: dict | None) -> str:
    """主题一眼说清这趟的结论，正文才有人点开。"""
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


def _entry(item: dict, draft_url: str) -> str:
    label = html.escape(str(item.get("label") or item.get("platform") or ""))
    title = html.escape(str(item.get("title") or ""))
    url = _platform_url(draft_url, str(item.get("platform") or ""))
    action = (
        f'<a href="{html.escape(url, quote=True)}" '
        f'style="color:{ACCENT};text-decoration:none;font-weight:600;">去发布 →</a>'
        if url
        else ""
    )
    return (
        f'<tr><td style="padding:12px 0;border-bottom:1px solid #e8eaef;">'
        f'<div style="font-size:15px;font-weight:600;color:{INK};">{label}</div>'
        f'<div style="font-size:13px;line-height:1.6;color:{MUTED};">{title}</div>'
        f"</td>"
        f'<td style="padding:12px 0;border-bottom:1px solid #e8eaef;'
        f'text-align:right;white-space:nowrap;font-size:13px;">{action}</td></tr>'
    )


def _notes(record: dict) -> str:
    """把「今天没得发」与「跑挂了」分开写，两者的下一步动作完全不同。"""
    blocks = []
    for label, key, color in (
        ("今天没有内容", "idle", MUTED),
        ("失败", "failed", "#c0392b"),
    ):
        items = [str(item) for item in record.get(key) or []]
        if not items:
            continue
        lines = "".join(
            f'<li style="margin:2px 0;">{html.escape(item)}</li>' for item in items
        )
        blocks.append(
            f'<p style="margin:16px 0 4px;font-size:13px;font-weight:600;'
            f'color:{color};">{label}</p>'
            f'<ul style="margin:0;padding-left:18px;font-size:13px;'
            f'line-height:1.8;color:{MUTED};">{lines}</ul>'
        )
    return "".join(blocks)


def build_email(root: Path, draft_url: str, run_url: str) -> tuple[str, str]:
    """读回记录拼出（主题, HTML 正文）。

    记录缺失说明这趟在收尾之前就断了——那封邮件更该发，只是内容退化成
    「去看日志」。
    """
    record = read_record(root)
    subject = subject_for(record)

    if record is None:
        body = (
            "<p>本次运行没有留下记录，说明它在收尾之前就中断了"
            "（依赖安装、测试或采集阶段）。</p>"
        )
        return subject, _page(subject, body, run_url)

    platforms = record.get("platforms") or []
    rows = "".join(_entry(item, draft_url) for item in platforms)
    body = ""
    if rows:
        body += (
            '<table style="width:100%;border-collapse:collapse;">'
            f"{rows}</table>"
        )
        overview = draft_url.rstrip("/") + "/index.html" if draft_url else ""
        if overview:
            body += (
                f'<p style="margin:20px 0 0;font-size:13px;">'
                f'<a href="{html.escape(overview, quote=True)}" '
                f'style="color:{ACCENT};text-decoration:none;">打开分发总览 →</a></p>'
            )
    else:
        body += '<p style="font-size:14px;">这一趟没有产出成稿。</p>'

    body += _notes(record)
    return subject, _page(subject, body, run_url)


def _page(subject: str, body: str, run_url: str) -> str:
    run_link = (
        f'<p style="margin:24px 0 0;font-size:12px;color:{MUTED};">'
        f'<a href="{html.escape(run_url, quote=True)}" style="color:{MUTED};">'
        f"查看运行详情 →</a></p>"
        if run_url
        else ""
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:24px;background:#f5f6f8;
  font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;">
  <div style="max-width:560px;margin:0 auto;padding:24px;background:#ffffff;
    border-radius:10px;">
    <h1 style="margin:0 0 18px;font-size:17px;line-height:1.5;color:{INK};">
      {html.escape(subject)}</h1>
    {body}
    {run_link}
  </div>
</body>
</html>
"""
