"""T1 成稿包：把渲染产物落盘，并生成一页可直接操作的发布页。

一套页面模板服务所有平台：有富文本就给富文本复制按钮，有纯文本就给文案复制框，
有图片就给图卡网格。新增平台不需要新写页面。
"""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

from channels.base import DeliveryResult
from core.models import ContentBundle
from renderers.base import RenderResult
from renderers.theme import ACCENT, INK, MUTED, PAPER


def _actions(result: RenderResult) -> str:
    buttons: list[str] = []
    if result.body_html:
        buttons.append(
            '<button class="primary" type="button" onclick="copyRich()">'
            "复制正文（富文本）</button>"
        )
    if result.body_text:
        buttons.append(
            '<button class="primary" type="button" onclick="copyPlain()">'
            "复制文案</button>"
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
        f'<figure class="shot"><img src="{html.escape(asset.name, quote=True)}" '
        f'alt="{html.escape(asset.name)}" loading="lazy">'
        f'<figcaption><span>{index}</span>'
        f'<a download="{html.escape(asset.name, quote=True)}" '
        f'href="{html.escape(asset.name, quote=True)}">下载</a></figcaption></figure>'
        for index, asset in enumerate(result.images, start=1)
    )
    names = json.dumps([asset.name for asset in result.images], ensure_ascii=False)
    return (
        '<section class="block"><div class="block-head"><h2>图片素材</h2>'
        '<button class="ghost" type="button" onclick="downloadAll()">'
        "全部下载</button></div>"
        f'<div class="gallery">{cards}</div>'
        f"<script>const ASSETS = {names};</script></section>"
    )


def _text_block(result: RenderResult) -> str:
    if not result.body_text:
        return ""
    return (
        '<section class="block"><div class="block-head"><h2>文案</h2></div>'
        f'<textarea id="plain" rows="16" readonly>{html.escape(result.body_text)}'
        "</textarea></section>"
    )


def _article_block(result: RenderResult) -> str:
    if not result.body_html:
        return ""
    return (
        '<section class="block"><div class="block-head"><h2>正文预览</h2></div>'
        f'<article id="rich">{result.body_html}</article></section>'
    )


def build_publish_page(result: RenderResult) -> str:
    safe_title = html.escape(result.title)
    hint = html.escape(result.hint).replace("\n", "<br>")
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
    .block {{ margin:0 0 22px; }}
    .block-head {{ display:flex; align-items:center; justify-content:space-between;
      margin:0 0 10px; }}
    .block-head h2 {{ margin:0; font-size:13px; font-weight:600; color:{MUTED};
      letter-spacing:.04em; }}
    textarea {{ width:100%; padding:14px; border:1px solid #dde0e6; border-radius:10px;
      background:#fff; font:400 13px/1.75 inherit; color:{INK}; resize:vertical; }}
    .gallery {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
      gap:12px; }}
    .shot {{ margin:0; background:#fff; border:1px solid #e2e5ea; border-radius:10px;
      overflow:hidden; }}
    .shot img {{ display:block; width:100%; height:auto; }}
    .shot figcaption {{ display:flex; align-items:center; justify-content:space-between;
      padding:8px 10px; font-size:12px; color:{MUTED}; }}
    .shot a {{ color:{ACCENT}; text-decoration:none; font-weight:600; }}
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
    {_text_block(result)}
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
      try {{
        if (window.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {{
          await navigator.clipboard.write([new ClipboardItem({{
            "text/html": new Blob([article.innerHTML], {{type:"text/html"}}),
            "text/plain": new Blob([article.innerText], {{type:"text/plain"}})
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
        toast("已复制，可粘贴到编辑器");
      }} catch (error) {{
        toast("复制失败，请手动选择正文");
      }}
    }}
    async function copyPlain() {{
      const area = document.getElementById("plain");
      try {{
        await navigator.clipboard.writeText(area.value);
      }} catch (error) {{
        area.removeAttribute("readonly");
        area.select();
        document.execCommand("copy");
        area.setAttribute("readonly", "readonly");
      }}
      toast("文案已复制");
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


class BundleChannel:
    """把成品写进 ``<root>/<platform>/``，人工打开页面即可完成发布。"""

    name = "bundle"

    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root

    def preflight(self) -> None:
        self.output_root.mkdir(parents=True, exist_ok=True)

    def deliver(
        self, bundle: ContentBundle, result: RenderResult
    ) -> DeliveryResult:
        target = self.output_root / result.platform
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)

        for asset in result.images:
            asset.save(target / asset.name)
        for name, content in result.text_files.items():
            (target / name).write_text(content, encoding="utf-8")
        (target / "index.html").write_text(
            build_publish_page(result), encoding="utf-8"
        )

        parts = [f"{len(result.images)} 图"] if result.images else []
        parts.append(f"{len(result.text_files) + 1} 文件")
        return DeliveryResult(
            channel=self.name,
            ok=True,
            detail=" · ".join(parts),
            location=str(target),
        )
