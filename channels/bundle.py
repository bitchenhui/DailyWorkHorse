"""T1 成稿包：把渲染产物落盘，并生成一页可直接操作的发布页。

一套页面模板服务所有平台：有富文本就给富文本复制按钮，有纯文本就给文案复制框，
有图片就给图卡网格。新增平台不需要新写页面。
"""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path
from typing import Sequence

from channels.base import DeliveryResult
from core.models import Bundle
from renderers.base import RenderResult
from renderers.theme import ACCENT, INK, MUTED, PAPER


def _actions(result: RenderResult) -> str:
    buttons: list[str] = []
    if result.body_html:
        buttons.append(
            '<button class="primary" type="button" onclick="copyRich()">'
            "复制正文（富文本）</button>"
        )
    if result.target_url:
        buttons.append(
            f'<a class="button secondary" href="{html.escape(result.target_url, quote=True)}"'
            f' target="_blank" rel="noopener">{html.escape(result.target_label)}</a>'
        )
    return "".join(buttons)


def _gallery(result: RenderResult) -> str:
    if not result.images:
        return ""
    cards = "".join(
        f'<figure class="shot"><span class="seq">{index}</span>'
        f'<img src="{html.escape(asset.name, quote=True)}" '
        f'alt="第 {index} 张图卡" loading="lazy">'
        f'<figcaption><a download="{html.escape(asset.name, quote=True)}" '
        f'href="{html.escape(asset.name, quote=True)}">下载</a></figcaption></figure>'
        for index, asset in enumerate(result.images, start=1)
    )
    names = json.dumps([asset.name for asset in result.images], ensure_ascii=False)
    return (
        '<section class="block"><div class="block-head"><h2>图片素材</h2>'
        '<button class="ghost" type="button" onclick="downloadAll()">'
        "全部下载</button></div>"
        '<p class="field-hint">按角标顺序上传；手机端长按图片即可保存。</p>'
        f'<div class="gallery">{cards}</div>'
        f"<script>const ASSETS = {names};</script></section>"
    )


def _video_block(names: Sequence[str]) -> str:
    """视频区块。降级成 GIF 时 ``<video>`` 放不了，得换成 ``<img>``。"""
    if not names:
        return ""

    players: list[str] = []
    for name in names:
        safe = html.escape(name, quote=True)
        if name.lower().endswith(".gif"):
            players.append(f'<img class="clip" src="{safe}" alt="{html.escape(name)}">')
        else:
            players.append(
                f'<video class="clip" src="{safe}" controls playsinline '
                'preload="metadata"></video>'
            )
        players.append(
            f'<p class="field-hint"><a download="{safe}" href="{safe}">下载 {html.escape(name)}</a>'
            "　·　手机端点开后长按即可保存到相册</p>"
        )

    return (
        '<section class="block"><div class="block-head"><h2>视频</h2></div>'
        + "".join(players)
        + "</section>"
    )


def _copy_blocks(result: RenderResult) -> str:
    blocks: list[str] = []
    for index, item in enumerate(result.copy_fields):
        if not item.text:
            continue
        field_id = f"field{index}"
        note = (
            f'<p class="field-hint">{html.escape(item.hint)}</p>' if item.hint else ""
        )
        blocks.append(
            '<section class="block"><div class="block-head">'
            f"<h2>{html.escape(item.label)}</h2>"
            f'<button class="ghost" type="button" '
            f"onclick=\"copyField('{field_id}')\">复制</button></div>"
            f"{note}"
            f'<textarea id="{field_id}" rows="{item.rows}" readonly>'
            f"{html.escape(item.text)}</textarea></section>"
        )
    return "".join(blocks)


def _article_block(result: RenderResult) -> str:
    if not result.body_html:
        return ""
    return (
        '<section class="block"><div class="block-head"><h2>正文预览</h2></div>'
        f'<article id="rich">{result.body_html}</article></section>'
    )


