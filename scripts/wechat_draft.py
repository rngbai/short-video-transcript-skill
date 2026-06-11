from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests


DEFAULT_DIRECT_BASE = "https://api.weixin.qq.com"
DEFAULT_ENV_DIRNAME = ".shiyi-wechat"
DEFAULT_RESULT_NAME = "wechat-draft-result.json"
DEFAULT_PREVIEW_NAME = "wechat-draft-preview.html"
CONTENT_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
HTML_IMAGE_SRC_RE = re.compile(r"(<img\b[^>]*?\bsrc=[\"'])([^\"']+)([\"'][^>]*>)", re.IGNORECASE)
BODY_RE = re.compile(r"<body\b[^>]*>(.*?)</body>", re.IGNORECASE | re.DOTALL)
TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
H1_RE = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class ImageReference:
    source: str
    path: Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_env_file(root: Path, raw: str | None) -> Path | None:
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def load_env(root: Path, explicit_env_file: str | None = None) -> dict[str, str]:
    merged: dict[str, str] = {}
    for env_path in (
        Path.home() / DEFAULT_ENV_DIRNAME / ".env",
        root / DEFAULT_ENV_DIRNAME / ".env",
        root / "config" / "shiyi-wechat" / ".env",
    ):
        merged.update(read_env_file(env_path))
    env_file = resolve_env_file(root, explicit_env_file)
    if env_file is not None:
        if not env_file.is_file():
            raise FileNotFoundError(f"公众号配置文件不存在: {env_file}")
        merged.update(read_env_file(env_file))
    merged.update({key: value for key, value in os.environ.items() if value is not None})
    return merged


def resolve_config(args: argparse.Namespace, require_credentials: bool = True) -> dict[str, str]:
    root = project_root()
    env = load_env(root, getattr(args, "env_file", None))
    mode = (
        getattr(args, "mode", None)
        or env.get("WECHAT_MODE")
        or ("proxy" if env.get("WECHAT_API_BASE") else "direct")
    ).strip().lower()
    if mode not in {"proxy", "direct"}:
        raise RuntimeError("WECHAT_MODE must be proxy or direct")

    base = getattr(args, "base", None)
    if not base:
        base = DEFAULT_DIRECT_BASE if mode == "direct" else env.get("WECHAT_API_BASE")
    if not base:
        raise RuntimeError("proxy mode requires WECHAT_API_BASE or --base")

    appid = getattr(args, "appid", None) or env.get("WECHAT_APP_ID")
    appsecret = getattr(args, "appsecret", None) or env.get("WECHAT_APP_SECRET")
    if require_credentials and (not appid or not appsecret):
        raise RuntimeError("missing WECHAT_APP_ID / WECHAT_APP_SECRET")

    return {
        "mode": mode,
        "base": base.rstrip("/"),
        "appid": appid or "",
        "appsecret": appsecret or "",
        "default_author": env.get("WECHAT_DEFAULT_AUTHOR", ""),
    }


def check_config(args: argparse.Namespace) -> int:
    cfg = resolve_config(args, require_credentials=True)
    present = {
        "WECHAT_MODE": cfg["mode"],
        "WECHAT_API_BASE": "PRESENT" if cfg["mode"] == "proxy" else "DIRECT",
        "WECHAT_APP_ID": "PRESENT",
        "WECHAT_APP_SECRET": "PRESENT",
    }
    print(json.dumps(present, ensure_ascii=False, indent=2))
    return 0


def resolve_path(base_dir: Path, raw: str | None) -> Path | None:
    if not raw:
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def path_is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload if isinstance(payload, dict) else {}


def load_manifest(raw_path: str | None) -> dict[str, Any]:
    if not raw_path:
        return {}
    path = Path(raw_path).expanduser().resolve()
    payload = load_json_file(path)
    nested = payload.get("wechat_draft")
    if isinstance(nested, dict):
        merged = {**payload, **nested}
        merged.pop("wechat_draft", None)
        return merged
    return payload


