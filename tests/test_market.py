"""行情日报：布局推演、文案、视频编码。"""

from __future__ import annotations

import unittest
from datetime import datetime
from itertools import islice
from pathlib import Path
from tempfile import TemporaryDirectory

from core.config import CST
from renderers import encode, marketvideo
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


class TradingDayTests(unittest.TestCase):
    """非交易日跑，接口给的是上一个交易日的完整曲线，必须识别出来。"""

    def run_with(self, trading_date: str):
        original = market.fetch
        market.fetch = lambda *a, **k: {
            "trading_date": trading_date,
            "indexes": [],
            "sector_inflow": [],
            "sector_outflow": [],
            "stock_inflow": [],
            "stock_outflow": [],
        }
        try:
            return market.build_bundle()
        finally:
            market.fetch = original

    def test_stale_data_is_rejected(self) -> None:
        with self.assertRaises(market.NotATradingDay):
            self.run_with("1999-01-04")

    def test_missing_date_is_rejected(self) -> None:
        with self.assertRaises(market.NotATradingDay):
            self.run_with("")

    def test_today_is_accepted(self) -> None:
        today = datetime.now(CST).strftime("%Y-%m-%d")
        self.assertEqual(today, self.run_with(today).date_text)


class SeriesFixtureTests(unittest.TestCase):
    def test_series_is_cumulative(self) -> None:
        """夹具本身也得符合上游语义：曲线是当日累计值，不是每分钟增量。"""
        points = make_series(10e8, minutes=5)
        values = [point["net_inflow"] for point in points]

        self.assertEqual(values, sorted(values))
        self.assertAlmostEqual(10e8, values[-1])


if __name__ == "__main__":
    unittest.main()
