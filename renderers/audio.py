"""视频配音与背景音乐。

视频原本挂的是一条无声音轨（``anullsrc``），干巴巴的。这里补两样东西：
edge-tts 合成的中文旁白，和一段随仓入库的免版税背景音乐。旁白盖在低音量的
BGM 上，混成一条音轨交给 ``encode`` muxing 进 mp4。

设计取舍：

- **配音走 edge-tts**：免费、无需 API Key、纯 pip 包，境外 runner 直连微软即可。
  合成失败（没装包、断网、微软抽风）一律返回 ``None`` 降级——音频是锦上添花，
  绝不能因为它拿不到就让整支视频出不来。
- **BGM 随仓入库**：一首 CC0/公有领域的曲子放在 ``assets/``，避免运行期再去下载。
  路径可用环境变量 ``MARKET_BGM`` 覆盖；文件不在就跳过 BGM，只留旁白（或纯静音）。
- **音量**：BGM 压到很低垫底，别盖过人声；旁白保持原音量。具体混音在
  ``encode`` 里用 ffmpeg 的 ``amix`` 完成，这里只负责把素材备齐。
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.config import PROJECT_ROOT
from core.console import safe_print

# 中文女声，语速略快一点更贴合短视频节奏。
VOICE = "zh-CN-XiaoxiaoNeural"
RATE = "+6%"

# 随仓入库的默认 BGM；可用 MARKET_BGM 覆盖成别的文件。
DEFAULT_BGM = PROJECT_ROOT / "assets" / "bgm.mp3"

# BGM 相对旁白的音量，垫底用，别盖过人声。
# 素材本身已 loudnorm 到 -14 LUFS 的正常音乐响度，这里再压一档当背景垫底：
# 0.20 ≈ -14dB，混在满量程旁白下约低十来分贝，听得见又不抢人声。想更响调大即可。
BGM_VOLUME = 0.20


@dataclass
class AudioSpec:
    """一支视频要配的音：旁白口播稿 + 背景音乐路径 + BGM 音量。

    旁白以**文本**携带而非音频文件：TTS 要联网、可能失败，推迟到真正编码时再合成，
    失败了也只影响这一条音轨，不影响画面。
    """

    narration: str = ""
    bgm: Path | None = None
    bgm_volume: float = BGM_VOLUME


def resolve_bgm() -> Path | None:
    """定位 BGM 文件：优先 ``MARKET_BGM`` 环境变量，否则用仓库内置的；都没有则 None。"""
    override = os.environ.get("MARKET_BGM", "").strip()
    candidate = Path(override) if override else DEFAULT_BGM
    return candidate if candidate.is_file() else None


def synthesize(text: str, out_dir: Path | None = None) -> Path | None:
    """把口播稿合成成一个 mp3，返回路径；不可用时返回 ``None``。

    包没装、网络不通、合成结果为空——任一情况都吞掉返回 None，让上层降级到
    纯 BGM 或静音。绝不抛出去阻断出片。
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        import edge_tts
    except ImportError:
        safe_print("  未安装 edge-tts，跳过配音")
        return None

    # mkstemp 连带返回一个**已打开**的句柄，只取路径会把它漏在那儿——Windows 上
    # 这个悬空句柄会锁住文件，让 edge-tts 随后写入、或结束时删除都报 WinError 32
    # （Linux 不锁，所以 CI 发现不了）。这里显式关掉它，只留文件名给下面用。
    fd, name = tempfile.mkstemp(suffix=".mp3", dir=str(out_dir) if out_dir else None)
    os.close(fd)
    target = Path(name)

    # Windows + Python 3.8 的默认 Proactor 事件循环会在 aiohttp 关闭时抛一条
    # 「Event loop is closed」的 __del__ 噪声：无害，但每次合成都甩一段吓人的
    # traceback。切到 Selector 循环即可，客户端请求照常，日志也干净。仅 Windows
    # 生效，真正跑这条流水线的 Linux runner 不受影响。
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        asyncio.run(edge_tts.Communicate(text, VOICE, rate=RATE).save(str(target)))
    except Exception as exc:  # noqa: BLE001 — 配音失败降级，不阻断出片
        safe_print(f"  配音合成失败，本支视频改为纯背景音乐/静音: {exc}")
        target.unlink(missing_ok=True)
        return None

    if not target.is_file() or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        return None
    return target
