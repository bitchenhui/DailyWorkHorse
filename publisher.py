"""生成公众号半自动发布素材：在线复制页、HTML、Markdown 与封面图。"""

from __future__ import annotations

import html
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

INK = "#1a1d29"
ACCENT = "#0f6f63"
PAPER = "#f5f6f8"
MUTED = "#8b93a3"


def _font_candidates(bold: bool) -> list[str]:
    windows = os.environ.get("WINDIR", r"C:\Windows")
    if bold:
        return [
            str(Path(windows) / "Fonts" / "msyhbd.ttc"),
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    return [
        str(Path(windows) / "Fonts" / "msyh.ttc"),
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for candidate in _font_candidates(bold):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _center_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: str,
) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    width = box[2] - box[0]
    height = box[3] - box[1]
    draw.text((xy[0] - width / 2, xy[1] - height / 2), text, font=font, fill=fill)


def generate_cover(
    path: Path, date_text: str, top_repo: dict[str, Any] | None
) -> None:
    """生成 900×383 头条封面，核心标题位于中央方形安全区。"""
    image = Image.new("RGB", (900, 383), INK)
    draw = ImageDraw.Draw(image)

    # 两侧图形即使被微信裁成方图也不影响核心信息。
    draw.ellipse((-105, 40, 235, 380), fill="#202538")
    draw.ellipse((705, -120, 1020, 195), fill="#123f3b")
    draw.rounded_rectangle((54, 54, 154, 82), radius=14, fill=ACCENT)
    draw.text((72, 60), "DAILY", font=_font(14, bold=True), fill="#ffffff")

    center_x = 450
    _center_text(draw, (center_x, 132), "开源升温榜", _font(54, bold=True), "#ffffff")
    _center_text(
        draw,
        (center_x, 190),
        "GITHUB DAILY RADAR",
        _font(17, bold=True),
        "#93a0b8",
    )
    _center_text(draw, (center_x, 228), date_text, _font(18), "#d6dae4")

    repo_name = (top_repo or {}).get("full_name") or "今日开源趋势"
    delta = (top_repo or {}).get("stars_today")
    signal = f"TOP 1  {repo_name}"
    if delta:
        signal += f"  +{delta}★"
    if len(signal) > 44:
        signal = signal[:43] + "…"
    _center_text(draw, (center_x, 304), signal, _font(18, bold=True), "#cde5e1")

    image.save(path, format="PNG", optimize=True)


def build_markdown(
    title: str,
    date_text: str,
    repos: list[dict[str, Any]],
    editorial: dict[int, dict[str, str]],
) -> str:
    lines = [f"# {title}", "", f"> {date_text} · 按今日新增 Stars 降序", ""]
    for repo in repos:
        rank = repo["rank"]
        item = editorial.get(rank, {})
        summary = item.get("summary") or repo.get("description") or "暂无简介"
        lines.extend(
            [
                f"## {rank:02d}. [{repo['full_name']}]({repo['url']})",
                (
                    f"**+{repo['stars_today']}★ 今日** · {repo['language']} · "
                    f"累计 {repo['stars_total']:,}★"
                ),
                "",
                summary,
                "",
            ]
        )
        if rank <= 3:
            for label, key in (
                ("是什么", "what"),
                ("上涨原因", "why"),
                ("适合关注", "who"),
            ):
                value = item.get(key)
                if value:
                    lines.append(f"- **{label}**：{value}")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def _document(title: str, body: str) -> str:
    safe_title = html.escape(title)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{safe_title}</title>
</head>
<body style="margin:0;background:{PAPER};">{body}</body>
</html>
"""


def build_copy_page(title: str, article_html: str) -> str:
    safe_title = html.escape(title)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{safe_title} · 公众号成稿</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin:0; background:#eef0f3; color:{INK};
      font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif; }}
    .toolbar {{ position:sticky; top:0; z-index:10; display:flex; gap:10px;
      align-items:center; justify-content:space-between; padding:12px 18px;
      background:rgba(255,255,255,.96); border-bottom:1px solid #dde0e6; }}
    .toolbar strong {{ font-size:14px; }}
    .actions {{ display:flex; gap:8px; flex-wrap:wrap; }}
    button,.button {{ border:0; border-radius:7px; padding:9px 13px;
      font:600 13px/1 sans-serif; cursor:pointer; text-decoration:none; }}
    .primary {{ color:#fff; background:{ACCENT}; }}
    .secondary {{ color:{INK}; background:#eceef2; }}
    .page {{ width:min(100%,700px); margin:22px auto 50px; padding:0 12px; }}
    .hint {{ margin:0 0 12px; color:{MUTED}; font-size:12px; line-height:1.7; }}
    #article {{ box-shadow:0 10px 30px rgba(26,29,41,.08); }}
    #toast {{ position:fixed; left:50%; bottom:28px; transform:translateX(-50%);
      padding:10px 16px; border-radius:20px; background:{INK}; color:#fff;
      font-size:13px; opacity:0; pointer-events:none; transition:opacity .2s; }}
    #toast.show {{ opacity:1; }}
    @media (max-width:620px) {{
      .toolbar {{ align-items:flex-start; }}
      .toolbar strong {{ display:none; }}
      .actions {{ width:100%; }}
      button,.button {{ flex:1; text-align:center; white-space:nowrap; }}
      .page {{ margin-top:14px; }}
    }}
  </style>
</head>
<body>
  <header class="toolbar">
    <strong>公众号成稿预览</strong>
    <nav class="actions" aria-label="发布操作">
      <button class="primary" type="button" onclick="copyArticle()">复制公众号正文</button>
      <a class="button secondary" href="cover.png" download="cover.png">下载封面</a>
      <a class="button secondary" href="https://mp.weixin.qq.com/" target="_blank" rel="noopener">打开公众号后台</a>
    </nav>
  </header>
  <main class="page">
    <p class="hint">复制后粘贴到公众号编辑器；再上传封面、预览并群发。</p>
    <article id="article">{article_html}</article>
  </main>
  <div id="toast" role="status" aria-live="polite">已复制，可粘贴到公众号编辑器</div>
  <script>
    async function copyArticle() {{
      const article = document.getElementById("article");
      const html = article.innerHTML;
      const plain = article.innerText;
      try {{
        if (window.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {{
          const item = new ClipboardItem({{
            "text/html": new Blob([html], {{type:"text/html"}}),
            "text/plain": new Blob([plain], {{type:"text/plain"}})
          }});
          await navigator.clipboard.write([item]);
        }} else {{
          const range = document.createRange();
          range.selectNodeContents(article);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
          document.execCommand("copy");
          selection.removeAllRanges();
        }}
        const toast = document.getElementById("toast");
        toast.classList.add("show");
        setTimeout(() => toast.classList.remove("show"), 2200);
      }} catch (error) {{
        alert("自动复制失败，请手动选择正文区域复制。");
      }}
    }}
  </script>
</body>
</html>
"""


def write_publish_bundle(
    output_dir: Path,
    title: str,
    date_text: str,
    article_html: str,
    repos: list[dict[str, Any]],
    editorial: dict[int, dict[str, str]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "index.html").write_text(
        build_copy_page(title, article_html), encoding="utf-8"
    )
    (output_dir / "article.html").write_text(
        _document(title, article_html), encoding="utf-8"
    )
    (output_dir / "article.md").write_text(
        build_markdown(title, date_text, repos, editorial), encoding="utf-8"
    )
    generate_cover(
        output_dir / "cover.png", date_text, repos[0] if repos else None
    )
