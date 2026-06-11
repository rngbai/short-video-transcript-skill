---
name: short-video-transcript
description: Use when the user mentions short-video transcript extraction, 短视频转文字, 抖音, 快手, 小红书, 视频文案提取, 博主主页, 公众号素材, NotebookLM, or building a local transcript knowledge base from short videos.
metadata:
  short-description: 短视频采集、转写与图文整理
---

# Short Video Transcript

## Quick Start

Use the bundled CLI for deterministic collection:

```powershell
python scripts/short_video_collect.py collect "<短视频分享文本或链接>" --platform auto --out output --model medium --limit 10
```

For a safe preview without downloads or transcription:

```powershell
python scripts/short_video_collect.py collect "<短视频分享文本或链接>" --platform auto --dry-run
```

v1 implemented platform: domestic Douyin via BugPk. Planned but not implemented yet: Kuaishou, Xiaohongshu, Bilibili, TikTok.

## Workflow

1. Extract the short-video URL from the user-provided share text.
2. Use `scripts/short_video_collect.py collect ... --platform auto` by default. It dispatches to Douyin in v1.
3. Use `--kind auto` by default. Use `--kind profile` only when the input is clearly a creator homepage.
4. Keep `--limit 10` for homepage collection unless the user explicitly requests more.
5. Use `medium` by default for balance. For final high-accuracy copy, prefer `--model large-v3` or `--model large-v3-turbo`.
6. Read `copy.txt` and `metadata.json`.
7. As the agent, create `copy.zh.txt` and `copy.zh.md` with Chinese-natural punctuation.
8. If the user asks for公众号排版 or 图文稿, rerun or call with `--wechat-template warm-card --frame-count 5` to create `wechat.md`, `wechat-warm-card.html`, and video frame screenshots.
9. If the user asks for公众号文章、图文文章、切片稿、连麦整理稿, follow the "WeChat Article Workflow" below and create `article.md` or `dialogue.md` plus the matching warm-card HTML.
10. If the user wants local knowledge-base storage, follow the "Local Knowledge Base Workflow". Treat Markdown as the content source of truth; export PDF/DOCX only when explicitly useful.
11. If the user asks to上传到公众号 or 创建公众号草稿, follow the "WeChat Draft Workflow" below after the warm-card HTML is ready.
12. Return the generated `manifest.json`, `copy.zh.txt`, `copy.zh.md`, `copy.txt`, `transcript.md`, optional article/wechat HTML/PDF/DOCX, draft result JSON, and media paths to the user.

## Capability Modes

- Local mode is the default: Markdown, JSON, media files, optional PDF/DOCX. Markdown is the canonical local artifact and does not require WeChat credentials.
- WeChat layout mode creates article Markdown/HTML and video frames for manual or automated publishing. Native HTML is the canonical visual artifact for WeChat preview/copy/upload.
- WeChat draft mode is optional and requires official-account API configuration. Do not assume it exists.
- Platform support mode is explicit: v1 runs Douyin only. If Kuaishou/Xiaohongshu is requested, say it is planned but not implemented instead of faking support.

## Copy Output Rules

Default output is pure extracted video copy, not notes and not a rewrite.

- `copy.txt`: machine transcript copy body, no title, no source, no commentary.
- `copy.md`: title, source metadata, and the same machine copy body.
- `copy.zh.txt`: agent-corrected Chinese punctuation copy body, no title, no source, no commentary.
- `copy.zh.md`: title, source metadata, and the Chinese punctuation copy body.
- Use `transcript.md` for audit and debugging; use `copy.zh.txt` for later公众号接入.
- Do not summarize, extend, rewrite for virality, or add claims at this stage.
- The agent may fix punctuation, paragraph breaks, obvious spacing, and very obvious ASR homophones.
- If a phrase is likely wrong but uncertain, keep the body clean and record the uncertainty under `待复核`.
- Do not put every sentence on its own line.
- Short video copy should usually be one compact paragraph.
- Add paragraph breaks only for topic changes, speaker turns, or genuinely long paragraphs.

## Agent Chinese Punctuation Pass

After the CLI finishes, the agent should generate `copy.zh.txt` and `copy.zh.md`.

Input priority:

1. Prefer `metadata.json.transcript_text`.
2. Use `copy.txt` as the machine-copy fallback.
3. Consult `raw_transcript_text` and `transcript_segments` when punctuation is ambiguous.

Rules:

