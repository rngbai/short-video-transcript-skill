#!/usr/bin/env python3
"""Collect Douyin video metadata and raw transcripts for local knowledge bases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import requests
except ImportError:  # pragma: no cover - exercised by real CLI environments
    requests = None

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover - tqdm is optional at runtime
    tqdm = None


VIDEO_API = "https://api.bugpk.com/api/douyin"
PROFILE_API = "https://api.bugpk.com/api/dyzy"
DOUYIN_URL_RE = re.compile(r"https?://(?:v|www)\.douyin\.com/[^\s，。；、]+", re.IGNORECASE)
INVALID_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
TRAILING_URL_CHARS = " \t\r\n，。；、：:；;,.!?！？)]}）】》\"'`"
WHISPER_MODELS = (
    "tiny",
    "base",
    "small",
    "medium",
    "large",
    "large-v1",
    "large-v2",
    "large-v3",
    "large-v3-turbo",
    "turbo",
)
DEFAULT_AI_MODEL = "gpt-5.5"
WECHAT_TEMPLATES = ("none", "plain", "warm-card", "autumn-warm")
WARM_CARD_TEMPLATE_ALIASES = {"warm-card", "autumn-warm"}


def extract_douyin_url(text: str) -> str | None:
    """Extract the first Douyin URL from a pasted share message."""
    if not text:
        return None
    match = DOUYIN_URL_RE.search(text)
    if not match:
        return None
    return match.group(0).rstrip(TRAILING_URL_CHARS)


def safe_filename(value: Any, fallback: str = "untitled", max_length: int = 80) -> str:
    """Return a cross-platform safe filename stem."""
    text = str(value or "").strip()
    text = INVALID_FILENAME_RE.sub("_", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"_+", "_", text)
    text = text.strip(" ._")
    if not text:
        text = fallback
    if text.upper() in RESERVED_WINDOWS_NAMES:
        text = f"{text}_"
    if len(text) > max_length:
        text = text[:max_length].rstrip(" ._")
    return text or fallback


def extract_aweme_id(value: str | None) -> str:
    if not value:
        return ""
    patterns = [
        r"/video/(\d+)",
        r"/note/(\d+)",
        r"(?:aweme_id|item_id|modal_id|id)=(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, value)
        if match:
            return match.group(1)
    return ""


def first_video_backup_url(data: dict[str, Any]) -> str:
    backups = data.get("video_backup") or []
    if isinstance(backups, list):
        for item in backups:
            if isinstance(item, dict) and item.get("url"):
                return str(item["url"])
    return ""


def empty_item(source_url: str) -> dict[str, Any]:
    return {
        "platform": "douyin",
        "provider": "bugpk",
        "aweme_id": "",
        "title": "",
        "desc": "",
        "author_name": "",
        "author_id": "",
        "share_url": source_url,
        "create_time": "",
        "duration": "",
        "cover_url": "",
        "video_url": "",
        "audio_url": "",
        "statistics": {},
        "hashtags": [],
        "local_video_path": "",
        "local_audio_path": "",
        "local_frame_paths": [],
        "raw_transcript_text": "",
        "transcript_text": "",
        "ai_polished_text": "",
    }


def stable_unknown_id(item: dict[str, Any]) -> str:
    seed = "|".join(
        str(item.get(key, "")) for key in ("share_url", "title", "desc", "video_url", "audio_url")
    )
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"unknown_{digest}"


def normalize_video_payload(payload: dict[str, Any], source_url: str) -> list[dict[str, Any]]:
    if payload.get("code") != 200:
        raise ValueError(f"BugPk video API error: {payload.get('msg', 'unknown error')}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("BugPk video API returned an unexpected payload shape")

    author = data.get("author") if isinstance(data.get("author"), dict) else {}
    music = data.get("music") if isinstance(data.get("music"), dict) else {}
    item = empty_item(source_url)
    item.update(
        {
            "aweme_id": str(data.get("aweme_id") or extract_aweme_id(data.get("share_url")) or extract_aweme_id(source_url)),
            "title": str(data.get("title") or data.get("desc") or ""),
            "desc": str(data.get("desc") or data.get("title") or ""),
            "author_name": str(author.get("name") or data.get("author_name") or "unknown"),
            "author_id": str(author.get("id") or data.get("author_id") or ""),
            "share_url": str(data.get("share_url") or source_url),
            "create_time": str(data.get("create_time") or ""),
            "duration": data.get("duration") or "",
            "cover_url": str(data.get("cover") or ""),
            "video_url": str(data.get("url") or first_video_backup_url(data) or ""),
            "audio_url": str(music.get("url") or data.get("music_url") or ""),
            "statistics": data.get("statistics") if isinstance(data.get("statistics"), dict) else {},
            "hashtags": data.get("hashtags") if isinstance(data.get("hashtags"), list) else [],
        }
    )
    if not item["aweme_id"]:
        item["aweme_id"] = stable_unknown_id(item)
    return [item]


def normalize_profile_payload(payload: dict[str, Any], source_url: str, limit: int = 10) -> list[dict[str, Any]]:
    if payload.get("code") != 200:
        raise ValueError(f"BugPk profile API error: {payload.get('msg', 'unknown error')}")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("BugPk profile API returned an unexpected payload shape")

    items: list[dict[str, Any]] = []
    for raw in data[: max(limit, 0)]:
        if not isinstance(raw, dict):
            continue
        item = empty_item(source_url)
        share_url = str(raw.get("share_url") or "")
        item.update(
            {
                "aweme_id": str(raw.get("aweme_id") or extract_aweme_id(share_url)),
                "title": str(raw.get("title") or raw.get("desc") or ""),
                "desc": str(raw.get("desc") or raw.get("title") or ""),
                "author_name": str(raw.get("author") or raw.get("author_name") or "unknown"),
                "author_id": str(raw.get("author_uid") or raw.get("author_id") or ""),
                "share_url": share_url or source_url,
                "create_time": str(raw.get("create_time") or ""),
                "duration": raw.get("duration") or "",
                "cover_url": str(raw.get("cover") or ""),
                "video_url": str(raw.get("url") or first_video_backup_url(raw) or ""),
                "audio_url": str(raw.get("music_url") or raw.get("audio_url") or ""),
                "statistics": raw.get("statistics") if isinstance(raw.get("statistics"), dict) else {},
                "hashtags": raw.get("hashtags") if isinstance(raw.get("hashtags"), list) else [],
            }
        )
        if not item["aweme_id"]:
            item["aweme_id"] = stable_unknown_id(item)
        items.append(item)
    return items


def require_requests():
    if requests is None:
        raise RuntimeError("缺少 requests，请先运行: pip install -r scripts/requirements.txt")
    return requests


def http_get_json(url: str, params: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
    client = require_requests()
    response = client.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def resolve_redirect(url: str, timeout: int = 15) -> str:
    client = require_requests()
    try:
        response = client.get(url, allow_redirects=True, timeout=timeout)
        return response.url or url
    except Exception:
        return url


def guess_kind(url: str, explicit_kind: str) -> str:
    if explicit_kind != "auto":
        return explicit_kind
    parsed = urlparse(url)
    if "/user/" in parsed.path:
        return "profile"
    return "video"


def fetch_items(input_text: str, kind: str = "auto", limit: int = 10) -> tuple[str, list[dict[str, Any]], str]:
    url = extract_douyin_url(input_text) or input_text.strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("没有找到有效的抖音链接")

    resolved_url = resolve_redirect(url) if "v.douyin.com" in url else url
    selected_kind = guess_kind(resolved_url, kind)

    if selected_kind == "profile":
        payload = http_get_json(PROFILE_API, {"url": resolved_url, "count": limit}, timeout=300)
        return selected_kind, normalize_profile_payload(payload, resolved_url, limit=limit), resolved_url

    try:
        payload = http_get_json(VIDEO_API, {"url": url}, timeout=60)
        return "video", normalize_video_payload(payload, resolved_url), resolved_url
    except Exception:
        if kind != "auto":
            raise
        payload = http_get_json(PROFILE_API, {"url": resolved_url, "count": limit}, timeout=300)
        return "profile", normalize_profile_payload(payload, resolved_url, limit=limit), resolved_url


def ensure_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("未在 PATH 中找到 ffmpeg，请先安装 FFmpeg 并加入 PATH")


def build_ffmpeg_extract_command(video_path: Path, audio_path: Path, overwrite: bool = False) -> list[str]:
    # The caller skips existing files unless overwrite=True; -y keeps ffmpeg non-interactive.
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "libmp3lame",
        "-q:a",
        "2",
        str(audio_path),
    ]


def build_ffmpeg_frame_command(video_path: Path, frame_path: Path, timestamp_seconds: float) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-ss",
        f"{max(timestamp_seconds, 0):.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(frame_path),
    ]


def parse_content_range_total(value: str | None) -> int:
    if not value:
        return 0
    match = re.search(r"/(\d+)$", value)
    return int(match.group(1)) if match else 0


def run_subprocess_capture(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def iter_content_with_progress(response: Any, destination: Path, append: bool = False, initial: int = 0):
    total_size = parse_content_range_total(response.headers.get("content-range"))
    if not total_size:
        content_length = int(response.headers.get("content-length", 0) or 0)
        total_size = initial + content_length if append else content_length
    iterator = response.iter_content(chunk_size=1024 * 256)
    mode = "ab" if append else "wb"
    with destination.open(mode) as handle:
        if tqdm is None:
            for chunk in iterator:
                if chunk:
                    handle.write(chunk)
            return
        with tqdm(total=total_size or None, initial=initial if append else 0, unit="B", unit_scale=True) as bar:
            for chunk in iterator:
                if chunk:
                    handle.write(chunk)
                    bar.update(len(chunk))


def download_file(url: str, destination: Path, overwrite: bool = False, timeout: int = 120) -> Path:
    if not url:
        raise ValueError(f"下载地址为空: {destination}")
    if destination.exists() and destination.stat().st_size > 0 and not overwrite:
        return destination

    client = require_requests()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".part")
    resume_from = 0
    headers: dict[str, str] = {}
    if temp_path.exists() and temp_path.stat().st_size > 0 and not overwrite:
        resume_from = temp_path.stat().st_size
        headers["Range"] = f"bytes={resume_from}-"

    response = client.get(url, stream=True, timeout=timeout, headers=headers or None)
    response.raise_for_status()
    append = bool(resume_from and response.status_code == 206)
    if resume_from and response.status_code != 206:
        resume_from = 0
    iter_content_with_progress(response, temp_path, append=append, initial=resume_from)
    os.replace(temp_path, destination)
    return destination


def extract_audio_from_video(video_path: Path, audio_path: Path, overwrite: bool = False) -> Path:
    if audio_path.exists() and audio_path.stat().st_size > 0 and not overwrite:
        return audio_path
    ensure_ffmpeg()
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_ffmpeg_extract_command(video_path, audio_path, overwrite=overwrite)
    result = run_subprocess_capture(command)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(f"FFmpeg 抽音频失败: {stderr[-2000:]}")
    return audio_path


def duration_to_seconds(value: Any) -> float:
    if value in (None, ""):
        return 0
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip()
        if re.match(r"^\d+:\d{2}(?::\d{2})?$", text):
            parts = [float(part) for part in text.split(":")]
            if len(parts) == 2:
                return parts[0] * 60 + parts[1]
            if len(parts) == 3:
                return parts[0] * 3600 + parts[1] * 60 + parts[2]
        try:
            number = float(text)
        except ValueError:
            return 0
    return number / 1000 if number > 1000 else number


def frame_timestamps(duration: Any, count: int) -> list[float]:
    if count <= 0:
        return []
    seconds = duration_to_seconds(duration)
    if seconds <= 0:
        return [float(5 + index * 10) for index in range(count)]
    start = seconds * 0.12
    end = seconds * 0.88
    if count == 1:
        return [seconds * 0.5]
    step = (end - start) / (count - 1)
    return [start + step * index for index in range(count)]


def extract_video_frames(
    video_path: Path,
    frames_dir: Path,
    duration: Any,
    count: int = 0,
    overwrite: bool = False,
) -> list[Path]:
    if count <= 0:
        return []
    ensure_ffmpeg()
    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_paths: list[Path] = []
    for index, timestamp in enumerate(frame_timestamps(duration, count), start=1):
        frame_path = frames_dir / f"frame_{index:02d}.jpg"
        if frame_path.exists() and frame_path.stat().st_size > 0 and not overwrite:
            frame_paths.append(frame_path)
            continue
        command = build_ffmpeg_frame_command(video_path, frame_path, timestamp)
        result = run_subprocess_capture(command)
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise RuntimeError(f"FFmpeg 抽帧失败: {stderr[-2000:]}")
        frame_paths.append(frame_path)
    return frame_paths


def parse_timecode_list(values: list[str]) -> list[float]:
    timestamps: list[float] = []
    for value in values:
        for token in str(value).split(","):
            token = token.strip()
            if not token:
                continue
            seconds = duration_to_seconds(token)
            if seconds < 0:
                raise ValueError(f"时间点不能为负数: {token}")
            timestamps.append(seconds)
    if not timestamps:
        raise ValueError("至少需要提供一个抽帧时间点")
    return timestamps


def extract_video_frames_at_timestamps(
    video_path: Path,
    frames_dir: Path,
    timestamps: list[float],
    prefix: str = "article",
    overwrite: bool = False,
) -> list[Path]:
    ensure_ffmpeg()
    frames_dir.mkdir(parents=True, exist_ok=True)
    safe_prefix = safe_filename(prefix, fallback="article", max_length=48)
    frame_paths: list[Path] = []
    for index, timestamp in enumerate(timestamps, start=1):
        frame_path = frames_dir / f"{safe_prefix}_{index:02d}.jpg"
        if frame_path.exists() and frame_path.stat().st_size > 0 and not overwrite:
            frame_paths.append(frame_path)
            continue
        result = run_subprocess_capture(build_ffmpeg_frame_command(video_path, frame_path, timestamp))
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise RuntimeError(f"FFmpeg 抽帧失败: {stderr[-2000:]}")
        frame_paths.append(frame_path)
    return frame_paths


def build_ffmpeg_contact_sheet_command(frame_pattern: Path, output_path: Path, count: int) -> list[str]:
    columns = 2 if count > 1 else 1
    rows = max(1, (count + columns - 1) // columns)
    return [
        "ffmpeg",
        "-y",
        "-framerate",
        "1",
        "-i",
        str(frame_pattern),
        "-vf",
        f"scale=320:-1,tile={columns}x{rows}:padding=12:margin=12:color=white",
        "-frames:v",
        "1",
        "-update",
        "1",
        str(output_path),
    ]


def write_contact_sheet(frames_dir: Path, prefix: str, count: int, overwrite: bool = False) -> Path:
    safe_prefix = safe_filename(prefix, fallback="article", max_length=48)
    output_path = frames_dir / f"{safe_prefix}_contact_sheet.jpg"
    if output_path.exists() and output_path.stat().st_size > 0 and not overwrite:
        return output_path
    ensure_ffmpeg()
    pattern = frames_dir / f"{safe_prefix}_%02d.jpg"
    result = run_subprocess_capture(build_ffmpeg_contact_sheet_command(pattern, output_path, count))
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(f"FFmpeg 生成截图总览失败: {stderr[-2000:]}")
    return output_path


def has_sentence_punctuation(text: str) -> bool:
    return bool(re.search(r"[。！？.!?]", text))


def ensure_terminal_punctuation(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    if re.search(r"[。！？.!?]$", text):
        return text
    return f"{text}。"


def split_long_unpunctuated_text(text: str, max_chars: int = 32) -> list[str]:
    """Split plain Chinese transcript text into readable chunks without changing words."""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    markers = [
        "但是",
        "不过",
        "然后",
        "所以",
        "因为",
        "对 ",
        "我很",
        "这边",
        "这里",
        "我们",
        "大家",
        "你只要",
        "没有问题",
        "非常满意",
    ]
    for marker in markers:
        text = text.replace(marker, f"。{marker}")
    text = text.strip("。")

    chunks: list[str] = []
    for part in [p.strip() for p in text.split("。") if p.strip()]:
        while len(part) > max_chars:
            split_at = max(
                part.rfind("，", 0, max_chars + 1),
                part.rfind(" ", 0, max_chars + 1),
            )
            if split_at <= 0:
                split_at = max_chars
            chunks.append(part[:split_at].strip(" ，"))
            part = part[split_at:].strip(" ，")
        if part:
            chunks.append(part)
    return chunks


def restore_chinese_punctuation(text: str, segments: list[dict[str, Any]] | None = None) -> str:
    """Restore light Chinese punctuation using Whisper segments and safe heuristics."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if text and has_sentence_punctuation(text):
        return text

    segment_texts = []
    for segment in segments or []:
        if isinstance(segment, dict):
            segment_text = re.sub(r"\s+", " ", str(segment.get("text") or "")).strip()
            if segment_text:
                segment_texts.append(ensure_terminal_punctuation(segment_text))
    if segment_texts:
        return "".join(segment_texts)

    chunks = split_long_unpunctuated_text(text)
    return "".join(ensure_terminal_punctuation(chunk) for chunk in chunks)