def fill_from_manifest(args: argparse.Namespace, manifest: dict[str, Any]) -> argparse.Namespace:
    if not manifest:
        return args
    aliases = {
        "item_dir": ("item_dir", "itemDir", "base_dir", "baseDir"),
        "html": ("html", "html_file", "htmlFile", "input_html", "inputHtml"),
        "cover": ("cover", "cover_image", "coverImage", "thumb"),
        "title": ("title",),
        "author": ("author",),
        "digest": ("digest",),
        "content_source_url": ("content_source_url", "contentSourceUrl", "source_url", "sourceUrl"),
        "preview_html": ("preview_html", "previewHtml"),
        "result_json": ("result_json", "resultJson"),
        "mode": ("mode",),
        "base": ("api_base", "apiBase", "base_url", "baseUrl"),
    }
    for attr, keys in aliases.items():
        if getattr(args, attr, None):
            continue
        for key in keys:
            value = manifest.get(key)
            if value:
                setattr(args, attr, str(value))
                break
    return args


def strip_tags(value: str) -> str:
    value = SCRIPT_STYLE_RE.sub("", value)
    value = TAG_RE.sub("", value)
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def extract_body_html(html_text: str) -> str:
    match = BODY_RE.search(html_text)
    body = match.group(1) if match else html_text
    return SCRIPT_STYLE_RE.sub("", body).strip()


def extract_title(html_text: str) -> str:
    for pattern in (TITLE_RE, H1_RE):
        match = pattern.search(html_text)
        if match:
            title = strip_tags(match.group(1))
            if title:
                return title
    return ""


