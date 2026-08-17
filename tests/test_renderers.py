import unittest

from renderers import article, carddeck
from renderers.fonts import load_font, sanitize, text_width, wrap
from renderers.format import fmt_count, fmt_delta
from tests.fixtures import make_bundle


class FormatTests(unittest.TestCase):
    def test_counts_use_compact_units(self) -> None:
        self.assertEqual("999", fmt_count(999))
        self.assertEqual("1.2k", fmt_count(1234))
        self.assertEqual("12k", fmt_count(12345))
        self.assertEqual("1.2M", fmt_count(1_234_567))
        self.assertEqual("+1.2k★", fmt_delta(1234))


class SanitizeTests(unittest.TestCase):
    def test_emoji_are_stripped_because_cjk_fonts_lack_glyphs(self) -> None:
        self.assertEqual("热榜第二", sanitize("热榜第二🔥"))
        self.assertEqual("上新", sanitize("🚀 上新 ✨"))

    def test_symbols_actually_used_by_the_layout_survive(self) -> None:
        self.assertEqual("+1.6k★", sanitize("+1.6k★"))
        self.assertEqual("打开仓库 →", sanitize("打开仓库 →"))
        self.assertEqual("Python · 累计", sanitize("Python · 累计"))

    def test_wrap_applies_sanitize(self) -> None:
        lines = wrap("热榜第二🔥", load_font(32), 600)

        self.assertEqual(["热榜第二"], lines)


class WrapTests(unittest.TestCase):
    def test_ascii_identifiers_are_not_split_when_they_fit(self) -> None:
        font = load_font(32)
        name = "owner/some-long-project-name"
        width = text_width(name, font) + 40

        lines = wrap(f"{name} 是一个很棒的项目", font, width)

        self.assertGreater(len(lines), 1)
        self.assertEqual(name, lines[0])

    def test_token_wider_than_the_line_is_broken_by_character(self) -> None:
        font = load_font(48)
        name = "MakazhanAlpamys/super-long-project-name-for-layout-test"

        lines = wrap(name, font, 400)

        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertLessEqual(text_width(line, font), 400)
        self.assertEqual(name, "".join(lines))

    def test_max_lines_truncates_with_ellipsis(self) -> None:
        font = load_font(32)
        text = "这是一段很长的中文描述文本" * 6

        lines = wrap(text, font, 300, max_lines=2)

        self.assertEqual(2, len(lines))
        self.assertTrue(lines[-1].endswith("…"))
        self.assertLessEqual(text_width(lines[-1], font), 300)


class ArticleRendererTests(unittest.TestCase):
    def test_render_produces_html_cover_and_text_files(self) -> None:
        bundle = make_bundle()

        result = article.render(bundle)

        self.assertEqual("wechat_mp", result.platform)
        self.assertIn("开源升温榜", result.body_html)
        self.assertIn("acme/project-1", result.body_html)
        self.assertEqual(["cover.png"], [a.name for a in result.images])
        self.assertEqual((900, 383), result.images[0].image.size)
        self.assertEqual({"article.html", "article.md"}, set(result.text_files))
        self.assertIn("acme/project-1", result.text_files["article.md"])

    def test_render_uses_bundle_date_not_wall_clock(self) -> None:
        bundle = make_bundle()

        self.assertIn("2026-08-17", article.render(bundle).body_html)


class CardDeckRendererTests(unittest.TestCase):
    def test_ten_repos_produce_cover_three_details_and_two_lists(self) -> None:
        result = carddeck.render(make_bundle(10))

        self.assertEqual("xhs", result.platform)
        self.assertEqual(6, len(result.images))
        self.assertEqual(
            [f"card_{i:02d}.png" for i in range(1, 7)],
            [a.name for a in result.images],
        )
        for asset in result.images:
            self.assertEqual((1080, 1440), asset.image.size)

    def test_note_contains_every_repo_and_tags(self) -> None:
        bundle = make_bundle(10)

        note = carddeck.build_note(bundle)

        for repo in bundle.repos:
            self.assertIn(repo["full_name"], note)
        self.assertIn("#GitHub", note)
        self.assertTrue(note.startswith(bundle.social_title))

    def test_title_and_tags_stay_out_of_the_body_field(self) -> None:
        bundle = make_bundle(10)

        result = carddeck.render(bundle)

        fields = {item.label: item.text for item in result.copy_fields}
        self.assertEqual(["标题", "正文", "话题标签"], list(fields))
        self.assertEqual(bundle.social_title, fields["标题"])
        # 正文要能直接粘进小红书的正文框，不该夹带标题或话题。
        self.assertNotIn(bundle.social_title, fields["正文"])
        self.assertNotIn("#", fields["正文"])

    def test_short_list_still_renders_without_list_cards(self) -> None:
        result = carddeck.render(make_bundle(3))

        self.assertEqual(4, len(result.images))


if __name__ == "__main__":
    unittest.main()
