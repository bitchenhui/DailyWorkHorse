import html
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from channels.bundle import BundleChannel
from channels.overview import write_overview
from renderers import article, carddeck, marketvideo
from tests.fixtures import make_bundle, make_market_bundle


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
            self.assertNotIn("话题标签", page)

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
            self.assertIn("话题标签", page)
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
    def deliver_all(self, root: Path, renderers) -> None:
        bundle = make_bundle()
        channel = BundleChannel(root)
        channel.preflight()
        for render in renderers:
            channel.deliver(bundle, render(bundle))

    def test_overview_links_every_platform(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.deliver_all(root, (article.render, carddeck.render))

            page = write_overview(root).read_text(encoding="utf-8")

            self.assertIn('href="wechat_mp/index.html"', page)
            self.assertIn('href="xhs/index.html"', page)
            self.assertIn("微信公众号", page)
            self.assertIn("小红书", page)
            self.assertIn("共 2 项", page)

    def test_each_entry_carries_its_own_title(self) -> None:
        """总览要同时列 GitHub 日报与行情视频，标题不能只显示其中一份。"""
        bundle = make_bundle()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.deliver_all(root, (article.render, carddeck.render))

            page = write_overview(root).read_text(encoding="utf-8")

            for render in (article.render, carddeck.render):
                self.assertIn(html.escape(render(bundle).title), page)

    def test_a_later_run_keeps_the_earlier_run_listed(self) -> None:
        """两个信息源跑在各自的定时任务里。

        下午那趟只产出行情视频，若总览只列本次产物，上午发布的 GitHub 成稿
        就会从站点首页上消失——文件其实还在，只是没人能点进去了。
        """
        market = make_market_bundle(minutes=2)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.deliver_all(root, (article.render,))

            channel = BundleChannel(root)
            channel.deliver(market, marketvideo.render(market))
            page = write_overview(root).read_text(encoding="utf-8")

            self.assertIn('href="wechat_mp/index.html"', page)
            self.assertIn('href="xhs_video/index.html"', page)
            self.assertIn("共 2 项", page)

    def test_a_broken_meta_file_does_not_break_the_page(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.deliver_all(root, (article.render,))
            (root / "xhs").mkdir()
            (root / "xhs" / "meta.json").write_text("{ 半截", encoding="utf-8")

            page = write_overview(root).read_text(encoding="utf-8")

            self.assertIn("共 1 项", page)


if __name__ == "__main__":
    unittest.main()
