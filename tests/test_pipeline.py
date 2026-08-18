import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pipeline
from renderers.base import CopyField, RenderResult
from sources import market


def _result(platform: str, **kwargs) -> RenderResult:
    return RenderResult(
        platform=platform, platform_label=platform, title="标题", **kwargs
    )


class NotificationBodyTests(unittest.TestCase):
    def test_prefers_the_wechat_rich_text(self) -> None:
        results = [
            _result("xhs", copy_fields=[CopyField("正文", "小红书文案")]),
            _result("wechat_mp", body_html="<p>公众号正文</p>"),
        ]

        self.assertEqual("<p>公众号正文</p>", pipeline.notification_body(results))

    def test_falls_back_to_a_text_field_when_wechat_is_disabled(self) -> None:
        results = [_result("xhs", copy_fields=[CopyField("正文", "第一行\n第二行")])]

        body = pipeline.notification_body(results)

        self.assertIn("第一行<br>第二行", body)

    def test_escapes_text_so_the_notification_cannot_break(self) -> None:
        results = [_result("xhs", copy_fields=[CopyField("正文", "<script>x</script>")])]

        self.assertNotIn("<script>", pipeline.notification_body(results))

    def test_survives_results_without_any_copyable_text(self) -> None:
        self.assertEqual("", pipeline.notification_body([_result("xhs")]))


class NotificationTitleTests(unittest.TestCase):
    def test_title_comes_from_whichever_result_supplied_the_body(self) -> None:
        results = [
            _result("xhs", copy_fields=[CopyField("正文", "小红书文案")]),
            _result("wechat_mp", body_html="<p>正文</p>"),
        ]
        results[1].title = "公众号标题"

        self.assertEqual("公众号标题", pipeline.notification_title(results))

    def test_falls_back_when_nothing_has_text(self) -> None:
        self.assertEqual("标题", pipeline.notification_title([_result("xhs")]))


class FakeChannel:
    def preflight(self) -> None:
        pass

    def deliver(self, bundle, result):
        from channels.base import DeliveryResult

        return DeliveryResult(channel="fake", ok=True, detail="", location="mem")


class FeedIsolationTests(unittest.TestCase):
    """一个信息源挂了不能拖垮其余的。

    行情源打的是第三方行情接口，境外 runner 上未必稳；它失败时当天的
    GitHub 日报照样要发得出去。
    """

    def setUp(self) -> None:
        self.feeds = pipeline.FEEDS
        self.channel = pipeline.resolve_channel
        self.platforms = pipeline.enabled_platforms
        pipeline.resolve_channel = lambda platform: FakeChannel()
        pipeline.enabled_platforms = lambda: ("wechat_mp", "xhs_video")

    def tearDown(self) -> None:
        pipeline.FEEDS = self.feeds
        pipeline.resolve_channel = self.channel
        pipeline.enabled_platforms = self.platforms

    def test_a_broken_feed_does_not_stop_the_others(self) -> None:
        from tests.fixtures import make_bundle

        def explode():
            raise RuntimeError("行情接口不通")

        pipeline.FEEDS = (
            pipeline.Feed("market", explode, {"xhs_video": lambda b: None}),
            pipeline.Feed(
                "github",
                make_bundle,
                {"wechat_mp": lambda b: _result("wechat_mp", body_html="<p>x</p>")},
            ),
        )

        outcome = pipeline.distribute()

        self.assertEqual(["wechat_mp"], [r.platform for r in outcome.results])
        self.assertEqual("2026-08-17", outcome.date_text)
        self.assertEqual([], outcome.idle)
        self.assertEqual(1, len(outcome.failed))

    def test_configuration_errors_still_stop_the_run(self) -> None:
        """缺环境变量得当场炸出来，改了配置才有意义，不该被当成临时故障吞掉。"""

        def missing_env():
            raise SystemExit("缺少环境变量: LLM_API_KEY")

        pipeline.FEEDS = (
            pipeline.Feed("github", missing_env, {"wechat_mp": lambda b: None}),
        )

        with self.assertRaises(SystemExit):
            pipeline.distribute()


class IdleVsBrokenTests(unittest.TestCase):
    """「今天没得发」和「抓取挂了」得走不同的出口。

    行情流水线每逢周末都会无内容可发。若把它记成失败，Actions 上一周两次
    红叉，真出故障时就淹没在噪音里了。
    """

    def setUp(self) -> None:
        self.feeds = pipeline.FEEDS
        self.platforms = pipeline.enabled_platforms
        self.dist = pipeline.DIST_DIR
        pipeline.enabled_platforms = lambda: ("xhs_video",)
        # run() 会落一份运行记录，别让它写进真实的 dist/。
        self.tmp = TemporaryDirectory()
        pipeline.DIST_DIR = Path(self.tmp.name)

    def tearDown(self) -> None:
        pipeline.FEEDS = self.feeds
        pipeline.enabled_platforms = self.platforms
        pipeline.DIST_DIR = self.dist
        self.tmp.cleanup()

    def _market_feed(self, error: Exception) -> None:
        def build():
            raise error

        pipeline.FEEDS = (
            pipeline.Feed("market", build, {"xhs_video": lambda b: None}),
        )

    def test_a_closed_source_finishes_quietly(self) -> None:
        self._market_feed(market.NotATradingDay("今天是周六"))

        outcome = pipeline.distribute()

        self.assertEqual([], outcome.failed)
        self.assertEqual(1, len(outcome.idle))
        self.assertEqual(0, pipeline.run(dry_run=True))

    def test_a_real_failure_still_fails_the_run(self) -> None:
        self._market_feed(RuntimeError("行情接口不通"))

        outcome = pipeline.distribute()

        self.assertEqual([], outcome.idle)
        self.assertEqual(1, len(outcome.failed))
        with self.assertRaises(RuntimeError):
            pipeline.run(dry_run=True)


if __name__ == "__main__":
    unittest.main()
