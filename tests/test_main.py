import unittest

import main


class RankingTests(unittest.TestCase):
    def test_merge_rank_repos_deduplicates_and_returns_top_ten(self) -> None:
        repos = [
            {
                "full_name": f"org/repo-{i}",
                "stars_today": i * 10,
                "stars_total": i * 100,
            }
            for i in range(1, 13)
        ]
        repos.append(
            {
                "full_name": "org/repo-12",
                "stars_today": 120,
                "stars_total": 1200,
            }
        )

        result = main.merge_rank_repos(repos, limit=10)

        self.assertEqual(10, len(result))
        self.assertEqual("org/repo-12", result[0]["full_name"])
        self.assertEqual("org/repo-3", result[-1]["full_name"])
        self.assertEqual(list(range(1, 11)), [r["rank"] for r in result])


class EditorialTests(unittest.TestCase):
    def test_parse_editorial_requires_summary_for_all_repos(self) -> None:
        raw = """[
          {"rank": 1, "summary": "一句话一", "what": "是什么", "why": "为什么", "who": "适合谁"},
          {"rank": 2, "summary": "一句话二", "what": "是什么", "why": "为什么", "who": "适合谁"},
          {"rank": 3, "summary": "一句话三", "what": "是什么", "why": "为什么", "who": "适合谁"},
          {"rank": 4, "summary": "一句话四"}
        ]"""

        result = main.parse_editorial(raw, expected_ranks={1, 2, 3, 4})

        self.assertEqual("一句话四", result[4]["summary"])
        self.assertEqual("是什么", result[1]["what"])

    def test_parse_editorial_rejects_missing_summary(self) -> None:
        raw = '[{"rank": 1, "summary": "正常"}, {"rank": 2, "summary": ""}]'

        with self.assertRaises(RuntimeError):
            main.parse_editorial(raw, expected_ranks={1, 2})


if __name__ == "__main__":
    unittest.main()
