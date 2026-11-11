"""运行记录与据此拼出的 Bark 推送载荷。"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from channels import report

DRAFT = "https://example.github.io/DailyWorkHorse/"
RUN = "https://github.com/me/DailyWorkHorse/actions/runs/1"


class RecordTests(unittest.TestCase):
    def test_record_survives_a_round_trip(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            report.write_record(
                root, "2026-08-18", [{"platform": "xhs_video", "label": "小红书视频"}], [], []
            )

            record = report.read_record(root)

            self.assertIsNotNone(record)
            self.assertEqual("2026-08-18", record["date"])
            self.assertEqual("xhs_video", record["platforms"][0]["platform"])

    def test_a_missing_record_reads_as_none(self) -> None:
        with TemporaryDirectory() as tmp:
            self.assertIsNone(report.read_record(Path(tmp)))

    def test_a_broken_record_reads_as_none(self) -> None:
        """半截 JSON 不该让推送发不出去——那正是最需要被通知的时候。"""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / report.RECORD).write_text("{不是 json", encoding="utf-8")

            self.assertIsNone(report.read_record(root))


class SubjectTests(unittest.TestCase):
    def test_a_successful_run_names_the_platforms(self) -> None:
        subject = report.subject_for(
            {
                "date": "2026-08-18",
                "platforms": [{"label": "微信公众号"}, {"label": "小红书"}],
                "idle": [],
                "failed": [],
            }
        )

        self.assertIn("微信公众号、小红书", subject)
        self.assertIn("2026-08-18", subject)

    def test_an_idle_run_does_not_read_as_a_failure(self) -> None:
        """周末的行情流水线走的就是这一支，标题里不能出现「失败」。"""
        subject = report.subject_for(
            {"date": "2026-08-18", "platforms": [], "idle": ["market（今天是周六）"], "failed": []}
        )

        self.assertIn("今天没有可发布的内容", subject)
        self.assertNotIn("失败", subject)

    def test_a_partial_run_counts_both_sides(self) -> None:
        subject = report.subject_for(
            {"date": "2026-08-18", "platforms": [{"label": "小红书"}], "failed": ["github（超时）"]}
        )

        self.assertIn("1 项就绪", subject)
        self.assertIn("1 项失败", subject)

    def test_a_missing_record_reads_as_a_failure(self) -> None:
        self.assertIn("生成失败", report.subject_for(None))


class PushPayloadTests(unittest.TestCase):
    """Bark 载荷的适配规则：标题给结论、正文给清单、点击给去处、级别给打扰度。"""

    def build(self, platforms, idle=(), failed=(), draft=DRAFT) -> dict:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            report.write_record(
                root, "2026-08-18", list(platforms), list(idle), list(failed)
            )
            return report.build_push(root, draft, RUN)

    def test_a_successful_push_lists_each_title_and_links_the_overview(self) -> None:
        payload = self.build(
            [{"platform": "xhs_topic", "label": "小红书·主题", "title": "算法工程师，哪些活真能交给 Agent？"}]
        )

        self.assertIn("小红书·主题 已就绪", payload["title"])
        self.assertIn("小红书·主题：算法工程师，哪些活真能交给 Agent？", payload["body"])
        self.assertEqual(DRAFT, payload["url"])
        self.assertEqual("active", payload["level"])
        self.assertEqual("DailyWorkHorse", payload["group"])

    def test_idle_and_failed_are_reported_separately(self) -> None:
        """两者的下一步动作完全不同：一个什么都不用做，一个得去重跑。"""
        payload = self.build([], idle=["market（今天是周六）"], failed=["github（超时）"])

        self.assertIn("没有内容｜market（今天是周六）", payload["body"])
        self.assertIn("失败｜github（超时）", payload["body"])
        self.assertEqual(RUN, payload["url"])
        self.assertEqual("timeSensitive", payload["level"])

    def test_an_idle_run_never_lights_up_the_screen(self) -> None:
        payload = self.build([], idle=["market（今天是周六）"])

        self.assertEqual("passive", payload["level"])
        self.assertNotIn("失败", payload["title"])

    def test_a_missing_record_still_produces_a_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            payload = report.build_push(Path(tmp), DRAFT, RUN)

            self.assertIn("生成失败", payload["title"])
            self.assertIn("查看日志", payload["body"])
            self.assertEqual(RUN, payload["url"])
            self.assertEqual("timeSensitive", payload["level"])

    def test_without_a_draft_url_the_overview_falls_back_to_the_run(self) -> None:
        payload = self.build([{"platform": "xhs", "label": "小红书", "title": "t"}], draft="")

        self.assertEqual(RUN, payload["url"])


if __name__ == "__main__":
    unittest.main()
