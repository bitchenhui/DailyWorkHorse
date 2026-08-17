import unittest

from enrich import social
from enrich.editorial import parse_editorial
from tests.fixtures import make_repos


class EditorialTests(unittest.TestCase):
    def test_parse_editorial_requires_summary_for_all_repos(self) -> None:
        raw = """[
          {"rank": 1, "summary": "一句话一", "what": "是什么", "why": "为什么", "who": "适合谁"},
          {"rank": 2, "summary": "一句话二", "what": "是什么", "why": "为什么", "who": "适合谁"},
          {"rank": 3, "summary": "一句话三", "what": "是什么", "why": "为什么", "who": "适合谁"},
          {"rank": 4, "summary": "一句话四"}
        ]"""

        result = parse_editorial(raw, expected_ranks={1, 2, 3, 4})

        self.assertEqual("一句话四", result[4]["summary"])
        self.assertEqual("是什么", result[1]["what"])
        self.assertEqual("", result[4]["what"])

    def test_parse_editorial_rejects_missing_summary(self) -> None:
        raw = '[{"rank": 1, "summary": "正常"}, {"rank": 2, "summary": ""}]'

        with self.assertRaises(RuntimeError):
            parse_editorial(raw, expected_ranks={1, 2})


class SocialCopyTests(unittest.TestCase):
    def test_overlong_title_falls_back_to_natural_breakpoint(self) -> None:
        titles = social._clean_titles(["今日榜首涨星1588，Python项目占多数"])

        self.assertEqual(["今日榜首涨星1588"], titles)

    def test_overlong_title_without_breakpoint_is_dropped(self) -> None:
        titles = social._clean_titles(["超" * 40, "  ", "正常标题"])

        self.assertEqual(["正常标题"], titles)

    def test_space_and_colon_are_not_treated_as_breakpoints(self) -> None:
        titles = social._clean_titles(["今日 GitHub 热榜：AI 编程工具集体上涨"])

        self.assertEqual([], titles)

    def test_titles_within_limit_are_kept_verbatim(self) -> None:
        titles = social._clean_titles(["今天最火的开源项目", "今天最火的开源项目"])

        self.assertEqual(["今天最火的开源项目"], titles)

    def test_tags_drop_hash_prefix_and_duplicates(self) -> None:
        tags = social._clean_tags(["#GitHub", "GitHub", " 开源 项目 ", ""])

        self.assertEqual(["GitHub", "开源项目"], tags)

    def test_fallback_copy_is_usable_without_llm(self) -> None:
        copy = social.fallback(make_repos(10))

        self.assertTrue(copy.titles)
        self.assertTrue(all(len(t) <= social.TITLE_LIMIT for t in copy.titles))
        self.assertTrue(copy.lede)
        self.assertIn("GitHub", copy.tags)


if __name__ == "__main__":
    unittest.main()
