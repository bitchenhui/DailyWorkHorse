"""收尾邮件：本次运行的记录与据此拼出的正文。"""

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
        """半截 JSON 不该让邮件发不出去——那正是最需要收到信的时候。"""
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
        """周末的行情流水线走的就是这一支，主题里不能出现「失败」。"""
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


class EmailTests(unittest.TestCase):
    def build(self, platforms, idle=(), failed=()) -> tuple[str, str]:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            report.write_record(
                root, "2026-08-18", list(platforms), list(idle), list(failed)
            )
            return report.build_email(root, DRAFT, RUN)

    def test_each_platform_links_to_its_publish_page(self) -> None:
        _, body = self.build(
            [{"platform": "xhs_video", "label": "小红书视频", "title": "今日资金流向"}]
        )

        self.assertIn(f"{DRAFT}xhs_video/index.html", body)
        self.assertIn("小红书视频", body)
        self.assertIn("今日资金流向", body)
        self.assertIn(RUN, body)

    def test_idle_and_failed_are_reported_separately(self) -> None:
        """两者的下一步动作完全不同：一个什么都不用做，一个得去重跑。"""
        _, body = self.build([], idle=["market（今天是周六）"], failed=["github（超时）"])

        self.assertIn("今天没有内容", body)
        self.assertIn("market（今天是周六）", body)
        self.assertIn("失败", body)
        self.assertIn("github（超时）", body)

    def test_titles_are_escaped(self) -> None:
        _, body = self.build(
            [{"platform": "xhs", "label": "小红书", "title": "<script>x</script>"}]
        )

        self.assertNotIn("<script>", body)

    def test_a_missing_record_still_produces_a_body(self) -> None:
        with TemporaryDirectory() as tmp:
            subject, body = report.build_email(Path(tmp), DRAFT, RUN)

            self.assertIn("生成失败", subject)
            self.assertIn(RUN, body)


if __name__ == "__main__":
    unittest.main()
