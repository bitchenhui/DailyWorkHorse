import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import main
import publisher


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


class PublishBundleTests(unittest.TestCase):
    def test_write_bundle_creates_copy_page_article_markdown_and_cover(self) -> None:
        repos = [
            {
                "rank": 1,
                "full_name": "owner/project",
                "url": "https://github.com/owner/project",
                "description": "A useful project",
                "language": "Python",
                "stars_today": 1234,
                "stars_total": 5678,
            }
        ]
        editorial = {
            1: {
                "summary": "用于演示的中文项目摘要",
                "what": "项目是什么",
                "why": "为什么值得关注",
                "who": "适合哪些读者",
            }
        }

        with TemporaryDirectory() as tmp:
            output = Path(tmp)
            publisher.write_publish_bundle(
                output_dir=output,
                title="开源升温榜",
                date_text="2026-08-17",
                article_html='<section id="article">正文</section>',
                repos=repos,
                editorial=editorial,
            )

            self.assertTrue((output / "index.html").is_file())
            self.assertTrue((output / "article.html").is_file())
            self.assertTrue((output / "article.md").is_file())
            self.assertTrue((output / "cover.png").is_file())

            index = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn("复制公众号正文", index)
            self.assertIn("ClipboardItem", index)
            self.assertIn("download=\"cover.png\"", index)

            markdown = (output / "article.md").read_text(encoding="utf-8")
            self.assertIn("owner/project", markdown)
            self.assertIn("用于演示的中文项目摘要", markdown)

            from PIL import Image

            with Image.open(output / "cover.png") as image:
                self.assertEqual((900, 383), image.size)


if __name__ == "__main__":
    unittest.main()
