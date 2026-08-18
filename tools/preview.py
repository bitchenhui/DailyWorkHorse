"""本地预览：用压力测试夹具渲染各平台成稿，不联网、不调用大模型。

调排版时用它代替 ``main.py --dry-run``，秒出结果且不消耗 API 额度。
夹具刻意混入超长项目名、超长与超短摘要、缺失深读字段等边界情况，
排版一旦在某个极端下崩掉，这里就能看出来。

    python -m tools.preview [输出目录]

默认跳过行情视频——渲染整段要十几秒，而调图卡排版时用不上它：

    python -m tools.preview --with-video
"""

from __future__ import annotations

import sys
from pathlib import Path

from channels.bundle import BundleChannel
from channels.overview import write_overview
from core.models import ContentBundle
from renderers import article, carddeck, marketvideo

_LONG_SUMMARY = (
    "一个用于压力测试排版的超长中文摘要，包含 English words 与 1234 数字，"
    "用来确认折行、截断与省略号在混排场景下都能正常工作"
)
_SAMPLES = [
    ("MakazhanAlpamys/super-long-project-name-for-layout-test", "Python", _LONG_SUMMARY),
    ("a/b", "Go", "极短摘要"),
    ("public-apis/public-apis", "Unknown", "汇总免费可用的公共 API 列表，面向开发者的社区资源合集"),
    ("usestrix/strix", "Python", "面向 Web 应用的 AI 自动化渗透测试工具"),
    ("harry0703/MoneyPrinterTurbo", "TypeScript", _LONG_SUMMARY),
    ("cactus-compute/needle", "Rust", "面向手机与物联网设备的超轻量基础模型"),
    ("ToolJet/ToolJet", "JavaScript", "用于搭建企业内部工具与 AI 代理应用的开源低代码平台"),
    ("unslothai/unsloth", "Python", "本地运行与微调大语言模型与扩散模型的桌面界面工具"),
    ("cordiverse/cordis", "TypeScript", ""),  # 摘要缺失，应回落到 description
    ("citrolabs/ego-lite", "Go", "为 AI 代理设计的轻量级浏览器自动化运行环境"),
]


def build_sample_bundle() -> ContentBundle:
    repos = []
    editorial = {}
    for index, (full_name, language, summary) in enumerate(_SAMPLES, start=1):
        repos.append(
            {
                "rank": index,
                "full_name": full_name,
                "url": f"https://github.com/{full_name}",
                "description": f"Fallback description for {full_name}",
                "language": language,
                "stars_total": 1_234_567 // index,
                "stars_today": 2000 - index * 137,
            }
        )
        # rank 2 只给摘要，用来验证深读缺失时详情卡不会塌掉。
        editorial[index] = {
            "summary": summary,
            "what": _LONG_SUMMARY if index == 1 else ("这个项目的定位说明" if index == 3 else ""),
            "why": _LONG_SUMMARY if index == 1 else ("今日上涨的原因说明" if index == 3 else ""),
            "who": _LONG_SUMMARY if index == 1 else ("适合关注的人群说明" if index == 3 else ""),
        }

    return ContentBundle(
        slug="preview-github-trending",
        date_text="2026-08-17",
        title=article.build_title(repos),
        repos=repos,
        editorial=editorial,
        alt_titles=["免费 API 合集稳坐榜首", "备选标题二", "备选标题三"],
        lede="每天扒一遍 GitHub Trending，两分钟看完今天的开源风向。",
        tags=["GitHub", "开源项目", "程序员", "AI"],
    )


def main() -> int:
    args = [arg for arg in sys.argv[1:] if arg != "--with-video"]
    with_video = "--with-video" in sys.argv
    output = Path(args[0] if args else "dist-preview").resolve()

    bundle = build_sample_bundle()
    channel = BundleChannel(output)
    channel.preflight()

    for render in (article.render, carddeck.render):
        result = render(bundle)
        delivered = channel.deliver(bundle, result)
        print(f"  {result.platform_label}: {delivered.detail}")

    if with_video:
        # 行情夹具住在 tests 里：它同样是一份刻意设计的边界数据
        # （末段名次反超），没必要为预览再维护第二份。
        from tests.fixtures import make_market_bundle

        market = make_market_bundle(minutes=60)
        result = marketvideo.render(market)
        delivered = channel.deliver(market, result)
        print(f"  {result.platform_label}: {delivered.detail}")

    write_overview(output)
    print(f"预览已生成: {output / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
