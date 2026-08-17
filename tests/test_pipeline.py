import unittest

import pipeline
from renderers.base import CopyField, RenderResult


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


if __name__ == "__main__":
    unittest.main()
