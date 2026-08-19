"""行情日报：布局推演、文案、视频编码。"""

from __future__ import annotations

import unittest
from datetime import datetime
from itertools import islice
from pathlib import Path
from tempfile import TemporaryDirectory

from core.config import CST
from core.models import NothingToPublish
from enrich import narration
from renderers import audio, encode, marketvideo
from sources import market
from tests.fixtures import make_market_bundle, make_series


class LayoutTests(unittest.TestCase):
    def rows(self) -> list[dict]:
        bundle = make_market_bundle()
        return bundle.sectors

    def test_last_frame_is_fully_settled(self) -> None:
        """定格帧要停在各就各位的状态。

        这一帧会被定住一两秒，是观众唯一会认真读的一帧。停在换位半路上时
        两张卡片会叠住，看起来就是「少了一行」。
        """
        frames = list(marketvideo.layout(self.rows()))
        slots = frames[-1].slots

        self.assertEqual(
            sorted(round(slot) for slot in slots), list(range(len(slots)))
        )
        for slot in slots:
            self.assertAlmostEqual(slot, round(slot), places=1)

    def test_settled_rows_never_share_a_slot(self) -> None:
        last = list(marketvideo.layout(self.rows()))[-1]
        gaps = [
            abs(last.slots[a] - last.slots[b])
            for a in range(len(last.slots))
            for b in range(a + 1, len(last.slots))
        ]
        self.assertGreater(min(gaps), marketvideo.CARD_RATIO)

    def test_final_order_matches_closing_values(self) -> None:
        rows = self.rows()
        last = list(marketvideo.layout(rows))[-1]
        by_slot = sorted(range(len(rows)), key=lambda i: last.slots[i])

        self.assertEqual(
            [rows[i]["name"] for i in by_slot],
            [row["name"] for row in sorted(
                rows, key=lambda r: r["net_inflow"], reverse=True
            )],
        )

    def test_cards_leave_a_gap_between_rows(self) -> None:
        for count in (10, 12):
            span, card = marketvideo._row_metrics(count)
            self.assertLess(card, span, f"{count} 行时卡片顶满了行距")

    def test_empty_series_yields_no_frames(self) -> None:
        self.assertEqual([], list(marketvideo.layout([])))


class CopyTests(unittest.TestCase):
    def test_social_title_fits_the_platform_limit(self) -> None:
        bundle = make_market_bundle()
        self.assertLessEqual(
            len(marketvideo.build_social_title(bundle)), marketvideo.TITLE_LIMIT
        )

    def test_long_sector_names_fall_back_to_a_shorter_form(self) -> None:
        """行业名长到两段式装不下时，得退到更短的写法而不是硬截断。"""
        bundle = make_market_bundle()
        bundle.sector_inflow[0]["name"] = "通信网络设备及器件制造"
        bundle.sector_outflow[0]["name"] = "计算机应用软件开发"

        title = marketvideo.build_social_title(bundle)

        self.assertLessEqual(len(title), marketvideo.TITLE_LIMIT)
        self.assertNotIn("计算机应用软件开发", title)

    def test_note_lists_both_ends_and_the_disclaimer(self) -> None:
        note = marketvideo.build_note(make_market_bundle())

        self.assertIn("农林牧渔", note)
        self.assertIn("电子", note)
        self.assertIn("中际旭创", note)
        self.assertIn("不构成投资建议", note)

    def test_render_carries_a_video_and_separate_copy_fields(self) -> None:
        result = marketvideo.render(make_market_bundle())

        self.assertEqual("xhs_video", result.platform)
        self.assertEqual(1, len(result.videos))
        self.assertEqual(
            ["标题", "正文", "话题标签"], [f.label for f in result.copy_fields]
        )
        self.assertEqual("", result.body_html)