def simplify_chinese(text: str) -> str:
    try:
        from zhconv import convert

        return convert(text, "zh-cn")
    except ImportError:
        return text


def build_whisper_initial_prompt(item: dict[str, Any] | None = None) -> str:
    item = item or {}
    parts = [
        "以下是中文普通话短视频音频，请按中文语境准确转写。",
        "注意金额、时间、地点、店名、人名、平台名等关键词。",
    ]
    if item.get("title"):
        parts.append(f"视频标题：{item['title']}")
    if item.get("desc"):
        parts.append(f"视频简介：{item['desc']}")
    if item.get("author_name"):
        parts.append(f"作者：{item['author_name']}")
    return "\n".join(parts)


def build_whisper_transcribe_options(initial_prompt: str = "") -> dict[str, Any]:
    return {
        "language": "zh",
        "task": "transcribe",
        "temperature": 0,
        "initial_prompt": initial_prompt,
        "condition_on_previous_text": True,
        "fp16": False,
    }


def transcribe_audio(audio_path: Path, model_name: str, context_item: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        import whisper
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise RuntimeError("缺少 openai-whisper，请先运行: pip install -r scripts/requirements.txt") from exc

    model = whisper.load_model(model_name)
    result = model.transcribe(
        str(audio_path),
        **build_whisper_transcribe_options(build_whisper_initial_prompt(context_item)),
    )
    raw_text = simplify_chinese(str(result.get("text", "")).strip())
    segments = result.get("segments") if isinstance(result.get("segments"), list) else []
    simplified_segments = []
    for segment in segments:
        if isinstance(segment, dict):
            segment_copy = dict(segment)
            segment_copy["text"] = simplify_chinese(str(segment_copy.get("text") or ""))
            simplified_segments.append(segment_copy)
    return {
        "raw_text": raw_text,
        "text": restore_chinese_punctuation(raw_text, simplified_segments),
        "segments": simplified_segments,
    }


def build_ai_polish_prompt(item: dict[str, Any]) -> str:
    """Build a constrained prompt for transcript cleanup, not plagiarism."""
    return f"""请把下面的抖音视频转写整理成适合个人知识库保存的中文学习笔记。

要求：
- 只做标点修复、错别字轻度校正、分段和小标题整理。
- 不要伪装成原创，不要改写成营销文，不要隐藏来源。
- 不要编造视频里没有的信息；不确定的词保留原样或用“[疑似]”标记。
- 保留说话人的原意，尽量不要改变事实、数字、时间、地点。
- 输出 Markdown，只输出整理后的正文。

来源信息：
- 标题：{item.get('title') or ''}
- 作者：{item.get('author_name') or ''}
- 链接：{item.get('share_url') or ''}
- 原始文案：{item.get('desc') or ''}

转写文本：
{item.get('transcript_text') or item.get('raw_transcript_text') or ''}
"""


def ai_polish_transcript(item: dict[str, Any], model_name: str = DEFAULT_AI_MODEL) -> str:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - depends on local env
        raise RuntimeError("缺少 openai，请先运行: pip install -r scripts/requirements.txt") from exc

    client_kwargs: dict[str, str] = {}
    if os.environ.get("OPENAI_BASE_URL"):
        client_kwargs["base_url"] = os.environ["OPENAI_BASE_URL"]

    client = OpenAI(**client_kwargs)
    response = client.responses.create(
        model=model_name,
        instructions="你是中文转写清洗助手，只做忠实整理，不伪装原创，不编造信息。",
        input=build_ai_polish_prompt(item),
    )
    text = str(getattr(response, "output_text", "") or "").strip()
    if not text:
        raise RuntimeError("AI 清洗返回为空")
    return text


def item_output_dir(output_root: Path, item: dict[str, Any]) -> Path:
    author = safe_filename(item.get("author_name"), fallback="unknown_author")
    aweme_id = safe_filename(item.get("aweme_id"), fallback=stable_unknown_id(item), max_length=60)
    return output_root / author / aweme_id


def relative_or_empty(path: Path | None, root: Path) -> str:
    if path is None:
        return ""
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def html_escape(value: Any) -> str:
    text = str(value or "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def html_attr(value: Any) -> str:
    return html_escape(value).replace("'", "&#39;")


def write_transcript_markdown(path: Path, item: dict[str, Any]) -> None:
    content = [
        f"# {item.get('title') or item.get('desc') or item.get('aweme_id')}",
        "",
        f"- 作者：{item.get('author_name') or ''}",
        f"- 平台链接：{item.get('share_url') or ''}",
        f"- 发布时间：{item.get('create_time') or ''}",
        f"- 时长：{item.get('duration') or ''}",
        f"- 视频文件：{item.get('local_video_path') or ''}",
        f"- 音频文件：{item.get('local_audio_path') or ''}",
        "",
        "## 原始文案",
        "",
        item.get("desc") or "",
        "",
        "## 转写文本（已恢复标点）",
        "",
        item.get("transcript_text") or "",
        "",
    ]
    if item.get("ai_polished_text"):
        content.extend(
            [
                "## AI 清洗版",
                "",
                item.get("ai_polished_text") or "",
                "",
            ]
        )
    if item.get("raw_transcript_text") and item.get("raw_transcript_text") != item.get("transcript_text"):
        content.extend(
            [
                "## 原始转写（未加标点）",
                "",
                item.get("raw_transcript_text") or "",
                "",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(content), encoding="utf-8")


def strip_review_markers(text: str) -> str:
    """Remove review markers from publishable copy while keeping conservative text."""
    def replace_marker(match: re.Match[str]) -> str:
        content = match.group(1).strip()
        if "/" in content:
            return content.split("/", 1)[0].strip()
        return content

    text = re.sub(r"\[疑似[:：]([^\]]+)\]", replace_marker, text)
    text = text.replace("，", "，")
    return text


def video_copy_text(item: dict[str, Any], paragraph_max_chars: int = 220) -> str:
    """Return the plain extracted video copy, suitable for downstream editors."""
    text = str(item.get("transcript_text") or item.get("desc") or item.get("raw_transcript_text") or "").strip()
    text = strip_review_markers(text)
    text = re.sub(r"\s+", " ", text)
    if not text:
        return ""

    sentences = re.findall(r"[^。！？!?]+[。！？!?]?", text)
    paragraphs: list[str] = []
    current = ""
    for sentence in sentences:
        cleaned = sentence.strip()
        if not cleaned:
            continue
        cleaned = ensure_terminal_punctuation(cleaned)
        if current and len(current) + len(cleaned) > paragraph_max_chars:
            paragraphs.append(current)
            current = cleaned
        else:
            current = f"{current}{cleaned}" if current else cleaned
    if current:
        paragraphs.append(current)
    return "\n\n".join(paragraphs)


def split_text_paragraphs(text: str, paragraph_max_chars: int = 360) -> str:
    """Split already-clean copy into readable long-form paragraphs."""
    text = re.sub(r"\s+", " ", str(text or "").strip())
    if not text:
        return ""
    sentences = re.findall(r"[^。！？!?]+[。！？!?]?", text)
    paragraphs: list[str] = []
    current = ""
    for sentence in sentences:
        cleaned = sentence.strip()
        if not cleaned:
            continue
        cleaned = ensure_terminal_punctuation(cleaned)
        if current and len(current) + len(cleaned) > paragraph_max_chars:
            paragraphs.append(current)
            current = cleaned
        else:
            current = f"{current}{cleaned}" if current else cleaned
    if current:
        paragraphs.append(current)
    return "\n\n".join(paragraphs)


def clean_wechat_title(value: Any) -> str:
    """Remove Douyin hashtag tails from WeChat article titles."""
    title = str(value or "").strip()
    title = re.sub(r"\s*#[^\s#]+", "", title).strip()
    return title or "视频文案"


def write_copy_outputs(item_dir: Path, item: dict[str, Any]) -> dict[str, str]:
    """Write pure video copy files for publishing or later公众号 workflows."""
    item_dir.mkdir(parents=True, exist_ok=True)
    copy_text = video_copy_text(item)
    copy_txt_path = item_dir / "copy.txt"
    copy_md_path = item_dir / "copy.md"

    copy_txt_path.write_text(copy_text, encoding="utf-8")

    title = item.get("title") or item.get("desc") or item.get("aweme_id") or "视频文案"
    md_content = [
        f"# {title}",
        "",
        f"- 来源：{item.get('author_name') or ''}",
        f"- 平台链接：{item.get('share_url') or ''}",
        f"- 视频 ID：{item.get('aweme_id') or ''}",
        "",
        "## 视频文案",
        "",
        copy_text,
        "",
    ]
    copy_md_path.write_text("\n".join(md_content), encoding="utf-8")

    return {
        "copy_md": str(copy_md_path.relative_to(item_dir)),
        "copy_txt": str(copy_txt_path.relative_to(item_dir)),
    }


def best_publish_copy(item_dir: Path, item: dict[str, Any]) -> str:
    """Prefer agent-reviewed copy when present; otherwise use deterministic machine copy."""
    copy_zh = item_dir / "copy.zh.txt"
    if copy_zh.exists():
        text = copy_zh.read_text(encoding="utf-8").strip()
        if text:
            return text
    return video_copy_text(item)


def build_wechat_markdown(item_dir: Path, item: dict[str, Any]) -> str:
    """Build a WeChat-friendly Markdown draft without pretending it is original writing."""
    title = clean_wechat_title(item.get("title") or item.get("desc") or item.get("aweme_id") or "视频文案")
    copy_text = split_text_paragraphs(best_publish_copy(item_dir, item), paragraph_max_chars=360)
    frame_paths = [
        str(path).replace("\\", "/")
        for path in (item.get("local_frame_paths") or [])
        if str(path).strip()
    ]

    lines = [
        f"# {title}",
        "",
        "> 把视频里的重要内容整理成更适合阅读的文字。",
    ]
    if frame_paths:
        lines.extend(["", "## 视频截图", ""])
        for index, frame_path in enumerate(frame_paths, start=1):
            lines.extend([f"![视频截图 {index}]({frame_path})", ""])
    lines.extend(["", "## 视频文案", "", copy_text, ""])

    return "\n".join(lines)


def markdown_inline_to_html(text: str) -> str:
    """Render a small safe Markdown inline subset for WeChat card output."""
    escaped = html_escape(text)
    escaped = re.sub(r"`([^`]+)`", r"<code style=\"background-color:#fef4e7;color:#c06b4d;padding:1px 4px;border-radius:4px;\">\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong style=\"color:#c06b4d;\">\1</strong>", escaped)
    escaped = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda match: (
            f'<a href="{html_attr(match.group(2))}" '
            'style="color:#c06b4d;text-decoration:underline;word-break:break-all;">'
            f"{match.group(1)}</a>"
        ),
        escaped,
    )
    return escaped


def parse_wechat_markdown(markdown_text: str) -> tuple[str, list[str], list[dict[str, Any]]]:
    """Parse enough Markdown structure for card rendering: H1-H3, paragraphs, quotes, lists."""
    title = "公众号整理稿"
    intro: list[str] = []
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    paragraph: list[str] = []
    list_items: list[str] = []
    list_ordered = False
    quote_lines: list[str] = []

    def ensure_section() -> dict[str, Any]:
        nonlocal current
        if current is None:
            current = {"title": "", "blocks": []}
            sections.append(current)
        return current

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            ensure_section()["blocks"].append({"type": "p", "text": " ".join(paragraph).strip()})
            paragraph = []

    def flush_list() -> None:
        nonlocal list_items
        if list_items:
            ensure_section()["blocks"].append(
                {"type": "ol" if list_ordered else "ul", "items": list_items[:]}
            )
            list_items = []

    def flush_quote() -> None:
        nonlocal quote_lines
        if quote_lines:
            target = intro if current is None else ensure_section()["blocks"]
            quote_text = "\n".join(quote_lines).strip()
            if target is intro:
                intro.append(quote_text)
            else:
                target.append({"type": "quote", "text": quote_text})
            quote_lines = []

    def flush_all() -> None:
        flush_paragraph()
        flush_list()
        flush_quote()

    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if not stripped:
            flush_all()
            continue
        if stripped == "---":
            flush_all()
            ensure_section()["blocks"].append({"type": "hr"})
            continue
        if stripped.startswith("### "):
            flush_all()
            ensure_section()["blocks"].append({"type": "subheading", "text": stripped[4:].strip()})
            continue
        if stripped.startswith("# "):
            flush_all()
            title = stripped[2:].strip() or title
            continue
        if stripped.startswith("## "):
            flush_all()
            current = {"title": stripped[3:].strip(), "blocks": []}
            sections.append(current)
            continue
        if stripped.startswith(">"):
            flush_paragraph()
            flush_list()
            quote_lines.append(stripped.lstrip(">").strip())
            continue

        image = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", stripped)
        if image:
            flush_all()
            ensure_section()["blocks"].append(
                {"type": "image", "alt": image.group(1).strip(), "src": image.group(2).strip()}
            )
            continue

        unordered = re.match(r"^[-*]\s+(.+)$", stripped)
        ordered = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if unordered or ordered:
            flush_paragraph()
            flush_quote()
            item_text = (unordered or ordered).group(1).strip()
            if list_items and list_ordered != bool(ordered):
                flush_list()
            list_ordered = bool(ordered)
            list_items.append(item_text)
            continue

        flush_list()
        flush_quote()
        paragraph.append(stripped)

    flush_all()
    return title, intro, sections


def paragraph_html(text: str) -> str:
    return (
        '<p style="margin:0 0 14px 0;font-size:16px;line-height:1.75;'
        'color:#4a413d;word-break:break-word;overflow-wrap:anywhere;">'
        f"{markdown_inline_to_html(text)}</p>"
    )


def quote_html(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    content = "<br>".join(markdown_inline_to_html(line) for line in lines)
    return (
        '<blockquote style="margin:0 0 16px 0;padding:16px 18px;background-color:#fef4e7;'
        'border-left:5px solid #d97758;box-shadow:inset 0 0 15px rgba(217,119,88,0.1);">'
        '<p style="margin:0;font-size:16px;line-height:1.75;color:#4a413d;'
        f'word-break:break-word;overflow-wrap:anywhere;">{content}</p></blockquote>'
    )


def subheading_html(text: str) -> str:
    return (
        '<h3 style="margin:24px 0 12px 0;padding:0 0 0 12px;border-left:4px solid #d97758;'
        'font-size:18px;line-height:1.45;color:#c06b4d;font-weight:800;'
        'word-break:break-word;overflow-wrap:anywhere;">'
        f"{markdown_inline_to_html(text)}</h3>"
    )


def list_html(block: dict[str, Any]) -> str:
    tag = "ol" if block["type"] == "ol" else "ul"
    items = "".join(
        '<li style="margin:0 0 8px 0;color:#4a413d;word-break:break-word;overflow-wrap:anywhere;">'
        f"{markdown_inline_to_html(item)}</li>"
        for item in block.get("items", [])
    )
    return (
        f'<{tag} style="margin:0 0 14px 0;padding-left:22px;color:#4a413d;'
        f'font-size:16px;line-height:1.75;">{items}</{tag}>'
    )


def image_html(block: dict[str, Any]) -> str:
    src = html_attr(block.get("src") or "")
    alt = html_attr(block.get("alt") or "视频截图")
    return (
        '<figure style="margin:0 0 18px 0;padding:4px;background:#ffffff;border-radius:14px;'
        'box-shadow:0 4px 12px rgba(217,119,88,0.15);">'
        f'<img src="{src}" alt="{alt}" style="display:block;width:100%;max-width:100%;'
        'border-radius:12px;box-sizing:border-box;">'
        f'<figcaption style="margin:8px 2px 2px 2px;font-size:13px;line-height:1.6;'
        f'color:#8a7a72;text-align:center;">{alt}</figcaption></figure>'
    )


def render_warm_card_html(markdown_text: str) -> str:
    """Render warm-card style HTML with only inline styles for WeChat compatibility."""
    title, intro, sections = parse_wechat_markdown(markdown_text)
    section_style = (
        "max-width:800px;width:100%;box-sizing:border-box;margin:0 auto 40px auto;"
        "padding:25px;background-color:#ffffff;"
        "background-image:linear-gradient(rgba(0,0,0,0.02) 1px,transparent 1px),"
        "linear-gradient(90deg,rgba(0,0,0,0.02) 1px,transparent 1px);"
        "background-size:20px 20px;border:1px solid rgba(0,0,0,0.05);"
        "box-shadow:0 10px 30px rgba(0,0,0,0.04),0 0 15px rgba(217,119,88,0.4);"
        "border-radius:18px;"
    )
    blocks = [
        "<!doctype html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{html_escape(title)}</title>",
        "</head>",
        '<body style="margin:0;padding:0;">',
        (
            '<div style="background-color:#faf9f5;padding:40px 10px;box-sizing:border-box;'
            "width:100%;overflow:hidden;word-break:break-word;overflow-wrap:anywhere;"
            "letter-spacing:0.5px;font-family:'Inter',-apple-system,BlinkMacSystemFont,"
            "'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;color:#4a413d;\">"
        ),
        f'<section style="{section_style}">',
        (
            '<h1 style="margin:0 0 18px 0;padding:16px 20px 14px 20px;border-bottom:1px dashed '
            'rgba(74,65,61,0.3);font-size:24px;line-height:1.35;color:#4a413d;text-align:center;'
            f'font-weight:800;word-break:break-word;overflow-wrap:anywhere;">{html_escape(title)}</h1>'
        ),
    ]
    if intro:
        blocks.append(quote_html("\n".join(intro)))
    blocks.append("</section>")

    for section in sections:
        section_title = str(section.get("title") or "").strip()
        section_blocks = section.get("blocks") or []
        blocks.append(f'<section style="{section_style}">')
        if section_title:
            blocks.append(
                '<h2 style="margin:0 0 20px 0;padding-bottom:12px;border-bottom:1px dashed '
                'rgba(74,65,61,0.3);font-size:22px;line-height:1.4;font-weight:800;'
                'word-break:break-word;overflow-wrap:anywhere;">'
                '<span style="color:#d97758;text-shadow:0 0 12px rgba(217,119,88,0.5);">▶</span> '
                f'<span style="color:#d97758;">{html_escape(section_title)}</span></h2>'
            )
        for block in section_blocks:
            block_type = block.get("type")
            if block_type == "p":
                blocks.append(paragraph_html(str(block.get("text") or "")))
            elif block_type == "subheading":
                blocks.append(subheading_html(str(block.get("text") or "")))
            elif block_type == "quote":
                blocks.append(quote_html(str(block.get("text") or "")))
            elif block_type in {"ul", "ol"}:
                blocks.append(list_html(block))
            elif block_type == "image":
                blocks.append(image_html(block))
            elif block_type == "hr":
                blocks.append('<hr style="border:none;height:1px;background-color:rgba(74,65,61,0.1);margin:24px 0;">')
        blocks.append("</section>")

    blocks.extend(["</div>", "</body>", "</html>"])
    return "\n".join(blocks)


def write_wechat_outputs(item_dir: Path, item: dict[str, Any], template: str = "none") -> dict[str, str]:
    """Write optional WeChat-friendly Markdown/HTML output."""
    if template == "none":
        return {}

    markdown_text = build_wechat_markdown(item_dir, item)
    md_path = item_dir / "wechat.md"
    md_path.write_text(markdown_text, encoding="utf-8")
    outputs = {"wechat_md": str(md_path.relative_to(item_dir))}

    if template in WARM_CARD_TEMPLATE_ALIASES:
        html_path = item_dir / "wechat-warm-card.html"
        html_path.write_text(render_warm_card_html(markdown_text), encoding="utf-8")
        outputs["wechat_html"] = str(html_path.relative_to(item_dir))

    return outputs


def load_existing_transcript(item_dir: Path) -> str:
    return str(load_existing_metadata(item_dir).get("transcript_text") or "")


def load_existing_metadata(item_dir: Path) -> dict[str, Any]:
    metadata_path = item_dir / "metadata.json"
    if not metadata_path.exists():
        return {}
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        return metadata if isinstance(metadata, dict) else {}
    except Exception:
        return {}


def collect_items(
    items: list[dict[str, Any]],
    output_root: Path,
    model_name: str = "medium",
    ai_polish: bool = False,
    ai_model: str = DEFAULT_AI_MODEL,
    wechat_template: str = "none",
    frame_count: int = 0,
    overwrite: bool = False,
) -> list[dict[str, Any]]:
    output_root.mkdir(parents=True, exist_ok=True)
    processed: list[dict[str, Any]] = []

    for index, item in enumerate(items, start=1):
        item_dir = item_output_dir(output_root, item)
        media_dir = item_dir / "media"
        video_path = media_dir / "video.mp4"
        audio_path = media_dir / "audio.mp3"

        print(f"[{index}/{len(items)}] 处理: {item.get('title') or item.get('desc') or item.get('aweme_id')}")

        local_video: Path | None = None
        local_audio: Path | None = None
        if item.get("video_url"):
            print("  下载视频...")
            local_video = download_file(str(item["video_url"]), video_path, overwrite=overwrite)
            item["local_video_path"] = relative_or_empty(local_video, output_root)

        if local_video is not None and frame_count > 0:
            print(f"  抽取视频截图: {frame_count} 张...")
            frames = extract_video_frames(
                local_video,
                media_dir / "frames",
                item.get("duration"),
                count=frame_count,
                overwrite=overwrite,
            )
            item["local_frame_paths"] = [relative_or_empty(frame, item_dir) for frame in frames]

        if item.get("audio_url"):
            print("  下载音频...")
            local_audio = download_file(str(item["audio_url"]), audio_path, overwrite=overwrite)
        elif local_video is not None:
            print("  音频直链为空，使用 FFmpeg 从视频抽音频...")
            local_audio = extract_audio_from_video(local_video, audio_path, overwrite=overwrite)
        else:
            raise RuntimeError(f"视频 {item.get('aweme_id')} 没有可用的视频或音频地址")

        item["local_audio_path"] = relative_or_empty(local_audio, output_root)

        existing_metadata = {} if overwrite else load_existing_metadata(item_dir)
        existing_text = str(existing_metadata.get("transcript_text") or "")
        if existing_text:
            print("  已有转写，跳过 Whisper。")
            for key in (
                "raw_transcript_text",
                "transcript_text",
                "transcript_segments",
                "ai_polished_text",
                "local_video_path",
                "local_audio_path",
                "copy_md_path",
                "copy_txt_path",
                "copy_zh_md_path",
                "copy_zh_txt_path",
                "review_md_path",
                "wechat_md_path",
                "wechat_html_path",
                "local_frame_paths",
            ):
                if key in existing_metadata:
                    if key == "local_frame_paths" and frame_count > 0 and item.get("local_frame_paths"):
                        continue
                    item[key] = existing_metadata[key]
            item["transcript_text"] = existing_text
        else:
            print(f"  Whisper 转写中，模型: {model_name}")
            transcript = transcribe_audio(local_audio, model_name, context_item=item)
            item["raw_transcript_text"] = transcript["raw_text"]
            item["transcript_text"] = transcript["text"]
            item["transcript_segments"] = transcript["segments"]

        if ai_polish:
            metadata_path = item_dir / "metadata.json"
            if metadata_path.exists() and not overwrite and not existing_metadata:
                existing_metadata = load_existing_metadata(item_dir)
            if existing_metadata.get("ai_polished_text"):
                print("  已有 AI 清洗版，跳过 AI polish。")
                item["ai_polished_text"] = str(existing_metadata["ai_polished_text"])
            else:
                print(f"  AI 清洗中，模型: {ai_model}")
                item["ai_polished_text"] = ai_polish_transcript(item, ai_model)

        write_transcript_markdown(item_dir / "transcript.md", item)
        copy_outputs = write_copy_outputs(item_dir, item)
        item["copy_md_path"] = copy_outputs["copy_md"]
        item["copy_txt_path"] = copy_outputs["copy_txt"]
        wechat_outputs = write_wechat_outputs(item_dir, item, template=wechat_template)
        if wechat_outputs.get("wechat_md"):
            item["wechat_md_path"] = wechat_outputs["wechat_md"]
        if wechat_outputs.get("wechat_html"):
            item["wechat_html_path"] = wechat_outputs["wechat_html"]
        if (item_dir / "copy.zh.md").exists():
            item["copy_zh_md_path"] = "copy.zh.md"
        if (item_dir / "copy.zh.txt").exists():
            item["copy_zh_txt_path"] = "copy.zh.txt"
        if (item_dir / "review.md").exists():
            item["review_md_path"] = "review.md"
        write_json(item_dir / "metadata.json", item)
        processed.append(item)

    return processed


def write_manifest(
    output_root: Path,
    source_url: str,
    kind: str,
    limit: int,
    items: list[dict[str, Any]],
) -> None:
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_url": source_url,
        "kind": kind,
        "limit": limit,
        "count": len(items),
        "items": [
            {
                "aweme_id": item.get("aweme_id"),
                "platform": item.get("platform", "douyin"),
                "provider": item.get("provider", "bugpk"),
                "title": item.get("title"),
                "author_name": item.get("author_name"),
                "share_url": item.get("share_url"),
                "metadata_path": str(item_output_dir(output_root, item).relative_to(output_root) / "metadata.json"),
                "transcript_path": str(item_output_dir(output_root, item).relative_to(output_root) / "transcript.md"),
                "copy_md_path": str(item_output_dir(output_root, item).relative_to(output_root) / "copy.md"),
                "copy_txt_path": str(item_output_dir(output_root, item).relative_to(output_root) / "copy.txt"),
                "copy_zh_md_path": (
                    str(item_output_dir(output_root, item).relative_to(output_root) / item["copy_zh_md_path"])
                    if item.get("copy_zh_md_path")
                    else ""
                ),
                "copy_zh_txt_path": (
                    str(item_output_dir(output_root, item).relative_to(output_root) / item["copy_zh_txt_path"])
                    if item.get("copy_zh_txt_path")
                    else ""
                ),
                "review_md_path": (
                    str(item_output_dir(output_root, item).relative_to(output_root) / item["review_md_path"])
                    if item.get("review_md_path")
                    else ""
                ),
                "wechat_md_path": (
                    str(item_output_dir(output_root, item).relative_to(output_root) / item["wechat_md_path"])
                    if item.get("wechat_md_path")
                    else ""
                ),
                "wechat_html_path": (
                    str(item_output_dir(output_root, item).relative_to(output_root) / item["wechat_html_path"])
                    if item.get("wechat_html_path")
                    else ""
                ),
                "frame_paths": [
                    str(item_output_dir(output_root, item).relative_to(output_root) / frame_path)
                    for frame_path in (item.get("local_frame_paths") or [])
                ],
            }
            for item in items
        ],
    }
    write_json(output_root / "manifest.json", manifest)


def print_dry_run(kind: str, source_url: str, items: list[dict[str, Any]]) -> None:
    print(f"Dry run: kind={kind}, source={source_url}, count={len(items)}")
    for index, item in enumerate(items, start=1):
        print(f"{index}. {item.get('author_name')} | {item.get('title') or item.get('desc')}")
        print(f"   aweme_id: {item.get('aweme_id')}")
        print(f"   video_url: {'yes' if item.get('video_url') else 'no'}")
        print(f"   audio_url: {'yes' if item.get('audio_url') else 'no'}")


def collect_command(args: argparse.Namespace) -> int:
    kind, items, source_url = fetch_items(args.input, kind=args.kind, limit=args.limit)
    if args.dry_run:
        print_dry_run(kind, source_url, items)
        return 0
    processed = collect_items(
        items,
        output_root=Path(args.out),
        model_name=args.model,
        ai_polish=args.ai_polish,
        ai_model=args.ai_model,
        wechat_template=args.wechat_template,
        frame_count=args.frame_count,
        overwrite=args.overwrite,
    )
    write_manifest(Path(args.out), source_url, kind, args.limit, processed)
    print(f"完成：{len(processed)} 条视频已写入 {Path(args.out).resolve()}")
    return 0


def extract_frames_command(args: argparse.Namespace) -> int:
    item_dir = Path(args.item_dir)
    video_path = Path(args.video) if args.video else item_dir / "media" / "video.mp4"
    if not video_path.exists():
        raise FileNotFoundError(f"未找到视频文件: {video_path}")
    frames_dir = Path(args.frames_dir) if args.frames_dir else item_dir / "media" / "frames"
    timestamps = parse_timecode_list(args.times)
    frames = extract_video_frames_at_timestamps(
        video_path,
        frames_dir,
        timestamps,
        prefix=args.prefix,
        overwrite=args.overwrite,
    )
    print("已抽取截图:")
    for frame in frames:
        try:
            rel = frame.relative_to(item_dir)
        except ValueError:
            rel = frame
        rel_text = str(rel).replace("\\", "/")
        print(f"- {rel_text}")
    if args.contact_sheet:
        contact_sheet = write_contact_sheet(frames_dir, args.prefix, len(frames), overwrite=args.overwrite)
        try:
            rel_sheet = contact_sheet.relative_to(item_dir)
        except ValueError:
            rel_sheet = contact_sheet
        rel_sheet_text = str(rel_sheet).replace("\\", "/")
        print(f"截图总览: {rel_sheet_text}")
    return 0


def render_article_command(args: argparse.Namespace) -> int:
    item_dir = Path(args.item_dir)
    markdown_path = Path(args.input)
    if not markdown_path.is_absolute():
        markdown_path = item_dir / markdown_path
    if not markdown_path.exists():
        raise FileNotFoundError(f"未找到文章 Markdown: {markdown_path}")

    html_path = Path(args.html)
    if not html_path.is_absolute():
        html_path = item_dir / html_path

    markdown_text = markdown_path.read_text(encoding="utf-8")
    if args.template in WARM_CARD_TEMPLATE_ALIASES:
        html = render_warm_card_html(markdown_text)
    else:
        raise ValueError(f"暂不支持的文章模板: {args.template}")
    html_path.write_text(html, encoding="utf-8")
    print(f"已渲染: {html_path.resolve()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="抖音视频/主页采集与原始转写工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect", help="采集抖音视频或主页并生成原始转写")
    collect.add_argument("input", help="抖音分享文本、视频链接或博主主页链接")
    collect.add_argument("--out", default="output", help="输出目录，默认 output")
    collect.add_argument("--model", default="medium", choices=WHISPER_MODELS, help="Whisper 模型，默认 medium")
    collect.add_argument("--limit", type=int, default=10, help="主页最多处理条数，默认 10")
    collect.add_argument("--kind", default="auto", choices=("auto", "video", "profile"), help="链接类型，默认 auto")
    collect.add_argument("--dry-run", action="store_true", help="只解析并预览，不下载、不转写、不写文件")
    collect.add_argument("--overwrite", action="store_true", help="覆盖已有媒体、转写和元数据")
    collect.add_argument("--ai-polish", action="store_true", help="调用 OpenAI 对转写做忠实清洗和分段整理")
    collect.add_argument("--ai-model", default=DEFAULT_AI_MODEL, help=f"AI 清洗模型，默认 {DEFAULT_AI_MODEL}")
    collect.add_argument(
        "--wechat-template",
        default="none",
        choices=WECHAT_TEMPLATES,
        help="可选公众号排版输出：none/plain/warm-card/autumn-warm，默认 none",
    )
    collect.add_argument("--frame-count", type=int, default=0, help="从视频中均匀抽取截图数量，默认 0")
    collect.set_defaults(func=collect_command)

    frames = subparsers.add_parser("extract-frames", help="从已下载视频按指定时间点抽取公众号文章截图")
    frames.add_argument("item_dir", help="单条视频输出目录，例如 output/作者/aweme_id")
    frames.add_argument("--times", nargs="+", required=True, help="抽帧时间点，支持 8、00:05:35、00:00:08,00:05:35")
    frames.add_argument("--prefix", default="article", help="截图文件名前缀，默认 article")
    frames.add_argument("--video", default="", help="自定义视频路径，默认 item_dir/media/video.mp4")
    frames.add_argument("--frames-dir", default="", help="自定义截图目录，默认 item_dir/media/frames")
    frames.add_argument("--contact-sheet", action="store_true", help="生成截图总览图")
    frames.add_argument("--overwrite", action="store_true", help="覆盖已有截图")
    frames.set_defaults(func=extract_frames_command)

    render = subparsers.add_parser("render-article", help="把文章 Markdown 渲染为公众号暖光卡片 HTML")
    render.add_argument("item_dir", help="单条视频输出目录，例如 output/作者/aweme_id")
    render.add_argument("--input", default="article.md", help="文章 Markdown 文件名或路径，默认 article.md")
    render.add_argument("--html", default="article-warm-card.html", help="输出 HTML 文件名或路径")
    render.add_argument(
        "--template",
        default="warm-card",
        choices=("warm-card", "autumn-warm"),
        help="文章模板，默认 warm-card",
    )
    render.set_defaults(func=render_article_command)
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
