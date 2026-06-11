import importlib.util
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "scripts" / "short_video_collect.py"


def load_module():
    spec = importlib.util.spec_from_file_location("short_video_collect", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ShortVideoCollectTests(unittest.TestCase):
    def test_detect_platform_prefers_douyin_urls(self):
        svc = load_module()

        self.assertEqual(svc.detect_platform("https://v.douyin.com/demo/"), "douyin")
        self.assertEqual(svc.detect_platform("https://www.douyin.com/video/123"), "douyin")

    def test_collect_parser_defaults_to_auto_platform(self):
        svc = load_module()

        args = svc.build_parser().parse_args(["collect", "https://v.douyin.com/demo/"])

        self.assertEqual(args.platform, "auto")
        self.assertEqual(args.model, "medium")
        self.assertEqual(args.limit, 10)

    def test_auto_platform_dispatches_douyin_collect(self):
        svc = load_module()
        calls = []

        def fake_douyin_main(argv):
            calls.append(argv)
            return 0

        original = svc.douyin_collect.main
        try:
            svc.douyin_collect.main = fake_douyin_main
            code = svc.main(
                [
                    "collect",
                    "https://v.douyin.com/demo/",
                    "--platform",
                    "auto",
                    "--dry-run",
                    "--limit",
                    "1",
                ]
            )
        finally:
            svc.douyin_collect.main = original

        self.assertEqual(code, 0)
        self.assertEqual(calls, [["collect", "https://v.douyin.com/demo/", "--limit", "1", "--dry-run"]])

    def test_unimplemented_platform_returns_clear_error(self):
        svc = load_module()

        with self.assertRaises(NotImplementedError) as ctx:
            svc.dispatch_collect(
                svc.build_parser().parse_args(
                    ["collect", "https://www.kuaishou.com/short-video/demo", "--platform", "kuaishou"]
                )
            )

        self.assertIn("v1 暂未实现 kuaishou", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