class NarrationTests(unittest.TestCase):
    def test_fallback_names_both_ends_and_the_disclaimer(self) -> None:
        script = narration.fallback(make_market_bundle())

        self.assertIn("农林牧渔", script)  # 流入榜首
        self.assertIn("电子", script)  # 流出榜首
        self.assertIn("不构成投资建议", script)

    def test_fallback_stays_short_enough_for_the_clip(self) -> None:
        """整片约 11 秒，配音靠 ``-shortest`` 随画面收口，稿子太长尾巴会被切掉。

        兜底稿没有 LLM 的字数约束、最容易写长，这条钉住上限，防止回归到
        「连免责声明都念不完就被截断」的状态。
        """
        self.assertLessEqual(len(narration.fallback(make_market_bundle())), 50)

    def test_build_script_falls_back_when_the_model_is_unavailable(self) -> None:
        """缺 LLM（只跑 xhs_video 的常态）时静默退到纯数据兜底稿，绝不阻断出片。"""
        bundle = make_market_bundle()

        def _no_model(*_a, **_k):
            raise SystemExit("没有配置 LLM_API_KEY")

        original = narration.llm.complete
        narration.llm.complete = _no_model
        try:
            self.assertEqual(narration.build_script(bundle), narration.fallback(bundle))
        finally:
            narration.llm.complete = original


class AudioTests(unittest.TestCase):
    def test_repo_ships_a_bgm_asset(self) -> None:
        """随仓入库的 BGM 得真的在，否则成片就只有配音、没有背景乐。"""
        self.assertIsNotNone(audio.resolve_bgm())

    def test_synthesize_returns_none_for_empty_text(self) -> None:
        """没有文本就不该去合成——最省事的降级路径，不碰网络也不装 edge-tts。"""
        self.assertIsNone(audio.synthesize(""))

    def test_render_attaches_narration_and_the_bgm(self) -> None:
        """行情视频要带上音频规格：口播稿文本 + 仓库里的 BGM 路径。"""
        def _no_model(*_a, **_k):
            raise SystemExit("没有配置 LLM_API_KEY")

        original = narration.llm.complete
        narration.llm.complete = _no_model
        try:
            asset = marketvideo.render(make_market_bundle()).videos[0]
        finally:
            narration.llm.complete = original

        self.assertIsNotNone(asset.audio)
        self.assertTrue(asset.audio.narration)
        self.assertEqual(asset.audio.bgm, audio.resolve_bgm())


class StructureTests(unittest.TestCase):
    def test_closing_page_is_the_last_thing_yielded(self) -> None:
        """结论页要真的接在片尾。

        少了它，视频跑完个股榜就直接黑掉，没有可当封面缩略图的定格结论。
        末尾若干帧应当全等（定格），且不同于个股段最后一帧。
        """
        bundle = make_market_bundle(minutes=2)
        seq = list(marketvideo.frames(bundle))
        hold = int(1.0 * marketvideo.FPS)

        tail = seq[-hold:]
        self.assertTrue(
            all(frame.tobytes() == tail[0].tobytes() for frame in tail),
            "结论页没有定格成一串相同帧",
        )
        self.assertNotEqual(
            seq[-hold - 1].tobytes(),
            tail[0].tobytes(),
            "结论页与前一段之间没有切换",
        )

    def test_closing_page_shows_the_stock_top3(self) -> None:
        """个股不再单独走赛跑，最终前三收在结论页——改榜首名字，成片必须变。

        个股段被删掉后，个股数据只剩这一处出口；这条断言守住它别再悄悄丢掉。
        """
        bundle = make_market_bundle(minutes=2)
        before = next(iter(marketvideo._closing_frames(bundle, seconds=0.1))).tobytes()

        bundle.stock_inflow[0]["name"] = "关灯吃面科技"
        after = next(iter(marketvideo._closing_frames(bundle, seconds=0.1))).tobytes()

        self.assertNotEqual(before, after, "结论页没有把个股榜首画上去")


class EncodeTests(unittest.TestCase):
    def frames(self):
        # 一帧就是 1080×1920，测编码链路取几帧就够，不必渲染整段。
        return islice(marketvideo.frames(make_market_bundle(minutes=2)), 12)

    def test_gif_fallback_writes_a_playable_file(self) -> None:
        with TemporaryDirectory() as tmp:
            written = encode.write(self.frames(), Path(tmp) / "clip.gif", fps=25)

            self.assertEqual(".gif", written.suffix)
            self.assertGreater(written.stat().st_size, 0)

    def test_mp4_request_degrades_to_gif_without_ffmpeg(self) -> None:
        """没有 ffmpeg 时不能报错，也不能留下一个扩展名骗人的文件。"""
        original = encode.ffmpeg_binary
        encode.ffmpeg_binary = lambda: None
        try:
            with TemporaryDirectory() as tmp:
                target = Path(tmp) / "clip.mp4"
                written = encode.write(self.frames(), target, fps=25)

                self.assertEqual(".gif", written.suffix)
                self.assertFalse(target.exists())
        finally:
            encode.ffmpeg_binary = original

    def test_asset_frames_can_be_iterated_more_than_once(self) -> None:
        """投递可能重跑，所以帧必须以工厂而非生成器携带。

        早先直接携带生成器，第二次保存拿到的是已耗尽的迭代器，写出空文件。
        """
        asset = marketvideo.render(make_market_bundle(minutes=2)).videos[0]

        first = next(iter(asset.frames()))
        second = next(iter(asset.frames()))

        self.assertEqual(first.tobytes(), second.tobytes())


