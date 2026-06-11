import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "scripts" / "export_pdf.py"


def load_module():
    spec = importlib.util.spec_from_file_location("export_pdf", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ExportPdfTests(unittest.TestCase):
    def test_choose_input_file_prefers_dialogue(self):
        pdf = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            item_dir = Path(tmp)
            (item_dir / "copy.zh.md").write_text("# 文案", encoding="utf-8")
            (item_dir / "dialogue.md").write_text("# 对话", encoding="utf-8")

            result = pdf.choose_input_file(item_dir, None)

        self.assertEqual(result.name, "dialogue.md")

    def test_default_pdf_path_uses_input_stem(self):
        pdf = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            item_dir = Path(tmp)
            input_path = item_dir / "article.md"

            result = pdf.default_pdf_path(item_dir, input_path, None)

        self.assertEqual(result, item_dir / "article.pdf")

    def test_default_docx_path_uses_input_stem(self):
        pdf = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            item_dir = Path(tmp)
            input_path = item_dir / "article.md"

            result = pdf.default_docx_path(item_dir, input_path, None)

        self.assertEqual(result, item_dir / "article.docx")

    def test_markdown_without_images_removes_standalone_images(self):
        pdf = load_module()

        result = pdf.markdown_without_images("# 标题\n\n![截图](media/frame.jpg)\n\n正文")

        self.assertEqual(result, "# 标题\n\n正文")

    def test_choose_provider_prefers_typst_then_soffice_then_docx(self):
        pdf = load_module()
        original = pdf.available_provider
        try:
            pdf.available_provider = lambda provider: provider in {"pandoc-soffice", "pandoc-docx"}
            self.assertEqual(pdf.choose_provider("auto"), "pandoc-soffice")

            pdf.available_provider = lambda provider: provider == "pandoc-docx"
            self.assertEqual(pdf.choose_provider("auto"), "pandoc-docx")
        finally:
            pdf.available_provider = original

    def test_choose_provider_returns_requested_provider(self):
        pdf = load_module()

        self.assertEqual(pdf.choose_provider("pandoc-docx"), "pandoc-docx")

    def test_infer_title_reads_markdown_h1(self):
        pdf = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "article.md"
            input_path.write_text("# 公众号标题\n\n正文", encoding="utf-8")

            result = pdf.infer_title(input_path, None, {"title": "metadata title"})

        self.assertEqual(result, "公众号标题")

    def test_export_uses_markdown_h1_without_extra_pandoc_title(self):
        pdf = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            item_dir = Path(tmp)
            input_path = item_dir / "article.md"
            pdf_path = item_dir / "article.pdf"
            input_path.write_text("# 正文标题\n\n正文", encoding="utf-8")
            captured_titles = []

            original_choose_provider = pdf.choose_provider
            original_pandoc_to_docx = pdf.pandoc_to_docx
            original_soffice_docx_to_pdf = pdf.soffice_docx_to_pdf
            try:
                pdf.choose_provider = lambda provider: "pandoc-soffice"

                def fake_pandoc_to_docx(input_md, item_dir_arg, docx_path, title=None):
                    captured_titles.append(title)
                    docx_path.write_bytes(b"docx")
                    return "pandoc"

                def fake_soffice_docx_to_pdf(docx_path, target_pdf_path):
                    target_pdf_path.write_bytes(b"pdf")
                    return "soffice"

                pdf.pandoc_to_docx = fake_pandoc_to_docx
                pdf.soffice_docx_to_pdf = fake_soffice_docx_to_pdf

                result = pdf.export_markdown_pdf(item_dir, input_path, pdf_path)
            finally:
                pdf.choose_provider = original_choose_provider
                pdf.pandoc_to_docx = original_pandoc_to_docx
                pdf.soffice_docx_to_pdf = original_soffice_docx_to_pdf

        self.assertEqual(captured_titles, [None])
        self.assertEqual(result["title"], "正文标题")

    def test_build_parser_accepts_provider_and_keep_docx(self):
        pdf = load_module()

        args = pdf.build_parser().parse_args(
            ["output/author/id", "--provider", "pandoc-soffice", "--keep-docx", "--no-images"]
        )

        self.assertEqual(args.provider, "pandoc-soffice")
        self.assertTrue(args.keep_docx)
        self.assertTrue(args.no_images)


if __name__ == "__main__":
    unittest.main()
