"""分发总览页：手机上打开一页，逐个平台完成当日发布。"""

from __future__ import annotations

import html
from pathlib import Path

from core.models import ContentBundle
from renderers.base import RenderResult
from renderers.theme import ACCENT, INK, MUTED


def _entry(result: RenderResult) -> str:
    counts: list[str] = []
    if result.images:
        counts.append(f"{len(result.images)} 张图")
    if result.body_html:
        counts.append("富文本正文")
    counts.extend(item.label for item in result.copy_fields if item.text)
    return f"""    <a class="entry" href="{html.escape(result.platform, quote=True)}/index.html">
      <span class="name">{html.escape(result.platform_label)}</span>
      <span class="meta">{html.escape(" · ".join(counts))}</span>
      <span class="go">去发布 →</span>
    </a>"""


def build_overview_page(
    bundle: ContentBundle, results: list[RenderResult]
) -> str:
    entries = "\n".join(_entry(result) for result in results)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{html.escape(bundle.title)} · 分发总览</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin:0; background:#eef0f3; color:{INK};
      font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif; }}
    .page {{ width:min(100%,640px); margin:0 auto; padding:32px 16px 60px; }}
    .kicker {{ font:600 11px/1 sans-serif; letter-spacing:.18em; color:{MUTED}; }}
    h1 {{ margin:12px 0 6px; font-size:22px; line-height:1.4; }}
    .date {{ margin:0 0 26px; color:{MUTED}; font-size:13px; }}
    .entry {{ display:flex; align-items:center; gap:12px; padding:18px 18px;
      margin:0 0 12px; background:#fff; border:1px solid #e2e5ea; border-radius:12px;
      text-decoration:none; color:{INK}; }}
    .name {{ font-size:16px; font-weight:600; }}
    .meta {{ flex:1; font-size:12px; color:{MUTED}; }}
    .go {{ font-size:13px; font-weight:600; color:{ACCENT}; white-space:nowrap; }}
    .note {{ margin:24px 0 0; font-size:12px; line-height:1.9; color:{MUTED}; }}
  </style>
</head>
<body>
  <main class="page">
    <div class="kicker">DAILY DISTRIBUTION</div>
    <h1>{html.escape(bundle.title)}</h1>
    <p class="date">{html.escape(bundle.date_text)} · 共 {len(results)} 个平台待发布</p>
{entries}
    <p class="note">成稿页把标题、正文、话题拆成了独立的复制按钮，对应发布后台的各个输入框。
      公众号粘贴正文后记得上传封面；小红书按角标顺序上传图卡。</p>
  </main>
</body>
</html>
"""


def write_overview(
    output_root: Path, bundle: ContentBundle, results: list[RenderResult]
) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "index.html"
    path.write_text(build_overview_page(bundle, results), encoding="utf-8")
    return path
