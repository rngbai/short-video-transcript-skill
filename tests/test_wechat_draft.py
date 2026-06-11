import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "scripts" / "wechat_draft.py"


def load_module():
    spec = importlib.util.spec_from_file_location("wechat_draft", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class WeChatDraftTests(unittest.TestCase):
    def test_extract_body_html_removes_head_and_style(self):
        wd = load_module()
        html = (
            "<!doctype html><html><head><title>标题</title>"
            "<style>.x{color:red}</style></head><body><div>正文</div></body></html>"
        )

        self.assertEqual(wd.extract_body_html(html), "<div>正文</div>")

    def test_extract_title_prefers_html_title(self):
        wd = load_module()

        self.assertEqual(wd.extract_title("<title>公众号标题</title><h1>备用</h1>"), "公众号标题")

    def test_sanitize_wechat_title_truncates_utf8_safely(self):
        wd = load_module()
        title = "自我介绍重点在于打造人设" * 6

        result = wd.sanitize_wechat_title(title)

        self.assertLessEqual(len(result.encode("utf-8")), 64)
        self.assertTrue(result)

    def test_replace_local_images_uploads_each_file_once(self):
        wd = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            item_dir = Path(tmp)
            image = item_dir / "media" / "frames" / "a.jpg"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"fake-jpg")
            html = '<p><img src="media/frames/a.jpg"></p><p><img src="media/frames/a.jpg"></p>'
            calls = []

            def upload(path):
                calls.append(path)
                return "https://mmbiz.qpic.cn/demo/a.jpg"

            result, uploads = wd.replace_local_images(html, item_dir, upload_image=upload)

        self.assertEqual(len(calls), 1)
        self.assertEqual(len(uploads), 1)
        self.assertIn('src="https://mmbiz.qpic.cn/demo/a.jpg"', result)

    def test_resolve_image_src_rejects_outside_paths(self):
        wd = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            item_dir = Path(tmp) / "item"
            item_dir.mkdir()
            outside = Path(tmp) / "outside.jpg"
            outside.write_bytes(b"fake-jpg")

            with self.assertRaises(RuntimeError):
                wd.resolve_image_src(item_dir, str(outside))

    def test_create_draft_payload_contains_article_fields(self):
        wd = load_module()

        payload = wd.create_draft_payload(
            title="标题",
            author="作者",
            digest="摘要",
            content_html="<p>正文</p>",
            thumb_media_id="thumb123",
            content_source_url="https://www.douyin.com/video/1",
            open_comment=1,
            only_fans_can_comment=0,
            show_cover_pic=0,
        )

        article = payload["articles"][0]
        self.assertEqual(article["title"], "标题")
        self.assertEqual(article["thumb_media_id"], "thumb123")
        self.assertEqual(article["content_source_url"], "https://www.douyin.com/video/1")
        self.assertEqual(article["need_open_comment"], 1)

    def test_default_content_source_url_is_empty_unless_explicit(self):
        wd = load_module()
        args = wd.build_parser().parse_args(["create-draft", "out"])

        self.assertEqual(wd.default_content_source_url(args, {"share_url": "https://www.douyin.com/video/1"}), "")

    def test_create_draft_command_accepts_update_media_id(self):
        wd = load_module()

        args = wd.build_parser().parse_args(
            ["create-draft", "out", "--draft-media-id", "MEDIA123", "--article-index", "0"]
        )

        self.assertEqual(args.draft_media_id, "MEDIA123")
        self.assertEqual(args.article_index, 0)

    def test_create_draft_command_dry_run_writes_preview_and_result(self):
        wd = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            item_dir = Path(tmp)
            image = item_dir / "media" / "frames" / "dialogue_01.jpg"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"fake-jpg")
            (item_dir / "metadata.json").write_text(
                json.dumps({"author_name": "冰言冰语", "share_url": "https://www.douyin.com/video/1"}, ensure_ascii=False),
                encoding="utf-8",
            )
            (item_dir / "dialogue-warm-card.html").write_text(
                "<html><head><title>一一大哥的故事</title></head>"
                '<body><div><h1>一一大哥的故事</h1><img src="media/frames/dialogue_01.jpg"></div></body></html>',
                encoding="utf-8",
            )

            args = wd.build_parser().parse_args(["create-draft", str(item_dir), "--dry-run"])
            with redirect_stdout(io.StringIO()):
                code = wd.run_create_draft(args)
            result = json.loads((item_dir / "wechat-draft-result.json").read_text(encoding="utf-8"))
            preview = (item_dir / "wechat-draft-preview.html").read_text(encoding="utf-8")

        self.assertEqual(code, 0)
        self.assertTrue(result["success"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["title"], "一一大哥的故事")
        self.assertEqual(result["author"], "冰言冰语")
        self.assertIn('src="media/frames/dialogue_01.jpg"', preview)


if __name__ == "__main__":
    unittest.main()
