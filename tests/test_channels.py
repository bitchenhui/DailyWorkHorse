import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from channels.bundle import BundleChannel
from channels.overview import build_overview_page
from renderers import article, carddeck
from tests.fixtures import make_bundle


class BundleChannelTests(unittest.TestCase):
    def test_wechat_bundle_lands_in_platform_subdirectory(self) -> None:
        bundle = make_bundle()
        result = article.render(bundle)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            channel = BundleChannel(root)
            channel.preflight()
            delivered = channel.deliver(bundle, result)

            target = root / "wechat_mp"
            self.assertTrue(delivered.ok)
            self.assertEqual(str(target), delivered.location)
            for name in ("index.html", "article.html", "article.md", "cover.png"):
                self.assertTrue((target / name).is_file(), name)

            page = (target / "index.html").read_text(encoding="utf-8")
            self.assertIn("复制正文（富文本）", page)
            self.assertIn("返回总览", page)
            self.assertNotIn("复制文案", page)

    def test_xhs_bundle_writes_every_card_and_note(self) -> None:
        bundle = make_bundle()
        result = carddeck.render(bundle)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            channel = BundleChannel(root)
            channel.preflight()
            channel.deliver(bundle, result)

            target = root / "xhs"
            self.assertTrue((target / "note.txt").is_file())
            self.assertEqual(6, len(list(target.glob("card_*.png"))))

            page = (target / "index.html").read_text(encoding="utf-8")
            self.assertIn("复制文案", page)
            self.assertIn("card_01.png", page)
            self.assertIn("全部下载", page)
            self.assertNotIn("复制正文（富文本）", page)

    def test_redelivery_clears_stale_files(self) -> None:
        bundle = make_bundle()

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            channel = BundleChannel(root)
            channel.preflight()
            channel.deliver(bundle, carddeck.render(bundle))
            stale = root / "xhs" / "card_09.png"
            stale.write_bytes(b"stale")

            channel.deliver(bundle, carddeck.render(bundle))

            self.assertFalse(stale.exists())


class OverviewTests(unittest.TestCase):
    def test_overview_links_every_platform(self) -> None:
        bundle = make_bundle()
        results = [article.render(bundle), carddeck.render(bundle)]

        page = build_overview_page(bundle, results)

        self.assertIn('href="wechat_mp/index.html"', page)
        self.assertIn('href="xhs/index.html"', page)
        self.assertIn("微信公众号", page)
        self.assertIn("小红书", page)
        self.assertIn("共 2 个平台待发布", page)


if __name__ == "__main__":
    unittest.main()
