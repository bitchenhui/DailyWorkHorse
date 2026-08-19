"""行情视频的配音口播稿。

视频原来是无声的，太干；这里生成一段供 TTS 朗读的旁白。约十来秒、四十来字，
配着板块赛跑念出来，把「钱从哪流到哪」说顺口。

一条不可动摇的底线：**数字全是事实，LLM 只许改写话术、不许动数据**。这与
``sources/market.py`` 里「标题直接从数据拼、不走 LLM」是同一个原则——行情稿没有
可编造的余地。所以这里把当日事实喂给模型、要求逐字照抄金额，再回来做一遍校验；
模型不可用（例如只跑 xhs_video 时按 README 本就不配 LLM_API_KEY）或失败，一律
退回纯数据拼的兜底稿，绝不因为配音而让出片中断。
"""

from __future__ import annotations

from core import llm
from core.console import safe_print
from core.models import MarketBundle

# 口播稿长度：约 10 秒 / 40–50 字，匹配整片时长。太长 TTS 会拖过画面。
LENGTH_HINT = "45"

SYSTEM_PROMPT = (
    "你为一支 A 股资金流向的竖屏短视频写配音口播稿，供语音合成朗读。\n"
    "语气：像财经主播口播，短句、口语、干净利落，不浮夸不喊口号。\n"
    "要求：\n"
    f"1. 全文 {LENGTH_HINT} 字左右，一到两句话，念出来约 10 秒；\n"
    "2. 必须说清今天资金主线：哪个行业最吸金、哪个最失血，带上金额；\n"
    "3. 数字一律照抄我给你的，不得改动、不得杜撰任何数据；\n"
    "4. 结尾加一句极短提示，如「仅供参考，不构成投资建议」；\n"
    "5. 只输出口播稿正文本身，不要引号、不要标题、不要解释。"
)


def _yi(value: float) -> str:
    """元 → 亿元，与视频画面口径一致。"""
    return f"{value / 1e8:.1f}亿"


def _facts(bundle: MarketBundle) -> str:
    top_in = bundle.sector_inflow[0] if bundle.sector_inflow else None
    top_out = bundle.sector_outflow[0] if bundle.sector_outflow else None
    lines = [f"日期：{bundle.date_text}"]
    if bundle.indexes:
        lines.append(
            "大盘："
            + "、".join(
                f"{index['name']}{index['change_pct']:+.2f}%"
                for index in bundle.indexes
            )
        )
    if top_in:
        lines.append(f"最吸金行业：{top_in['name']}，主力净流入 {_yi(top_in['net_inflow'])}")
    if top_out:
        lines.append(
            f"最失血行业：{top_out['name']}，主力净流出 {_yi(abs(top_out['net_inflow']))}"
        )
    if bundle.stock_inflow:
        top = bundle.stock_inflow[0]
        lines.append(f"抢筹最多个股：{top['name']}，净流入 {_yi(top['net_inflow'])}")
    return "\n".join(lines)


def fallback(bundle: MarketBundle) -> str:
    """LLM 不可用时的纯数据兜底稿，只由事实拼成。

    刻意压到 45 字上下（≈10 秒）：整片约 11 秒，配音靠 ``-shortest`` 随画面收口，
    稿子太长尾巴会被切掉、连免责声明都念不完。日期画面上已有，这里不再重复念。
    """
    top_in = bundle.sector_inflow[0] if bundle.sector_inflow else None
    top_out = bundle.sector_outflow[0] if bundle.sector_outflow else None

    if top_in and top_out:
        head = (
            f"今日{top_in['name']}最吸金，净流入{_yi(top_in['net_inflow'])}；"
            f"{top_out['name']}失血最多，净流出{_yi(abs(top_out['net_inflow']))}。"
        )
    elif top_in:
        head = f"今日{top_in['name']}最吸金，净流入{_yi(top_in['net_inflow'])}。"
    else:
        head = "今日A股主力资金流向复盘。"
    return head + "仅供参考，不构成投资建议。"


def build_script(bundle: MarketBundle) -> str:
    """生成配音口播稿；任何异常都退回纯数据兜底稿，绝不让配音阻断出片。"""
    default = fallback(bundle)
    try:
        text = llm.complete(SYSTEM_PROMPT, _facts(bundle))
    except SystemExit:
        # 缺 LLM_API_KEY 等配置：只跑视频时本就不配大模型，静默退兜底。
        safe_print("  未配置大模型，配音使用纯数据稿")
        return default
    except Exception as exc:  # noqa: BLE001 — 配音失败不该阻断出片
        safe_print(f"  口播稿生成失败，使用纯数据稿: {exc}")
        return default

    script = " ".join(llm.strip_code_fence(text).split()).strip("「」\"'")
    return script or default