- Use Chinese punctuation: `，` `。` `？` `！` `：` `；` `“”`.
- Make sentences read like normal spoken Chinese converted to text.
- Merge over-fragmented ASR sentences into natural Chinese sentences.
- Keep paragraph breaks by topic or speaker turn, not by every sentence.
- Keep numbers, times, place names, and proper nouns conservative.
- Do not summarize, expand, add opinion, add标题党 wording, or turn it into公众号文章.
- Do not put uncertainty markers such as `[疑似：...]` in `copy.zh.txt`.
- For obvious semantic ASR errors, the agent may correct the body when context is strong. Record the correction in `copy.zh.md` under `校对记录`.
- For uncertain ASR, keep the most conservative clean wording in the body and put the uncertainty only in `copy.zh.md` under `待复核`.

Recommended `copy.zh.md` structure:

```md
# <视频标题>

- 来源：<作者>
- 平台链接：<share_url>
- 视频 ID：<aweme_id>
- 说明：AI 仅做中文标点和轻度 ASR 校对，未做总结或改写。

## 视频文案

<copy.zh.txt content>

## 待复核

- <不确定的 ASR 词句；不要写进正文>

## 校对记录

- <原识别 -> 校正后；只记录有意义的 ASR 修正>
```

If the user explicitly asks for knowledge-base notes, then create `notes.md` as a separate downstream artifact. If the user asks for公众号改写, create a separate article draft later; do not mix that into `copy.txt`.

## Local Knowledge Base Workflow

Use this when the user wants local storage, NotebookLM, Obsidian, files for review, or PDF/DOCX export. This path does not need WeChat configuration.

Recommended local outputs:

- `metadata.json`: structured source and transcript metadata.
- `copy.zh.txt`: clean extracted copy for search and reuse.
- `copy.zh.md`: source-aware Markdown archive.
- `article.md` or `dialogue.md`: reader-facing article and content source of truth when the user asks for a structured version.
- `article-warm-card.html` or `dialogue-warm-card.html`: native visual output for preview, WeChat copy, and draft upload.
- `notes.md`: optional knowledge-base notes when the user asks for summary/learning notes.
- `*.pdf` / `*.docx`: optional derived export artifacts, not replacements for Markdown/HTML.

Export PDF:

```powershell
python scripts/export_pdf.py "output/<author>/<aweme_id>"
```

Choose input explicitly:

```powershell
python scripts/export_pdf.py "output/<author>/<aweme_id>" --input dialogue.md --pdf dialogue.pdf
```

Generate DOCX explicitly:

```powershell
python scripts/export_pdf.py "output/<author>/<aweme_id>" --provider pandoc-docx --docx dialogue.docx
```

PDF rules:

- Markdown/HTML stays primary. Do not optimize the article around PDF at the expense of the native HTML layout.
- Prefer exporting `dialogue.md` / `article.md` when the user wants a polished reading file.
- Prefer exporting `copy.zh.md` when the user wants a faithful transcript archive.
- Include local video frames by default; use `--no-images` for text-only PDFs.
- Do not default to Chrome/Edge or browser print. Many users may not have those browsers available.
- Before inventing a converter, check available mature tooling. The built-in exporter tries `pandoc-typst`, then `pandoc-soffice`, then `pandoc-docx`.
- For PDF, ask the user to install Pandoc plus Typst or LibreOffice/soffice if neither PDF provider is available. If only Pandoc exists, generate DOCX first.
- Keep the Markdown H1 as the visible title; do not add an extra Pandoc metadata title that duplicates the heading.

## WeChat Layout Output

Use this only after the plain copy is good enough. It is a downstream layout artifact, not a replacement for `copy.txt` or `copy.zh.txt`.

```powershell
python scripts/short_video_collect.py collect "<短视频链接>" --platform auto --out output --model medium --wechat-template warm-card --frame-count 5
```

- `warm-card`: recommended. 暖光卡片风，暖白背景、橙色强调、卡片段落、浅纹理和轻阴影。
- `autumn-warm`: compatibility alias for `warm-card`.
- `plain`: only write `wechat.md`.
- `none`: default; no公众号排版输出.
- `--frame-count N`: extract N evenly spaced video screenshots into `media/frames/` and insert them into `wechat.md` / `wechat-warm-card.html`.

Rules:

- Keep source traceability in `metadata.json` / `copy.zh.md`. Do not put long URLs into the public WeChat body unless the user asks.
- `wechat-warm-card.html` must be WeChat-friendly inline HTML: no `<style>` tag and no `class=` attributes.
- Use images to improve公众号阅读感, but keep them sourced from the downloaded video and avoid adding unrelated stock imagery by default.
- Treat this as a backup visual template. For manual visual editing, `doocs/md` is still a good preview tool.
- `xiaohu-wechat-format` newspaper output from the trial lives under `wechat-compare/xiaohu/source-interview/preview.html`; its clean publish body is `article.html`.

