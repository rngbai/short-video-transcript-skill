from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


IMAGE_RE = re.compile(r"^!\[[^\]]*\]\([^)]+\)\s*$")


def resolve_path(base_dir: Path, raw: str | None) -> Path | None:
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def choose_input_file(item_dir: Path, raw_input: str | None) -> Path:
    if raw_input:
        path = resolve_path(item_dir, raw_input)
        if path and path.is_file():
            return path
        raise FileNotFoundError(f"输入 Markdown 不存在: {raw_input}")

    for name in ("dialogue.md", "article.md", "copy.zh.md", "copy.md", "transcript.md"):
        path = item_dir / name
        if path.is_file():
            return path
    raise FileNotFoundError("未找到可导出的 Markdown，请传入 --input")


def default_pdf_path(item_dir: Path, input_path: Path, raw_pdf: str | None) -> Path:
    if raw_pdf:
        path = resolve_path(item_dir, raw_pdf)
        if path:
            return path
    return item_dir / f"{input_path.stem}.pdf"


def default_docx_path(item_dir: Path, input_path: Path, raw_docx: str | None) -> Path:
    if raw_docx:
        path = resolve_path(item_dir, raw_docx)
        if path:
            return path
    return item_dir / f"{input_path.stem}.docx"


def load_metadata(item_dir: Path) -> dict[str, Any]:
    path = item_dir / "metadata.json"
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {}


def markdown_without_images(text: str) -> str:
    without_images = "\n".join(line for line in text.splitlines() if not IMAGE_RE.match(line.strip()))
    return re.sub(r"\n{3,}", "\n\n", without_images).strip()