def truncate_utf8(text: str, max_bytes: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return text
    cut = data[:max_bytes]
    while cut:
        try:
            return cut.decode("utf-8").rstrip()
        except UnicodeDecodeError:
            cut = cut[:-1]
    return ""


def sanitize_wechat_title(title: str) -> str:
    title = title.replace("\u3000", " ")
    title = re.sub(r"[\r\n\t]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return truncate_utf8(title or "抖音视频整理", 64) or "抖音视频整理"


def build_digest(content_html: str, explicit: str | None = None) -> str:
    if explicit:
        return truncate_utf8(explicit, 120)
    text = strip_tags(content_html)
    return truncate_utf8(text, 120)


def read_html_input(item_dir: Path, raw_html: str | None) -> tuple[Path, str]:
    candidates = []
    if raw_html:
        candidates.append(resolve_path(item_dir, raw_html))
    else:
        for name in ("dialogue-warm-card.html", "article-warm-card.html", "wechat-warm-card.html"):
            candidates.append(item_dir / name)
    for path in candidates:
        if path and path.is_file():
            return path, path.read_text(encoding="utf-8-sig")
    raise FileNotFoundError("未找到公众号 HTML，请传入 --html")


def resolve_image_src(item_dir: Path, src: str) -> Path | None:
    parsed = urllib.parse.urlparse(src)
    if parsed.scheme in {"http", "https", "data"}:
        return None
    if parsed.netloc and parsed.scheme != "file":
        return None

    if parsed.scheme == "file":
        raw_path = urllib.parse.unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:/", raw_path):
            raw_path = raw_path[1:]
        path = Path(raw_path)
    else:
        raw_path = urllib.parse.unquote(parsed.path or src)
        path = Path(raw_path)
        if not path.is_absolute():
            path = item_dir / path

    path = path.resolve()
    if not path_is_inside(path, item_dir):
        raise RuntimeError(f"图片路径不在当前视频目录内，已拒绝上传: {path}")
    if path.suffix.lower() not in CONTENT_IMAGE_EXTENSIONS:
        raise RuntimeError(f"公众号正文图片仅支持 jpg/jpeg/png: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"HTML 引用的图片不存在: {path}")
    return path


def list_local_image_references(content_html: str, item_dir: Path) -> list[ImageReference]:
    refs: list[ImageReference] = []
    seen: set[Path] = set()
    for match in HTML_IMAGE_SRC_RE.finditer(content_html):
        src = match.group(2)
        path = resolve_image_src(item_dir, src)
        if path is None or path in seen:
            continue
        refs.append(ImageReference(source=src, path=path))
        seen.add(path)
    return refs


def list_remote_image_sources(content_html: str) -> list[str]:
    sources: list[str] = []
    for match in HTML_IMAGE_SRC_RE.finditer(content_html):
        src = match.group(2)
        parsed = urllib.parse.urlparse(src)
        if parsed.scheme in {"http", "https"}:
            sources.append(src)
    return sources


def replace_local_images(
    content_html: str,
    item_dir: Path,
    upload_image: Callable[[Path], str] | None = None,
    dry_run: bool = False,
) -> tuple[str, list[dict[str, Any]]]:
    upload_map: dict[Path, dict[str, Any]] = {}

    def replace(match: re.Match[str]) -> str:
        prefix, src, suffix = match.group(1), match.group(2), match.group(3)
        path = resolve_image_src(item_dir, src)
        if path is None:
            return match.group(0)
        if path not in upload_map:
            if dry_run:
                url = src
            else:
                if upload_image is None:
                    raise RuntimeError("upload_image is required when dry_run is false")
                url = upload_image(path)
            upload_map[path] = {
                "source": src,
                "path": str(path),
                "url": url,
                "uploaded": not dry_run,
            }
        return f"{prefix}{html.escape(upload_map[path]['url'], quote=True)}{suffix}"

    return HTML_IMAGE_SRC_RE.sub(replace, content_html), list(upload_map.values())


def choose_cover_path(item_dir: Path, explicit: str | None, refs: list[ImageReference]) -> Path:
    if explicit:
        cover = resolve_path(item_dir, explicit)
        if cover is None:
            raise FileNotFoundError("封面路径为空")
    elif refs:
        cover = refs[0].path
    else:
        frame_dir = item_dir / "media" / "frames"
        candidates = sorted(
            path for path in frame_dir.glob("*.jpg") if path.is_file() and "contact_sheet" not in path.name
        )
        if not candidates:
            raise FileNotFoundError("未找到可用封面图，请传入 --cover")
        cover = candidates[0]

    cover = cover.resolve()
    if not path_is_inside(cover, item_dir):
        raise RuntimeError(f"封面路径不在当前视频目录内，已拒绝上传: {cover}")
    if cover.suffix.lower() not in CONTENT_IMAGE_EXTENSIONS:
        raise RuntimeError(f"公众号封面图片仅支持 jpg/jpeg/png: {cover}")
    if not cover.is_file():
        raise FileNotFoundError(f"封面图片不存在: {cover}")
    return cover


def get_public_ip(timeout: float = 5.0) -> str:
    for endpoint in ("https://api.ipify.org", "https://ifconfig.me/ip", "https://ip.seeip.org"):
        try:
            response = requests.get(endpoint, timeout=timeout)
            response.raise_for_status()
            value = response.text.strip()
            if value:
                return value[:64]
        except Exception:
            continue
    return ""


def get_access_token(appid: str, appsecret: str, base: str) -> str:
    response = requests.get(
        f"{base}/cgi-bin/token",
        params={"grant_type": "client_credential", "appid": appid, "secret": appsecret},
        timeout=12,
    )
    response.raise_for_status()
    data = response.json()
    if "access_token" not in data:
        if str(data.get("errcode")) == "40164":
            public_ip = get_public_ip()
            hint = f" 当前出口公网 IP: {public_ip}" if public_ip else ""
            raise RuntimeError(f"获取 access_token 失败，IP 可能不在公众号白名单。{hint}")
        raise RuntimeError(f"获取 access_token 失败: {data}")
    return str(data["access_token"])


def upload_cover_material(access_token: str, image_path: Path, base: str) -> str:
    url = f"{base}/cgi-bin/material/add_material"
    with image_path.open("rb") as file_obj:
        response = requests.post(
            url,
            params={"access_token": access_token, "type": "image"},
            files={"media": (image_path.name, file_obj, "application/octet-stream")},
            timeout=60,
        )
    response.raise_for_status()
    data = response.json()
    if "media_id" not in data:
        raise RuntimeError(f"上传封面失败: {data}")
    return str(data["media_id"])


def upload_content_image(access_token: str, image_path: Path, base: str) -> str:
    url = f"{base}/cgi-bin/media/uploadimg"
    with image_path.open("rb") as file_obj:
        response = requests.post(
            url,
            params={"access_token": access_token},
            files={"media": (image_path.name, file_obj, "application/octet-stream")},
            timeout=60,
        )
    response.raise_for_status()
    data = response.json()
    if "url" not in data:
        raise RuntimeError(f"上传正文图片失败: {data}")
    return str(data["url"])


def retry_upload_content_image(access_token: str, image_path: Path, base: str, attempts: int = 3) -> str:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return upload_content_image(access_token, image_path, base)
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(1)
    raise RuntimeError(f"正文图片连续上传失败: {image_path.name}: {last_error}")


def create_draft_payload(
    title: str,
    author: str,
    digest: str,
    content_html: str,
    thumb_media_id: str,
    content_source_url: str = "",
    open_comment: int = 0,
    only_fans_can_comment: int = 0,
    show_cover_pic: int = 0,
) -> dict[str, Any]:
    article: dict[str, Any] = {
        "title": title,
        "author": author,
        "digest": digest,
        "content": content_html,
        "thumb_media_id": thumb_media_id,
        "show_cover_pic": int(show_cover_pic),
        "need_open_comment": int(open_comment),
        "only_fans_can_comment": int(only_fans_can_comment),
    }
    if content_source_url:
        article["content_source_url"] = content_source_url
    return {"articles": [article]}


def create_draft(access_token: str, payload: dict[str, Any], base: str) -> dict[str, Any]:
    response = requests.post(
        f"{base}/cgi-bin/draft/add",
        params={"access_token": access_token},
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if "media_id" not in data:
        raise RuntimeError(f"创建公众号草稿失败: {data}")
    return data


def publish_draft(access_token: str, media_id: str, base: str) -> dict[str, Any]:
    response = requests.post(
        f"{base}/cgi-bin/freepublish/submit",
        params={"access_token": access_token},
        json={"media_id": media_id},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("errcode") not in (None, 0):
        raise RuntimeError(f"提交发布失败: {data}")
    return data


def update_draft(access_token: str, media_id: str, index: int, article: dict[str, Any], base: str) -> dict[str, Any]:
    response = requests.post(
        f"{base}/cgi-bin/draft/update",
        params={"access_token": access_token},
        data=json.dumps(
            {"media_id": media_id, "index": int(index), "articles": article},
            ensure_ascii=False,
        ).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("errcode") not in (None, 0):
        raise RuntimeError(f"更新公众号草稿失败: {data}")
    return data


def infer_title(args: argparse.Namespace, html_text: str, metadata: dict[str, Any]) -> str:
    return sanitize_wechat_title(
        args.title
        or extract_title(html_text)
        or str(metadata.get("title") or metadata.get("desc") or "")
        or "抖音视频整理"
    )


def infer_author(args: argparse.Namespace, cfg: dict[str, str], metadata: dict[str, Any]) -> str:
    return args.author or cfg.get("default_author") or str(metadata.get("author_name") or "")


def default_content_source_url(args: argparse.Namespace, metadata: dict[str, Any]) -> str:
    return args.content_source_url or ""


def ensure_size_limits(content_html: str) -> None:
    size = len(content_html.encode("utf-8"))
    if size > 1_000_000:
        raise RuntimeError(f"公众号正文 HTML 超过 1MB: {size} bytes")


def run_create_draft(args: argparse.Namespace) -> int:
    args = fill_from_manifest(args, load_manifest(args.manifest))
    if not args.item_dir:
        raise RuntimeError("必须传入视频输出目录，例如 output/<author>/<aweme_id>")

    item_dir = Path(args.item_dir).expanduser().resolve()
    if not item_dir.is_dir():
        raise FileNotFoundError(f"视频输出目录不存在: {item_dir}")

    input_html_path, html_text = read_html_input(item_dir, args.html)
    metadata = load_json_file(item_dir / "metadata.json")
    body_html = extract_body_html(html_text)
    ensure_size_limits(body_html)

    cfg = resolve_config(args, require_credentials=not args.dry_run)
    title = infer_title(args, html_text, metadata)
    author = infer_author(args, cfg, metadata)
    digest = build_digest(body_html, args.digest or title)
    content_source_url = default_content_source_url(args, metadata)
    refs = list_local_image_references(body_html, item_dir)
    cover_path = choose_cover_path(item_dir, args.cover, refs)

    preview_html = resolve_path(item_dir, args.preview_html) or (item_dir / DEFAULT_PREVIEW_NAME)
    result_json = resolve_path(item_dir, args.result_json) or (item_dir / DEFAULT_RESULT_NAME)
    preview_html.parent.mkdir(parents=True, exist_ok=True)
    result_json.parent.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "success": False,
        "dry_run": bool(args.dry_run),
        "published": False,
        "updated": bool(args.draft_media_id),
        "mode": cfg["mode"],
        "base": cfg["base"],
        "input_html": str(input_html_path),
        "preview_html": str(preview_html),
        "result_json": str(result_json),
        "title": title,
        "author": author,
        "digest": digest,
        "content_source_url": content_source_url,
        "cover_path": str(cover_path),
        "remote_image_sources": list_remote_image_sources(body_html),
    }

    if args.dry_run:
        final_html, uploads = replace_local_images(body_html, item_dir, dry_run=True)
        preview_html.write_text(final_html, encoding="utf-8")
        result.update(
            {
                "success": True,
                "content_html": str(preview_html),
                "image_uploads": uploads,
                "thumb_media_id": "",
                "draft_response": {},
            }
        )
        result_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print("== 获取 access_token ==")
    token = get_access_token(cfg["appid"], cfg["appsecret"], cfg["base"])
    print("access_token OK")

    print("== 上传封面 ==")
    thumb_media_id = upload_cover_material(token, cover_path, cfg["base"])
    print("thumb_media_id OK")

    print("== 上传正文图片 ==")

    def upload(path: Path) -> str:
        url = retry_upload_content_image(token, path, cfg["base"])
        print(f" {path.name} -> OK")
        return url

    final_html, uploads = replace_local_images(body_html, item_dir, upload_image=upload, dry_run=False)
    ensure_size_limits(final_html)
    preview_html.write_text(final_html, encoding="utf-8")

    payload = create_draft_payload(
        title=title,
        author=author,
        digest=digest,
        content_html=final_html,
        thumb_media_id=thumb_media_id,
        content_source_url=content_source_url,
        open_comment=args.open_comment,
        only_fans_can_comment=args.only_fans_can_comment,
        show_cover_pic=1 if args.show_cover else 0,
    )

    if args.draft_media_id:
        print("== 更新公众号草稿 ==")
        draft_response = update_draft(
            token,
            args.draft_media_id,
            args.article_index,
            payload["articles"][0],
            cfg["base"],
        )
        media_id = args.draft_media_id
        print("草稿更新成功")
    else:
        print("== 创建公众号草稿 ==")
        draft_response = create_draft(token, payload, cfg["base"])
        media_id = str(draft_response.get("media_id", ""))
        print("草稿创建成功")

    result.update(
        {
            "success": True,
            "content_html": str(preview_html),
            "image_uploads": uploads,
            "thumb_media_id": thumb_media_id,
            "draft_media_id": media_id,
            "draft_response": draft_response,
        }
    )

    if args.publish:
        print("== 提交发布 ==")
        publish_response = publish_draft(token, media_id, cfg["base"])
        result["published"] = True
        result["publish_response"] = publish_response

    result_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(
        {
            "success": True,
            "published": result["published"],
            "updated": result["updated"],
            "media_id": media_id,
            "preview_html": str(preview_html),
            "result_json": str(result_json),
            "mode": cfg["mode"],
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


def add_config_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mode",
        choices=["proxy", "direct"],
        default=argparse.SUPPRESS,
        help="不传则读取 WECHAT_MODE；有 WECHAT_API_BASE 时默认 proxy",
    )
    parser.add_argument(
        "--base",
        default=argparse.SUPPRESS,
        help="接口 base URL；proxy 模式通常来自 WECHAT_API_BASE",
    )
    parser.add_argument(
        "--appid",
        default=argparse.SUPPRESS,
        help="公众号 AppID；也可用 WECHAT_APP_ID",
    )
    parser.add_argument(
        "--appsecret",
        default=argparse.SUPPRESS,
        help="公众号 AppSecret；也可用 WECHAT_APP_SECRET",
    )
    parser.add_argument(
        "--env-file",
        default=argparse.SUPPRESS,
        help="额外指定公众号 .env 配置文件；只读取，不打印具体值",
    )


def build_parser() -> argparse.ArgumentParser:
    config_parent = argparse.ArgumentParser(add_help=False)
    add_config_arguments(config_parent)
    parser = argparse.ArgumentParser(
        description="Create WeChat Official Account drafts from local Douyin article HTML.",
        parents=[config_parent],
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check-config", parents=[config_parent], help="只检查公众号配置是否齐全，不输出密钥")

    create = subparsers.add_parser(
        "create-draft",
        parents=[config_parent],
        help="从本地 HTML 和抽帧图片创建公众号草稿",
    )
    create.add_argument("item_dir", nargs="?", help="视频输出目录，例如 output/<author>/<aweme_id>")
    create.add_argument("--manifest", help="工作流 JSON，可填入 item_dir/html/title/cover 等字段")
    create.add_argument("--html", help="相对 item_dir 的 HTML，默认自动寻找 dialogue/article/wechat-warm-card.html")
    create.add_argument("--cover", help="相对 item_dir 的封面图；默认使用正文第一张本地图片")
    create.add_argument("--title", help="草稿标题；默认读取 HTML title/h1 或 metadata.json")
    create.add_argument("--author", help="作者名；默认读取 WECHAT_DEFAULT_AUTHOR 或 metadata.json.author_name")
    create.add_argument("--digest", help="摘要；默认从正文提取")
    create.add_argument("--content-source-url", help="阅读原文链接；默认不设置，只有显式传入才写入")
    create.add_argument("--preview-html", help=f"最终上传正文预览，默认 {DEFAULT_PREVIEW_NAME}")
    create.add_argument("--result-json", help=f"结果 JSON，默认 {DEFAULT_RESULT_NAME}")
    create.add_argument("--draft-media-id", help="已有草稿 media_id；传入时更新草稿而不是新建草稿")
    create.add_argument("--article-index", type=int, default=0, help="更新草稿中的文章序号，默认 0")
    create.add_argument("--open-comment", type=int, default=0)
    create.add_argument("--only-fans-can-comment", type=int, default=0)
    create.add_argument("--show-cover", action="store_true", help="在正文顶部显示封面图")
    create.add_argument("--dry-run", action="store_true", help="只校验并生成预览，不上传、不建草稿")
    create.add_argument("--publish", action="store_true", help="显式提交发布；默认只创建草稿")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "check-config":
        return check_config(args)
    if args.command == "create-draft":
        return run_create_draft(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
