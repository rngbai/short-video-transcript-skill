#!/usr/bin/env python3
"""Generic short-video collection entrypoint.

v1 dispatches to the Douyin implementation. Other platforms are exposed in the
interface so agent workflows can plan for them without pretending support exists.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import douyin_collect  # noqa: E402


PLATFORMS = ("auto", "douyin", "kuaishou", "xiaohongshu")
PLANNED_PLATFORMS = {"kuaishou", "xiaohongshu"}


def detect_platform(text: str) -> str:
    lowered = (text or "").lower()
    if "douyin.com" in lowered or "v.douyin.com" in lowered:
        return "douyin"
    if "kuaishou.com" in lowered or "gifshow.com" in lowered:
        return "kuaishou"
    if "xiaohongshu.com" in lowered or "xhslink.com" in lowered:
        return "xiaohongshu"
    return "unknown"


def build_douyin_argv(args: argparse.Namespace) -> list[str]:
    argv = ["collect", args.input]
    if args.out != "output":
        argv.extend(["--out", args.out])
    if args.model != "medium":
        argv.extend(["--model", args.model])
    if args.limit != 10:
        argv.extend(["--limit", str(args.limit)])
    if args.kind != "auto":
        argv.extend(["--kind", args.kind])
    if args.dry_run:
        argv.append("--dry-run")
    if args.overwrite:
        argv.append("--overwrite")
    if args.ai_polish:
        argv.append("--ai-polish")
    if args.ai_model != douyin_collect.DEFAULT_AI_MODEL:
        argv.extend(["--ai-model", args.ai_model])
    if args.wechat_template != "none":
        argv.extend(["--wechat-template", args.wechat_template])
    if args.frame_count:
        argv.extend(["--frame-count", str(args.frame_count)])
    return argv


def dispatch_collect(args: argparse.Namespace) -> int:
    platform = detect_platform(args.input) if args.platform == "auto" else args.platform
    if platform == "douyin":
        return int(douyin_collect.main(build_douyin_argv(args)))
    if platform in PLANNED_PLATFORMS:
        raise NotImplementedError(f"v1 暂未实现 {platform} 采集；当前可用平台：douyin")
    raise ValueError("无法识别短视频平台；v1 请传入抖音链接，或显式使用 --platform douyin")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="短视频采集、转写与图文整理通用入口")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect", help="采集短视频链接或主页；v1 已支持国内抖音")
    collect.add_argument("input", help="短视频分享文本、视频链接或主页链接")
    collect.add_argument("--platform", default="auto", choices=PLATFORMS, help="平台，默认 auto")
    collect.add_argument("--out", default="output", help="输出目录，默认 output")
    collect.add_argument("--model", default="medium", choices=douyin_collect.WHISPER_MODELS, help="Whisper 模型，默认 medium")
    collect.add_argument("--limit", type=int, default=10, help="主页最多处理条数，默认 10")
    collect.add_argument("--kind", default="auto", choices=("auto", "video", "profile"), help="链接类型，默认 auto")
    collect.add_argument("--dry-run", action="store_true", help="只解析并预览，不下载、不转写、不写文件")
    collect.add_argument("--overwrite", action="store_true", help="覆盖已有媒体、转写和元数据")
    collect.add_argument("--ai-polish", action="store_true", help="调用 OpenAI 对转写做忠实清洗和分段整理")
    collect.add_argument("--ai-model", default=douyin_collect.DEFAULT_AI_MODEL, help="AI 清洗模型")
    collect.add_argument(
        "--wechat-template",
        default="none",
        choices=douyin_collect.WECHAT_TEMPLATES,
        help="可选公众号排版输出：none/plain/warm-card/autumn-warm，默认 none",
    )
    collect.add_argument("--frame-count", type=int, default=0, help="从视频中均匀抽取截图数量，默认 0")
    collect.set_defaults(func=dispatch_collect)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