## WeChat Article Workflow

Use this when the user wants the final result to look like a公众号图文文章, especially for interview,连麦, story, speech, or commentary videos.

### Standard Commands

Collect first:

```powershell
python scripts/short_video_collect.py collect "<短视频分享文本或链接>" --platform auto --out output --model medium --limit 1
```

For a fast structure test, `--model base` is acceptable. For publish-quality text, prefer `medium`, `large-v3`, or `large-v3-turbo`.

After reading `metadata.json.transcript_segments`, choose 4-8 meaningful visual moments and extract frames by timestamp:

```powershell
python scripts/douyin_collect.py extract-frames "output/<author>/<aweme_id>" --times 00:00:08 00:05:35 00:09:35 00:13:20 --prefix article --contact-sheet
```

After the agent writes `article.md` or `dialogue.md`, render the warm-card HTML:

```powershell
python scripts/douyin_collect.py render-article "output/<author>/<aweme_id>" --input article.md --html article-warm-card.html
```

### Article Markdown Shape

For one-speaker videos, write `article.md`:

```md
# <公众号标题>

> <一句适合公开阅读的导语，不写工作流说明、链接、时长或 ASR 校对记录。>

## 一句话重点

<核心观点，1 段>

![画面说明](media/frames/article_01.jpg)

## 正文整理

### <小节标题>

<自然段正文>
```

For two-person连麦/访谈 videos, write `dialogue.md`:

```md
# <公众号标题>

> <一句适合公开阅读的导语，不写说话人清单、链接、时长或整理说明。>

## 一句话重点

<核心事件或观点>

![画面说明](media/frames/dialogue_01.jpg)

## 对话整理

### <小节标题>

**人物 A：** <自然对话文本>

**人物 B：** <自然对话文本>

## 写在最后

<agent 基于全文写一段忠实的公开结尾，可以自然吸收视频里的金句。>
```

### Writing Rules

- Keep the article faithful to the video. Do not invent facts, quotes, names, places, motives, or outcomes.
- This is not `copy.zh.txt`; it may restructure for阅读, but must preserve meaning and source attribution.
- Prefer speaker labels for连麦/访谈. If the identity is uncertain, use neutral labels such as `连麦观众` instead of guessing names.
- Fix obvious ASR errors when context is strong, for example `校园80` -> `校园霸凌`, `进席` -> `锦旗`.
- Do not put `[疑似：...]` in the article body. Use conservative wording instead.
- Do not include internal workflow metadata in the public article body: no "这不是逐字稿", no original URL, no audio duration, no speaker list, no ASR correction notes, no "整理说明".
- Do not append candidate title lists such as `可用于公众号的标题` to the public article. Store them in sidecar notes only if the user asks.
- Do not append a raw "适合切片的金句" list to the public article. If quotes are useful, weave them into `写在最后` as a short reader-facing ending.
- Keep source URLs, transcript caveats, and correction notes in `metadata.json`, `copy.zh.md`, or a private `publish-notes.md`, not in the WeChat body.
- Insert images at meaningful section boundaries. Use frames from the downloaded video only by default.
- Use `###` for section-level subheadings; the warm-card renderer supports H3 as orange left-bar subheadings.
- Keep paragraphs readable for mobile. Do not place every sentence on its own line.
- End with a concise AI-written summary that stays faithful to the video and leaves the reader with one clear takeaway.

## WeChat Draft Workflow

Use this only after the final article HTML is ready and reviewed locally. This is an optional workflow; local knowledge-base and PDF use do not need WeChat credentials. The default is to create or update a WeChat Official Account draft, not to publish.

### Config

Read configuration from process environment, then these optional files:

- `.shiyi-wechat/.env`
- `config/shiyi-wechat/.env`
- `~/.shiyi-wechat/.env`

Required fields:

- `WECHAT_APP_ID`
- `WECHAT_APP_SECRET`
- `WECHAT_MODE=proxy|direct`
- `WECHAT_API_BASE` when `WECHAT_MODE=proxy`
- `WECHAT_DEFAULT_AUTHOR` optional

Never print appsecret, access_token, cookies, or private keys.

See `references/wechat-setup.md` for the complete setup guide.

### Commands

Check config first:

```powershell
python scripts/wechat_draft.py check-config
```

