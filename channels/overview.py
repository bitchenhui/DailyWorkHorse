"""分发总览页：手机上打开一页，逐个平台完成当日发布。

页面由**磁盘上现有的平台目录**生成，而不是由某一次运行的产物生成。
两个信息源跑在各自的定时任务里，上午那趟的成品在下午这趟的 runner 上
并不存在；只列本次产物就会让总览页每跑一次丢掉另一半。
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from core.config import PLATFORM_LABELS
from renderers.theme import ACCENT, INK, MUTED


def collect(root: Path) -> list[dict]:
    """扫描各平台目录里的 ``meta.json``，按平台注册顺序排好。"""
    order = list(PLATFORM_LABELS)
    entries: list[dict] = []
    for path in root.glob("*/meta.json"):
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # 半截文件不该让整页生成不出来。
            continue
        if isinstance(entry, dict) and entry.get("platform"):
            entries.append(entry)

    entries.sort(
        key=lambda item: (
            order.index(item["platform"]) if item["platform"] in order else len(order),
            item["platform"],
        )
    )
    return entries


def _entry(item: dict) -> str:
    platform = str(item.get("platform", ""))
    counts = [str(count) for count in item.get("counts") or []]
    # 逐条标日期：两条内容来自不同的定时任务，某一趟失败时另一条会留在
    # 前一天的版本上，不标出来就看不出哪条是陈的。
    meta = " · ".join([str(item.get("date", ""))] + counts)
    return f"""    <a class="entry" href="{html.escape(platform, quote=True)}/index.html">
      <span class="body">
        <span class="name">{html.escape(str(item.get('label') or platform))}</span>
        <span class="title">{html.escape(str(item.get('title', '')))}</span>
        <span class="meta">{html.escape(meta)}</span>
      </span>
      <span class="go">去发布 →</span>
    </a>"""


def build_overview_page(entries: list[dict]) -> str:
    date_text = max((str(item.get("date", "")) for item in entries), default="")
    entries_html = "\n".join(_entry(item) for item in entries)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html.escape(date_text)} · 分发总览</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin:0; background:#eef0f3; color:{INK};
      font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif; }}
    .page {{ width:min(100%,640px); margin:0 auto; padding:32px 16px 60px; }}
    .kicker {{ font:600 11px/1 sans-serif; letter-spacing:.18em; color:{MUTED}; }}
    h1 {{ margin:12px 0 6px; font-size:22px; line-height:1.4; }}
    .date {{ margin:0 0 26px; color:{MUTED}; font-size:13px; }}
    .entry {{ display:flex; align-items:center; gap:12px; padding:16px 18px;
      margin:0 0 12px; background:#fff; border:1px solid #e2e5ea; border-radius:12px;
      text-decoration:none; color:{INK}; }}
    .body {{ flex:1; min-width:0; display:flex; flex-direction:column; gap:4px; }}
    .name {{ font-size:16px; font-weight:600; }}
    .title {{ font-size:13px; line-height:1.5; }}
    .meta {{ font-size:12px; color:{MUTED}; }}
    .go {{ font-size:13px; font-weight:600; color:{ACCENT}; white-space:nowrap; }}
    .note {{ margin:24px 0 0; font-size:12px; line-height:1.9; color:{MUTED}; }}
  </style>
</head>
<body>
  <main class="page">
    <div class="kicker">DAILY DISTRIBUTION</div>
    <h1>待发布</h1>
    <p class="date">{html.escape(date_text)} · 共 {len(entries)} 项</p>
{entries_html}
    <p class="note">成稿页把标题、正文、话题拆成了独立的复制按钮，对应发布后台的各个输入框。
      公众号粘贴正文后记得上传封面；小红书按角标顺序上传图卡；视频笔记直接下载后上传。</p>
  </main>
</body>
</html>
"""


def write_overview(output_root: Path) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "index.html"
    path.write_text(build_overview_page(collect(output_root)), encoding="utf-8")
    return path
