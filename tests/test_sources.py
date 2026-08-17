import unittest

from sources import github_trending


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

        result = github_trending.merge_rank_repos(repos, limit=10)

        self.assertEqual(10, len(result))
        self.assertEqual("org/repo-12", result[0]["full_name"])
        self.assertEqual("org/repo-3", result[-1]["full_name"])
        self.assertEqual(list(range(1, 11)), [r["rank"] for r in result])

    def test_parse_int_ignores_separators_and_labels(self) -> None:
        self.assertEqual(1234, github_trending.parse_int("1,234 stars today"))
        self.assertEqual(0, github_trending.parse_int(None))
        self.assertEqual(0, github_trending.parse_int("no digits"))


if __name__ == "__main__":
    unittest.main()
