import os
import unittest
from unittest import mock

from core import config


class PlatformSwitchTests(unittest.TestCase):
    def test_defaults_to_all_known_platforms(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(config.DEFAULT_PLATFORMS, config.enabled_platforms())

    def test_explicit_subset_is_respected(self) -> None:
        with mock.patch.dict(os.environ, {"ENABLED_PLATFORMS": "xhs"}, clear=True):
            self.assertEqual(("xhs",), config.enabled_platforms())

    def test_unknown_platform_fails_fast(self) -> None:
        with mock.patch.dict(
            os.environ, {"ENABLED_PLATFORMS": "xhs,douyin"}, clear=True
        ):
            with self.assertRaises(SystemExit):
                config.enabled_platforms()

    def test_tier_defaults_to_bundle_and_reads_env(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual("bundle", config.platform_tier("xhs"))
        with mock.patch.dict(os.environ, {"XHS_TIER": "Playwright"}, clear=True):
            self.assertEqual("playwright", config.platform_tier("xhs"))


class ChannelResolutionTests(unittest.TestCase):
    def test_unimplemented_tier_raises_readable_error(self) -> None:
        import pipeline

        with mock.patch.dict(os.environ, {"XHS_TIER": "playwright"}, clear=True):
            with self.assertRaises(SystemExit) as ctx:
                pipeline.resolve_channel("xhs")

        self.assertIn("小红书", str(ctx.exception))
        self.assertIn("playwright", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
