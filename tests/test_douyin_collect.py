import importlib.util
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "scripts" / "douyin_collect.py"


def load_module():
    spec = importlib.util.spec_from_file_location("douyin_collect", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DouyinCollectTests(unittest.TestCase):
    def test_extract_douyin_url_from_share_text(self):
        dc = load_module()
        share_text = (
            "3.30 复制打开抖音，看看【钱江晚报的作品】近日，萧山城河街一家复古老茶馆悄然走红。"
            "https://v.douyin.com/zhw_hrZ0E-c/ :3pm w@f.OX 04/21 PXm:/ 。"
        )

        self.assertEqual(dc.extract_douyin_url(share_text), "https://v.douyin.com/zhw_hrZ0E-c/")

    def test_safe_filename_removes_cross_platform_invalid_chars(self):
        dc = load_module()

        result = dc.safe_filename('a/b\\c:*?"<>|  .', fallback="untitled", max_length=80)

        self.assertTrue(result)
        self.assertNotEqual(result, "untitled")
        self.assertTrue(all(ch not in result for ch in '/\\:*?"<>|'))
        self.assertLessEqual(len(result), 80)

    def test_normalize_video_payload_uses_video_url_when_audio_missing(self):
        dc = load_module()
        payload = {
            "code": 200,
            "msg": "解析成功",
            "data": {
                "type": "video",
                "title": "近日，萧山城河街一家复古老茶馆悄然走红。",
                "desc": "近日，萧山城河街一家复古老茶馆悄然走红。",
                "author": {"name": "钱江晚报", "id": 93184216277},
                "url": "https://example.test/video.mp4",
                "video_backup": [{"url": "https://example.test/backup.mp4"}],
                "music": {"url": ""},
                "duration": 18877,
            },
        }

        items = dc.normalize_video_payload(
            payload,
            source_url="https://www.douyin.com/video/7649708931048033582",
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["aweme_id"], "7649708931048033582")
        self.assertEqual(items[0]["author_name"], "钱江晚报")
        self.assertEqual(items[0]["audio_url"], "")
        self.assertEqual(items[0]["video_url"], "https://example.test/video.mp4")
        self.assertEqual(items[0]["platform"], "douyin")
        self.assertEqual(items[0]["provider"], "bugpk")
        self.assertTrue(items[0]["title"].startswith("近日，萧山城河街"))

    def test_normalize_profile_payload_respects_limit_and_fields(self):
        dc = load_module()
        payload = {
            "code": 200,
            "msg": "success",
            "data": [
                {
                    "index": 1,
                    "aweme_id": "111",
                    "desc": "第一个视频",
                    "create_time": "2026-01-01 12:00:00",
                    "share_url": "https://www.douyin.com/video/111",
                    "author": "面试博主",
                    "author_uid": "42",
                    "url": "https://example.test/111.mp4",
                    "music_url": "https://example.test/111.mp3",
                    "statistics": {"digg_count": 10},
                    "hashtags": ["面试"],
                },
                {
                    "index": 2,
                    "aweme_id": "222",
                    "desc": "第二个视频",
                    "share_url": "https://www.douyin.com/video/222",
                    "author": "面试博主",
                },
            ],
        }

        items = dc.normalize_profile_payload(payload, source_url="https://www.douyin.com/user/demo", limit=1)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["aweme_id"], "111")
        self.assertEqual(items[0]["author_name"], "面试博主")
        self.assertEqual(items[0]["audio_url"], "https://example.test/111.mp3")
        self.assertEqual(items[0]["video_url"], "https://example.test/111.mp4")
        self.assertEqual(items[0]["platform"], "douyin")
        self.assertEqual(items[0]["provider"], "bugpk")
        self.assertEqual(items[0]["hashtags"], ["面试"])

    def test_build_ffmpeg_extract_command_is_non_interactive(self):
        dc = load_module()

        command = dc.build_ffmpeg_extract_command(Path("in.mp4"), Path("out.mp3"), overwrite=False)

        self.assertEqual(command[:3], ["ffmpeg", "-y", "-i"])
        self.assertIn("-vn", command)
        self.assertIn(str(Path("in.mp4")), command)
        self.assertIn(str(Path("out.mp3")), command)

    def test_build_ffmpeg_frame_command_seeks_and_writes_jpg(self):
        dc = load_module()

        command = dc.build_ffmpeg_frame_command(Path("in.mp4"), Path("frame_01.jpg"), 12.3456)

        self.assertEqual(command[:2], ["ffmpeg", "-y"])
        self.assertIn("-ss", command)
        self.assertIn("12.346", command)
        self.assertIn("-frames:v", command)
        self.assertIn(str(Path("frame_01.jpg")), command)

    def test_parse_content_range_total_for_resume_download(self):
        dc = load_module()

        self.assertEqual(dc.parse_content_range_total("bytes 100-999/5000"), 5000)
        self.assertEqual(dc.parse_content_range_total(None), 0)

    def test_frame_timestamps_uses_middle_range(self):
        dc = load_module()

        result = dc.frame_timestamps(100000, 3)

        self.assertEqual([round(value, 1) for value in result], [12.0, 50.0, 88.0])

    def test_duration_to_seconds_accepts_milliseconds_and_clock_text(self):
        dc = load_module()

        self.assertEqual(dc.duration_to_seconds(293035), 293.035)
        self.assertEqual(dc.duration_to_seconds("01:02"), 62)
        self.assertEqual(dc.duration_to_seconds("01:02:03"), 3723)

    def test_parse_timecode_list_accepts_clock_and_comma_values(self):
        dc = load_module()

        result = dc.parse_timecode_list(["8", "00:05:35,00:21:40"])

        self.assertEqual(result, [8.0, 335.0, 1300.0])

    def test_restore_chinese_punctuation_uses_segment_boundaries(self):
        dc = load_module()
        segments = [
            {"text": "你只要花8块钱就可以在这里坐一天都没有问题"},
            {"text": "我很喜欢这种古老的玩意儿"},
            {"text": "这边很有茶文化"},
        ]

        result = dc.restore_chinese_punctuation("", segments)

        self.assertEqual(result, "你只要花8块钱就可以在这里坐一天都没有问题。我很喜欢这种古老的玩意儿。这边很有茶文化。")

    def test_restore_chinese_punctuation_keeps_existing_punctuation(self):
        dc = load_module()
        text = "这里很舒服。价格也不贵。"

        self.assertEqual(dc.restore_chinese_punctuation(text, []), text)

    def test_restore_chinese_punctuation_splits_long_unpunctuated_text(self):
        dc = load_module()
        text = "你只要花8块钱就可以在这里坐一天都没有问题我很喜欢这种古老的玩意儿这边很有茶文化我是最喜欢的非常满意"

        result = dc.restore_chinese_punctuation(text, [])

        self.assertIn("。", result)
        self.assertTrue(result.endswith("。"))

    def test_collect_command_defaults_to_medium_model(self):
        dc = load_module()

        parser = dc.build_parser()
        args = parser.parse_args(["collect", "https://v.douyin.com/zhw_hrZ0E-c/"])

        self.assertEqual(args.model, "medium")

    def test_collect_command_accepts_large_v3_models_for_accuracy(self):
        dc = load_module()

        parser = dc.build_parser()
        args = parser.parse_args(
            ["collect", "https://v.douyin.com/zhw_hrZ0E-c/", "--model", "large-v3"]
        )

        self.assertEqual(args.model, "large-v3")

    def test_build_whisper_initial_prompt_uses_video_context(self):
        dc = load_module()
        item = {
            "title": "萧山城河街复古老茶馆走红",
            "desc": "茶馆于6月8日试营业，消费亲民，怀旧氛围浓。",
            "author_name": "钱江晚报",
        }

        prompt = dc.build_whisper_initial_prompt(item)

        self.assertIn("萧山城河街复古老茶馆走红", prompt)
        self.assertIn("6月8日", prompt)
        self.assertIn("钱江晚报", prompt)

    def test_build_whisper_transcribe_options_for_chinese_accuracy(self):
        dc = load_module()

        options = dc.build_whisper_transcribe_options("上下文提示")

        self.assertEqual(options["language"], "zh")
        self.assertEqual(options["task"], "transcribe")
        self.assertEqual(options["temperature"], 0)
        self.assertEqual(options["initial_prompt"], "上下文提示")

    def test_collect_command_supports_optional_ai_polish(self):
        dc = load_module()

        parser = dc.build_parser()
        args = parser.parse_args(
            [
                "collect",
                "https://v.douyin.com/zhw_hrZ0E-c/",
                "--ai-polish",
                "--ai-model",
                "gpt-5.5",
            ]
        )

        self.assertTrue(args.ai_polish)
        self.assertEqual(args.ai_model, "gpt-5.5")

    def test_collect_command_accepts_wechat_warm_card_template(self):
        dc = load_module()

        parser = dc.build_parser()
        args = parser.parse_args(
            [
                "collect",
                "https://v.douyin.com/zhw_hrZ0E-c/",
                "--wechat-template",
                "warm-card",
            ]
        )

        self.assertEqual(args.wechat_template, "warm-card")

    def test_collect_command_accepts_autumn_warm_alias(self):
        dc = load_module()

        parser = dc.build_parser()
        args = parser.parse_args(
            [
                "collect",
                "https://v.douyin.com/zhw_hrZ0E-c/",
                "--wechat-template",
                "autumn-warm",
            ]
        )

        self.assertEqual(args.wechat_template, "autumn-warm")

    def test_collect_command_accepts_frame_count(self):
        dc = load_module()

        parser = dc.build_parser()
        args = parser.parse_args(
            [
                "collect",
                "https://v.douyin.com/zhw_hrZ0E-c/",
                "--frame-count",
                "5",
            ]
        )

        self.assertEqual(args.frame_count, 5)

    def test_extract_frames_command_accepts_times_and_prefix(self):
        dc = load_module()

        parser = dc.build_parser()
        args = parser.parse_args(
            [
                "extract-frames",
                "output/作者/111",
                "--times",
                "00:00:08",
                "00:05:35,00:21:40",
                "--prefix",
                "dialogue",
                "--contact-sheet",
            ]
        )

        self.assertEqual(args.command, "extract-frames")
        self.assertEqual(args.times, ["00:00:08", "00:05:35,00:21:40"])
        self.assertEqual(args.prefix, "dialogue")
        self.assertTrue(args.contact_sheet)

    def test_render_article_command_accepts_warm_card_template(self):
        dc = load_module()

        parser = dc.build_parser()
        args = parser.parse_args(
            [
                "render-article",
                "output/作者/111",
                "--input",
                "dialogue.md",
                "--html",
                "dialogue-warm-card.html",
            ]
        )

        self.assertEqual(args.command, "render-article")
        self.assertEqual(args.input, "dialogue.md")
        self.assertEqual(args.html, "dialogue-warm-card.html")
        self.assertEqual(args.template, "warm-card")

    def test_ai_polish_prompt_preserves_source_and_forbids_fabrication(self):
        dc = load_module()
        item = {
            "title": "面试经验",
            "desc": "讲简历和面试准备",
            "author_name": "面试博主",
            "share_url": "https://www.douyin.com/video/111",
            "transcript_text": "准备面试要先看岗位要求然后整理项目经历",
        }

        prompt = dc.build_ai_polish_prompt(item)

        self.assertIn("不要伪装成原创", prompt)
        self.assertIn("不要编造", prompt)
        self.assertIn("面试博主", prompt)
        self.assertIn("准备面试要先看岗位要求", prompt)

    def test_write_transcript_markdown_includes_ai_polished_copy(self):
        dc = load_module()
        item = {
            "title": "面试经验",
            "author_name": "面试博主",
            "share_url": "https://www.douyin.com/video/111",
            "create_time": "",
            "duration": "",
            "local_video_path": "demo/video.mp4",
            "local_audio_path": "demo/audio.mp3",
            "desc": "原始文案",
            "transcript_text": "准备面试要先看岗位要求。",
            "ai_polished_text": "准备面试时，先阅读岗位要求，再整理自己的项目经历。",
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "transcript.md"
            dc.write_transcript_markdown(path, item)
            text = path.read_text(encoding="utf-8")

        self.assertIn("## AI 清洗版", text)
        self.assertIn("准备面试时，先阅读岗位要求", text)

    def test_video_copy_text_prefers_punctuated_transcript_only(self):
        dc = load_module()
        item = {
            "desc": "接口文案",
            "transcript_text": "第一句话。第二句话。",
            "raw_transcript_text": "第一句话第二句话",
            "ai_polished_text": "不应该用于纯文案",
        }

        self.assertEqual(dc.video_copy_text(item), "第一句话。第二句话。")

    def test_write_copy_outputs_creates_markdown_and_plain_text(self):
        dc = load_module()
        item = {
            "title": "面试经验",
            "author_name": "面试博主",
            "share_url": "https://www.douyin.com/video/111",
            "aweme_id": "111",
            "transcript_text": "准备面试要先看岗位要求。然后整理项目经历。",
        }

        with tempfile.TemporaryDirectory() as tmp:
            item_dir = Path(tmp)
            outputs = dc.write_copy_outputs(item_dir, item)
            copy_md = (item_dir / "copy.md").read_text(encoding="utf-8")
            copy_txt = (item_dir / "copy.txt").read_text(encoding="utf-8")

        self.assertEqual(outputs["copy_md"], "copy.md")
        self.assertEqual(outputs["copy_txt"], "copy.txt")
        self.assertIn("# 面试经验", copy_md)
        self.assertIn("来源：面试博主", copy_md)
        self.assertIn("准备面试要先看岗位要求。", copy_md)
        self.assertEqual(copy_txt, "准备面试要先看岗位要求。然后整理项目经历。")

    def test_write_wechat_outputs_creates_warm_card_inline_html(self):
        dc = load_module()
        item = {
            "title": "自我介绍重点在于打造“人设”",
            "author_name": "02万辞王",
            "share_url": "https://www.douyin.com/video/111?previous_page=app_code_link",
            "aweme_id": "111",
            "transcript_text": "自我介绍不是复述简历，而是用一个清晰的人设让面试官记住你。",
            "local_frame_paths": ["media/frames/frame_01.jpg"],
        }

        with tempfile.TemporaryDirectory() as tmp:
            item_dir = Path(tmp)
            (item_dir / "copy.zh.txt").write_text(
                "自我介绍不是复述简历，而是用一个清晰的人设，让面试官记住你。",
                encoding="utf-8",
            )
            outputs = dc.write_wechat_outputs(item_dir, item, template="warm-card")
            wechat_md = (item_dir / "wechat.md").read_text(encoding="utf-8")
            wechat_html = (item_dir / "wechat-warm-card.html").read_text(encoding="utf-8")

        self.assertEqual(outputs["wechat_md"], "wechat.md")
        self.assertEqual(outputs["wechat_html"], "wechat-warm-card.html")
        self.assertIn("把视频里的重要内容整理成更适合阅读的文字", wechat_md)
        self.assertNotIn("原视频链接见文末", wechat_md)
        self.assertIn("![视频截图 1](media/frames/frame_01.jpg)", wechat_md)
        self.assertIn("自我介绍不是复述简历", wechat_md)
        self.assertIn("background-color:#faf9f5", wechat_html)
        self.assertIn('src="media/frames/frame_01.jpg"', wechat_html)
        self.assertIn("box-sizing:border-box", wechat_html)
        self.assertIn("style=", wechat_html)
        self.assertNotIn("<style", wechat_html.lower())
        self.assertNotIn("class=", wechat_html.lower())

    def test_warm_card_renders_h3_as_subheading(self):
        dc = load_module()
        html = dc.render_warm_card_html("# 标题\n\n## 正文\n\n### 小节标题\n\n内容")

        self.assertIn("<h3", html)
        self.assertIn("小节标题", html)
        self.assertNotIn("### 小节标题", html)

    def test_copy_text_does_not_include_review_markers(self):
        dc = load_module()
        item = {
            "transcript_text": "你只要花[疑似：半块钱/8块钱]，就可以在这里坐一天。"
        }

        self.assertEqual(dc.video_copy_text(item), "你只要花半块钱，就可以在这里坐一天。")

    def test_video_copy_text_breaks_only_long_paragraphs(self):
        dc = load_module()
        item = {
            "transcript_text": (
                "第一句内容比较长但仍然属于同一个话题。"
                "第二句继续解释这个话题。"
                "第三句补充更多背景。"
                "第四句自然延续。"
                "第五句让整段超过默认长度。"
                "第六句用于触发分段。"
            )
        }

        result = dc.video_copy_text(item, paragraph_max_chars=45)

        self.assertIn("\n\n", result)
        self.assertNotIn("。\n\n第二句", result)

    def test_clean_wechat_title_removes_douyin_hashtags(self):
        dc = load_module()

        result = dc.clean_wechat_title("自我介绍重点在于打造“人设” #面试 #求职 #找工作")

        self.assertEqual(result, "自我介绍重点在于打造“人设”")

    def test_load_existing_metadata_preserves_transcript_fields(self):
        dc = load_module()
        metadata = {
            "transcript_text": "已有带标点文本。",
            "raw_transcript_text": "已有带标点文本",
            "transcript_segments": [{"text": "已有带标点文本"}],
        }

        with tempfile.TemporaryDirectory() as tmp:
            item_dir = Path(tmp)
            (item_dir / "metadata.json").write_text(
                dc.json.dumps(metadata, ensure_ascii=False),
                encoding="utf-8",
            )
            result = dc.load_existing_metadata(item_dir)

        self.assertEqual(result["transcript_text"], "已有带标点文本。")
        self.assertEqual(result["raw_transcript_text"], "已有带标点文本")
        self.assertEqual(len(result["transcript_segments"]), 1)

    def test_load_existing_metadata_accepts_utf8_bom(self):
        dc = load_module()

        with tempfile.TemporaryDirectory() as tmp:
            item_dir = Path(tmp)
            (item_dir / "metadata.json").write_text(
                '{"transcript_text":"BOM 也能读取。"}',
                encoding="utf-8-sig",
            )
            result = dc.load_existing_metadata(item_dir)

        self.assertEqual(result["transcript_text"], "BOM 也能读取。")


if __name__ == "__main__":
    unittest.main()