If the existing WeChat workflow already has a config file elsewhere, pass it explicitly:

```powershell
python scripts/wechat_draft.py --env-file "C:\path\to\.env" check-config
```

Dry-run the exact article directory before uploading:

```powershell
python scripts/wechat_draft.py create-draft "output/<author>/<aweme_id>" --html dialogue-warm-card.html --cover media/frames/dialogue_01.jpg --dry-run
```

Create the draft:

```powershell
python scripts/wechat_draft.py create-draft "output/<author>/<aweme_id>" --html dialogue-warm-card.html --cover media/frames/dialogue_01.jpg
```

Update an existing draft after editing the article:

```powershell
python scripts/wechat_draft.py create-draft "output/<author>/<aweme_id>" --html dialogue-warm-card.html --cover media/frames/dialogue_01.jpg --draft-media-id "<media_id>"
```

Only when the user explicitly asks to publish:

```powershell
python scripts/wechat_draft.py create-draft "output/<author>/<aweme_id>" --html dialogue-warm-card.html --cover media/frames/dialogue_01.jpg --publish
```

### Draft Rules

- Upload local `<img src="media/frames/...">` images to WeChat and replace them with WeChat image URLs before creating the draft.
- Upload the cover as a permanent material and use its `thumb_media_id`.
- Prefer the article HTML `<title>` / `<h1>` as the draft title; fall back to `metadata.json.title`.
- Do not set `content_source_url` by default; pass `--content-source-url` only when the user wants a visible "阅读原文" link.
- Write `wechat-draft-preview.html` and `wechat-draft-result.json` in the same item directory.
- Default to draft-only. Use `--publish` only after explicit user confirmation.
- If WeChat returns an IP whitelist error, report it without printing secrets.
- Never include WeChat admin/edit URLs in public docs or generated examples; those URLs often contain session `token` values.

## Outputs

The CLI writes:

- `output/manifest.json`
- `output/<author>/<aweme_id>/metadata.json`
- `output/<author>/<aweme_id>/transcript.md`
- `output/<author>/<aweme_id>/copy.md`
- `output/<author>/<aweme_id>/copy.txt`
- `output/<author>/<aweme_id>/copy.zh.md` (created by the agent)
- `output/<author>/<aweme_id>/copy.zh.txt` (created by the agent)
- `output/<author>/<aweme_id>/wechat.md` (optional)
- `output/<author>/<aweme_id>/wechat-warm-card.html` (optional)
- `output/<author>/<aweme_id>/article.md` / `article-warm-card.html` (agent-created article workflow)
- `output/<author>/<aweme_id>/dialogue.md` / `dialogue-warm-card.html` (agent-created dialogue workflow)
- `output/<author>/<aweme_id>/article.pdf` / `dialogue.pdf` / `copy.zh.pdf` (optional local PDF export)
- `output/<author>/<aweme_id>/article.docx` / `dialogue.docx` / `copy.zh.docx` (optional local DOCX export)
- `output/<author>/<aweme_id>/wechat-draft-preview.html` (optional draft upload body)
- `output/<author>/<aweme_id>/wechat-draft-result.json` (optional draft API result, no secrets)
- `output/<author>/<aweme_id>/media/video.mp4`
- `output/<author>/<aweme_id>/media/audio.mp3`
- `output/<author>/<aweme_id>/media/frames/frame_*.jpg` (optional)
- `output/<author>/<aweme_id>/media/frames/article_*.jpg` or `dialogue_*.jpg` (curated article frames)

See `references/output-format.md` for field details.

## Guardrails

- v1 implemented platform is domestic Douyin only. Kuaishou, Xiaohongshu, Bilibili, and TikTok are planned extension targets, not current capabilities.
- v1 Douyin collection uses BugPk API as the provider.
- Keep platform/provider fields in metadata so future collectors can share the same downstream transcript, Markdown, HTML, PDF/DOCX, and WeChat draft workflows.
- Do not hardcode local FFmpeg paths; require `ffmpeg` on PATH.
- Preserve media by default so reruns and manual review are possible.
- Preserve `raw_transcript_text`; use `transcript_text` for the punctuation-restored reading copy.
- For higher ASR precision, rerun with `--overwrite --model large-v3` or `--model large-v3-turbo`.
- Keep `copy.zh.txt` as punctuation-corrected extracted copy; do not turn it into notes or article copy.
- Keep `copy.zh.txt` clean: no bracketed review comments, no `[疑似：...]` markers.
- Do not add AI summaries unless the user explicitly asks for a later version.