def _today() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d")


class TradingDayTests(unittest.TestCase):
    """非交易日跑，接口给的是上一个交易日的完整曲线，必须识别出来。"""

    def run_with(
        self,
        trading_date: str,
        last_clock: str = market.SESSION_CLOSE,
        after_deadline: bool = False,
    ):
        original_fetch = market.fetch
        original_deadline = market.DATA_DEADLINE
        original_retry = market.LAGGING_RETRY_SECONDS
        # 「此刻」不好摆布，改成挪动截止时刻：压到 00:00 就是永远已过，
        # 推到 23:59 就是永远没到。
        market.DATA_DEADLINE = "00:00" if after_deadline else "23:59"
        # 滞后重取的真实等待在单测里没意义，置零免得真睡；重取仍会走一遍
        # （mock 的 fetch 返回同一份滞后数据），因此该失败的仍会失败。
        market.LAGGING_RETRY_SECONDS = 0
        market.fetch = lambda *a, **k: {
            "trading_date": trading_date,
            "last_clock": last_clock,
            "indexes": [],
            "sectors": [],
            "stock_inflow": [],
            "stock_outflow": [],
        }
        try:
            return market.build_bundle()
        finally:
            market.fetch = original_fetch
            market.DATA_DEADLINE = original_deadline
            market.LAGGING_RETRY_SECONDS = original_retry

    def test_stale_data_is_rejected(self) -> None:
        with self.assertRaises(market.NotATradingDay):
            self.run_with("1999-01-04")

    def test_missing_date_is_rejected(self) -> None:
        with self.assertRaises(market.NotATradingDay):
            self.run_with("")

    def test_a_closed_trading_day_is_accepted(self) -> None:
        self.assertEqual(_today(), self.run_with(_today()).date_text)

    def test_a_half_day_curve_is_rejected(self) -> None:
        """盘中跑拿到的是半天曲线。

        它画出来和全天的一模一样，看不出是残的，所以必须在这里拦下——
        定时任务排在 15:10，只有手动触发才会走到。
        """
        with self.assertRaises(market.SessionNotClosed):
            self.run_with(_today(), "11:30")

    def test_the_lunch_break_does_not_count_as_closed(self) -> None:
        with self.assertRaises(market.SessionNotClosed):
            self.run_with(_today(), "14:59")

    def test_an_empty_curve_is_rejected(self) -> None:
        with self.assertRaises(market.SessionNotClosed):
            self.run_with(_today(), "")

    def test_a_lagging_source_after_the_close_is_a_failure(self) -> None:
        """收盘后曲线还不全，这一天本该出片。

        安静跳过等于漏发一期还没人知道，所以要抛非 ``NothingToPublish``
        的错，让这次运行亮红。
        """
        with self.assertRaises(market.MarketDataLagging):
            self.run_with(_today(), "14:30", after_deadline=True)

        self.assertNotIsInstance(market.MarketDataLagging(""), NothingToPublish)

    def test_the_stale_date_check_runs_first(self) -> None:
        """非交易日拿到的是上一交易日的**完整**曲线，时刻校验会放行。"""
        with self.assertRaises(market.NotATradingDay):
            self.run_with("1999-01-04", market.SESSION_CLOSE)


class SeriesFixtureTests(unittest.TestCase):
    def test_series_is_cumulative(self) -> None:
        """夹具本身也得符合上游语义：曲线是当日累计值，不是每分钟增量。"""
        points = make_series(10e8, minutes=5)
        values = [point["net_inflow"] for point in points]

        self.assertEqual(values, sorted(values))
        self.assertAlmostEqual(10e8, values[-1])


if __name__ == "__main__":
    unittest.main()