def find_command(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    if name == "soffice":
        for path in (
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ):
            if Path(path).is_file():
                return path
    return None


def run_command(command: list[str], cwd: Path | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = completed.stdout or ""
    if completed.returncode != 0:
        raise RuntimeError(f"命令执行失败 ({completed.returncode}): {' '.join(command)}\n{output[:4000]}")
    return output


def prepare_markdown(input_path: Path, work_dir: Path, include_images: bool) -> Path:
    text = input_path.read_text(encoding="utf-8-sig")
    if not include_images:
        text = markdown_without_images(text)
    md_path = work_dir / "input.md"
    md_path.write_text(text, encoding="utf-8")
    return md_path


def pandoc_to_docx(input_md: Path, item_dir: Path, docx_path: Path, title: str | None = None) -> str:
    pandoc = find_command("pandoc")
    if not pandoc:
        raise RuntimeError("未找到 pandoc。请安装 Pandoc，或跳过 PDF/DOCX 导出。")
    command = [
        pandoc,
        str(input_md),
        "-o",
        str(docx_path),
        "--resource-path",
        str(item_dir),
    ]
    if title:
        command.extend(["--metadata", f"title={title}"])
    return run_command(command)


def pandoc_typst_to_pdf(input_md: Path, item_dir: Path, pdf_path: Path, title: str | None = None) -> str:
    pandoc = find_command("pandoc")
    typst = find_command("typst")
    if not pandoc:
        raise RuntimeError("未找到 pandoc，无法使用 pandoc-typst provider。")
    if not typst:
        raise RuntimeError("未找到 typst，无法使用 pandoc-typst provider。")
    command = [
        pandoc,
        str(input_md),
        "-o",
        str(pdf_path),
        "--pdf-engine",
        "typst",
        "--resource-path",
        str(item_dir),
    ]
    if title:
        command.extend(["--metadata", f"title={title}"])
    return run_command(command)


def soffice_docx_to_pdf(docx_path: Path, pdf_path: Path) -> str:
    soffice = find_command("soffice")
    if not soffice:
        raise RuntimeError("未找到 LibreOffice/soffice，无法把 DOCX 转成 PDF。")
    out_dir = docx_path.parent
    output = run_command(
        [
            soffice,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(docx_path),
        ]
    )
    generated = out_dir / f"{docx_path.stem}.pdf"
    if not generated.is_file():
        raise RuntimeError(f"LibreOffice 未生成 PDF: {generated}\n{output[:4000]}")
    if generated.resolve() != pdf_path.resolve():
        shutil.copy2(generated, pdf_path)
    return output


def infer_title(input_path: Path, explicit: str | None, metadata: dict[str, Any]) -> str:
    if explicit:
        return explicit
    for line in input_path.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return str(metadata.get("title") or input_path.stem)


def available_provider(provider: str) -> bool:
    if provider == "pandoc-typst":
        return bool(find_command("pandoc") and find_command("typst"))
    if provider == "pandoc-soffice":
        return bool(find_command("pandoc") and find_command("soffice"))
    if provider == "pandoc-docx":
        return bool(find_command("pandoc"))
    return False


def choose_provider(requested: str) -> str:
    if requested != "auto":
        return requested
    for provider in ("pandoc-typst", "pandoc-soffice", "pandoc-docx"):
        if available_provider(provider):
            return provider
    raise RuntimeError(
        "未找到可用导出 provider。推荐安装 Pandoc；需要 PDF 时再安装 Typst 或 LibreOffice。"
    )


def export_markdown_pdf(
    item_dir: Path,
    input_path: Path,
    pdf_path: Path,
    docx_path: Path | None = None,
    title: str | None = None,
    include_images: bool = True,
    provider: str = "auto",
    keep_docx: bool = False,
) -> dict[str, Any]:
    metadata = load_metadata(item_dir)
    final_title = infer_title(input_path, title, metadata)
    selected_provider = choose_provider(provider)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    if docx_path:
        docx_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="douyin_md_export_") as tmp:
        work_dir = Path(tmp)
        temp_md = prepare_markdown(input_path, work_dir, include_images)
        temp_docx = work_dir / "output.docx"
        temp_pdf = work_dir / "output.pdf"
        logs: list[str] = []

        if selected_provider == "pandoc-typst":
            logs.append(pandoc_typst_to_pdf(temp_md, item_dir, temp_pdf))
            shutil.copy2(temp_pdf, pdf_path)
        elif selected_provider == "pandoc-soffice":
            logs.append(pandoc_to_docx(temp_md, item_dir, temp_docx))
            logs.append(soffice_docx_to_pdf(temp_docx, temp_pdf))
            shutil.copy2(temp_pdf, pdf_path)
            if keep_docx or docx_path:
                target_docx = docx_path or default_docx_path(item_dir, input_path, None)
                target_docx.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(temp_docx, target_docx)
                docx_path = target_docx
        elif selected_provider == "pandoc-docx":
            target_docx = docx_path or default_docx_path(item_dir, input_path, None)
            logs.append(pandoc_to_docx(temp_md, item_dir, temp_docx))
            target_docx.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(temp_docx, target_docx)
            docx_path = target_docx
        else:
            raise RuntimeError(f"未知 provider: {selected_provider}")

    result: dict[str, Any] = {
        "success": True,
        "input": str(input_path),
        "title": final_title,
        "provider": selected_provider,
        "include_images": include_images,
    }
    if selected_provider != "pandoc-docx":
        result["pdf"] = str(pdf_path)
    if docx_path:
        result["docx"] = str(docx_path)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export local Douyin transcript/article Markdown with mature Markdown conversion tools."
    )
    parser.add_argument("item_dir", help="视频输出目录，例如 output/<author>/<aweme_id>")
    parser.add_argument("--input", help="相对 item_dir 的 Markdown；默认 dialogue/article/copy.zh/copy/transcript")
    parser.add_argument("--pdf", help="输出 PDF 路径；默认与输入 Markdown 同名")
    parser.add_argument("--docx", help="输出 DOCX 路径；默认与输入 Markdown 同名")
    parser.add_argument("--title", help="标题；默认读取 Markdown H1 或 metadata.json")
    parser.add_argument("--no-images", action="store_true", help="不把本地截图写入导出文件")
    parser.add_argument(
        "--provider",
        choices=["auto", "pandoc-typst", "pandoc-soffice", "pandoc-docx"],
        default="auto",
        help="默认 auto：typst > soffice > docx",
    )
    parser.add_argument("--keep-docx", action="store_true", help="生成 PDF 时同时保留中间 DOCX")
    parser.add_argument("--result-json", help="可选：写出导出结果 JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    item_dir = Path(args.item_dir).expanduser().resolve()
    if not item_dir.is_dir():
        raise FileNotFoundError(f"视频输出目录不存在: {item_dir}")
    input_path = choose_input_file(item_dir, args.input)
    pdf_path = default_pdf_path(item_dir, input_path, args.pdf)
    docx_path = default_docx_path(item_dir, input_path, args.docx) if args.docx else None
    result = export_markdown_pdf(
        item_dir=item_dir,
        input_path=input_path,
        pdf_path=pdf_path,
        docx_path=docx_path,
        title=args.title,
        include_images=not args.no_images,
        provider=args.provider,
        keep_docx=args.keep_docx,
    )
    if args.result_json:
        result_path = resolve_path(item_dir, args.result_json)
        if result_path:
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            result["result_json"] = str(result_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