def build_publish_page(
    result: RenderResult, videos: Sequence[str] | None = None
) -> str:
    """``videos`` 传实际落盘的文件名：编码降级会把 .mp4 变成 .gif，
    页面必须引用真实存在的那个文件。"""
    safe_title = html.escape(result.title)
    hint = html.escape(result.hint).replace("\n", "<br>")
    video_names = list(videos) if videos is not None else [
        asset.name for asset in result.videos
    ]
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{safe_title} · {html.escape(result.platform_label)}成稿</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin:0; background:#eef0f3; color:{INK};
      font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif; }}
    .toolbar {{ position:sticky; top:0; z-index:10; padding:12px 18px;
      background:rgba(255,255,255,.96); border-bottom:1px solid #dde0e6; }}
    .toolbar .row {{ display:flex; gap:10px; align-items:center;
      justify-content:space-between; flex-wrap:wrap; }}
    .brand {{ font-size:14px; font-weight:600; }}
    .brand a {{ color:{MUTED}; text-decoration:none; font-weight:500; }}
    .actions {{ display:flex; gap:8px; flex-wrap:wrap; }}
    button,.button {{ border:0; border-radius:7px; padding:9px 13px;
      font:600 13px/1 sans-serif; cursor:pointer; text-decoration:none; }}
    .primary {{ color:#fff; background:{ACCENT}; }}
    .secondary {{ color:{INK}; background:#eceef2; }}
    .ghost {{ color:{ACCENT}; background:transparent; padding:6px 8px; }}
    .page {{ width:min(100%,700px); margin:22px auto 60px; padding:0 12px; }}
    .hint {{ margin:0 0 16px; color:{MUTED}; font-size:12px; line-height:1.8; }}
    .field-hint {{ margin:-2px 0 8px; color:{MUTED}; font-size:12px; line-height:1.6; }}
    .block {{ margin:0 0 22px; }}
    .block-head {{ display:flex; align-items:center; justify-content:space-between;
      margin:0 0 10px; }}
    .block-head h2 {{ margin:0; font-size:13px; font-weight:600; color:{MUTED};
      letter-spacing:.04em; }}
    textarea {{ width:100%; padding:14px; border:1px solid #dde0e6; border-radius:10px;
      background:#fff; font:400 13px/1.75 inherit; color:{INK}; resize:vertical; }}
    .gallery {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(160px,1fr));
      gap:12px; }}
    .shot {{ position:relative; margin:0; background:#fff; border:1px solid #e2e5ea;
      border-radius:10px; overflow:hidden; }}
    .shot img {{ display:block; width:100%; height:auto; }}
    .seq {{ position:absolute; top:8px; left:8px; min-width:22px; height:22px;
      border-radius:11px; background:{INK}; color:#fff; font:600 12px/22px sans-serif;
      text-align:center; }}
    .shot figcaption {{ display:flex; justify-content:flex-end;
      padding:8px 10px; font-size:12px; color:{MUTED}; }}
    .shot a {{ color:{ACCENT}; text-decoration:none; font-weight:600; }}
    .clip {{ display:block; width:100%; max-height:74vh; border-radius:10px;
      background:#000; }}
    .field-hint a {{ color:{ACCENT}; text-decoration:none; font-weight:600; }}
    #rich {{ background:{PAPER}; border-radius:10px;
      box-shadow:0 10px 30px rgba(26,29,41,.08); }}
    #toast {{ position:fixed; left:50%; bottom:28px; transform:translateX(-50%);
      padding:10px 16px; border-radius:20px; background:{INK}; color:#fff;
      font-size:13px; opacity:0; pointer-events:none; transition:opacity .2s; }}
    #toast.show {{ opacity:1; }}
    @media (max-width:620px) {{
      .actions {{ width:100%; }}
      button,.button {{ flex:1; text-align:center; white-space:nowrap; }}
      .page {{ margin-top:14px; }}
    }}
  </style>
</head>
<body>
  <header class="toolbar">
    <div class="row">
      <div class="brand">{html.escape(result.platform_label)}成稿 ·
        <a href="../index.html">返回总览</a></div>
      <nav class="actions" aria-label="发布操作">{_actions(result)}</nav>
    </div>
  </header>
  <main class="page">
    <p class="hint">{hint}</p>
    {_video_block(video_names)}
    {_copy_blocks(result)}
    {_gallery(result)}
    {_article_block(result)}
  </main>
  <div id="toast" role="status" aria-live="polite">已复制</div>
  <script>
    function toast(message) {{
      const el = document.getElementById("toast");
      el.textContent = message;
      el.classList.add("show");
      setTimeout(() => el.classList.remove("show"), 2200);
    }}
    async function copyRich() {{
      const article = document.getElementById("rich");
      const wrapped = `<!DOCTYPE html><html><body>${{article.innerHTML}}</body></html>`;
      try {{
        if (window.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {{
          await navigator.clipboard.write([new ClipboardItem({{
            "text/html": new Blob([wrapped], {{type:"text/html;charset=utf-8"}}),
            "text/plain": new Blob([article.innerText], {{type:"text/plain;charset=utf-8"}})
          }})]);
        }} else {{
          const range = document.createRange();
          range.selectNodeContents(article);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          document.execCommand("copy");
          selection.removeAllRanges();
        }}
        toast("已复制，可粘贴到公众号编辑器");
      }} catch (error) {{
        toast("复制失败，请手动选择正文");
      }}
    }}
    async function copyField(id) {{
      const area = document.getElementById(id);
      try {{
        await navigator.clipboard.writeText(area.value);
      }} catch (error) {{
        area.removeAttribute("readonly");
        area.select();
        document.execCommand("copy");
        area.setAttribute("readonly", "readonly");
      }}
      toast("已复制");
    }}
    function downloadAll() {{
      if (typeof ASSETS === "undefined") return;
      ASSETS.forEach((name, index) => setTimeout(() => {{
        const link = document.createElement("a");
        link.href = name;
        link.download = name;
        document.body.appendChild(link);
        link.click();
        link.remove();
      }}, index * 350));
      toast("开始逐张下载，手机端也可长按图片保存");
    }}
  </script>
</body>
</html>
"""


def _counts(result: RenderResult) -> list[str]:
    """成品里有些什么，给总览页一眼看的摘要。"""
    counts: list[str] = []
    if result.videos:
        counts.append(f"{len(result.videos)} 段视频")
    if result.images:
        counts.append(f"{len(result.images)} 张图")
    if result.body_html:
        counts.append("富文本正文")
    counts.extend(item.label for item in result.copy_fields if item.text)
    return counts


def write_meta(target: Path, bundle: Bundle, result: RenderResult) -> None:
    """在平台目录里留一份说明，供总览页扫描。

    总览页不能只反映「本次运行」：两个信息源跑在各自的定时任务里，
    上午那趟的成品在下午这趟的 runner 上根本不存在。让每个平台目录自带
    说明，总览页就退化成「扫一遍磁盘」，与谁在什么时候跑过无关。
    """
    target.mkdir(parents=True, exist_ok=True)
    (target / "meta.json").write_text(
        json.dumps(
            {
                "platform": result.platform,
                "label": result.platform_label,
                "title": result.title,
                "date": bundle.date_text,
                "counts": _counts(result),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


class BundleChannel:
    """把成品写进 ``<root>/<platform>/``，人工打开页面即可完成发布。"""

    name = "bundle"

    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root

    def preflight(self) -> None:
        self.output_root.mkdir(parents=True, exist_ok=True)

    def deliver(self, bundle: Bundle, result: RenderResult) -> DeliveryResult:
        target = self.output_root / result.platform
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)

        for asset in result.images:
            asset.save(target / asset.name)
        # 视频先落盘再建页：编码可能降级，真实文件名要等写完才知道。
        videos = [asset.save(target / asset.name).name for asset in result.videos]
        for name, content in result.text_files.items():
            (target / name).write_text(content, encoding="utf-8")
        (target / "index.html").write_text(
            build_publish_page(result, videos), encoding="utf-8"
        )
        write_meta(target, bundle, result)

        parts = [f"{len(result.images)} 图"] if result.images else []
        if videos:
            parts.append(" ".join(videos))
        parts.append(f"{len(result.text_files) + 1} 文件")
        return DeliveryResult(
            channel=self.name,
            ok=True,
            detail=" · ".join(parts),
            location=str(target),
        )
