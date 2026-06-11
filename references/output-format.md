# 输出格式说明

## `manifest.json`

一次采集任务的总索引：

- `created_at`：生成时间，UTC ISO 格式。
- `source_url`：解析后的来源链接。
- `kind`：`video` 或 `profile`。
- `limit`：主页采集数量上限。
- `count`：本次输出的视频数量。
- `items`：每条视频的轻量索引，包含 `platform`、`provider`、`aweme_id`、`title`、`author_name`、`share_url`、`metadata_path`、`transcript_path`。
- `copy_md_path` / `copy_txt_path`：纯视频文案输出路径。
- `copy_zh_md_path` / `copy_zh_txt_path`：agent 生成的中文标点版文案路径，可选。

## `metadata.json`

每条视频的完整规范化元数据：

- `platform`：平台标识，v1 为 `douyin`。
- `provider`：采集 provider，v1 抖音默认为 `bugpk`。
- `aweme_id`：平台视频 ID；抖音为 aweme_id，无法获取时生成稳定的 `unknown_<hash>`。
- `title`：标题，优先使用接口标题，其次使用简介。
- `desc`：视频简介。
- `author_name`：作者名。
- `author_id`：作者 ID。
- `share_url`：视频分享链接。
- `create_time`：发布时间，沿用接口原始格式。
- `duration`：视频时长，沿用接口原始单位。
- `cover_url`：封面链接。
- `video_url`：视频直链。
- `audio_url`：音频直链，可能为空。
- `statistics`：点赞、评论、收藏等统计信息。
- `hashtags`：话题标签列表。
- `local_video_path`：相对输出目录的视频文件路径。
- `local_audio_path`：相对输出目录的音频文件路径。
- `raw_transcript_text`：Whisper 原始转写，不额外加标点。
- `transcript_text`：恢复基础中文标点后的转写文本。
- `ai_polished_text`：可选字段，开启 `--ai-polish` 后生成，面向阅读和知识库导入。
- `transcript_segments`：Whisper 返回的分段信息，用于复查和后续精细加工。
- `copy_md_path`：同级 `copy.md` 文件名。
- `copy_txt_path`：同级 `copy.txt` 文件名。

## `transcript.md`

面向阅读和知识库导入的 Markdown：

- 顶部是标题和视频基础信息。
- `原始文案` 保留接口返回的视频简介。
- `转写文本（已恢复标点）` 用于阅读和知识库导入。
- `AI 清洗版` 是可选内容，仅在启用 `--ai-polish` 后出现。
- `原始转写（未加标点）` 保留 Whisper 原始识别文本，不做 AI 总结。

## `copy.txt`

机器文案正文，只包含从视频音频提取出来的文字内容：

- 不带标题。
- 不带来源信息。
- 不做总结。
- 不做公众号改写。
- 由脚本生成，标点可能偏机械。
- 短文默认是连续自然段，不逐句空行；长文才按长度分段。

## `copy.md`

带元信息的文案归档版：

- 标题。
- 来源、平台链接、视频 ID。
- `视频文案` 正文。

## `copy.zh.txt`

AI agent 按中文语感校对后的纯正文：

- 只改标点、自然段和明显 ASR 小问题。
- 不总结。
- 不公众号改写。
- 不添加视频外信息。
- 不确定词不要在正文里用 `[疑似：...]` 标注；正文保留最保守原词。
- 不确定项放到 `copy.zh.md` 的 `待复核` 区。
- 不要每句话单独换行；短视频默认一段自然正文。
- 推荐作为后续公众号工作流的一手文案输入。

## `copy.zh.md`

带元信息的中文标点归档版：

- 标题。
- 来源、平台链接、视频 ID。
- 说明：AI 仅做中文标点和轻度 ASR 校对。
- `视频文案` 正文。
- `待复核`：列出不确定的 ASR 词句；这些批注不应进入 `copy.zh.txt` 正文。
- `校对记录`：列出 AI 对明显 ASR 错误做出的正文修正，如 `半块钱 -> 8块钱`。

## `wechat.md`（可选公众号排版稿）

传 `--wechat-template plain|warm-card|autumn-warm` 时生成；推荐使用 `warm-card`。

- 公众号阅读结构稿。
- 保留来源信息，不伪装原创。
- 长链接默认放文末，避免手机宽度下撑破开头引用块。
- 如果 `metadata.json.local_frame_paths` 有截图，会插入 `视频截图` 小节。

## `wechat-warm-card.html`（可选公众号 HTML）

传 `--wechat-template warm-card` 或兼容别名 `--wechat-template autumn-warm` 时生成：

- 暖光卡片风：暖白背景、橙色强调、卡片分区、浅网格纹理和轻阴影。
- 只使用内联样式，不写 `<style>` 和 `class=`，方便复制到公众号后台前预览。
- 这是公众号视觉母版，适合预览、复制和草稿上传；不替代 `copy.txt`、`copy.zh.txt` 或 `metadata.json`。

## `article.md` / `article-warm-card.html`（可选公众号图文文章）

当用户明确需要公众号文章、图文稿、口播整理稿或视频切片稿时，由 agent 在采集转写后生成：

- `article.md`：单人口播或非对话视频的图文文章 Markdown。
- `article-warm-card.html`：由 `render-article` 渲染出的暖光卡片 HTML。
- `article.md` 是内容母版，后续 PDF/DOCX/HTML 都应从它派生。
- 文章可以重组段落、添加小标题和插图，但必须忠实于原视频，不新增事实。
- 文章正文不要出现 `[疑似：...]`；不确定内容应使用保守表达或放到待复核说明。
- 图片引用通常来自 `media/frames/article_*.jpg`。

## `dialogue.md` / `dialogue-warm-card.html`（可选连麦/访谈图文稿）

当视频包含两位或多位说话人时，由 agent 生成：

- `dialogue.md`：按说话人整理的对话式 Markdown。
- `dialogue-warm-card.html`：由 `render-article` 渲染出的暖光卡片 HTML。
- `dialogue.md` 是内容母版，`dialogue-warm-card.html` 是公众号视觉母版。
- 推荐说话人标签：`大冰`、`连麦观众`、`主持人`、`嘉宾` 等；不确定身份不要猜姓名。
- 图片引用通常来自 `media/frames/dialogue_*.jpg`。
- 公开正文不写工作流信息、原视频链接、音频时长、ASR 修正说明、候选标题列表或切片金句清单。
- 结尾推荐使用 `写在最后`，由 agent 忠实总结全文，并自然吸收视频里的关键句。

## `*.pdf`（可选本地知识库导出）

使用 `scripts/export_pdf.py` 从 Markdown 导出：

- 默认输入优先级：`dialogue.md`、`article.md`、`copy.zh.md`、`copy.md`、`transcript.md`。
- 默认输出同名 PDF，例如 `dialogue.md` -> `dialogue.pdf`。
- 保留标题、小节、自然段、引用和列表。
- 默认包含本地图片引用，例如 `media/frames/dialogue_*.jpg`。
- 传 `--no-images` 可生成纯文字 PDF。
- PDF 是本地知识库/审阅的派生产物，不需要公众号配置；不要为了 PDF 牺牲 Markdown/HTML 的正文结构和公众号视觉效果。
- 默认不依赖 Chrome/Edge，不使用浏览器打印作为主链路。
- provider 自动选择顺序：`pandoc-typst`、`pandoc-soffice`、`pandoc-docx`。
- 需要 PDF 时推荐安装 Pandoc + Typst，或 Pandoc + LibreOffice/soffice。
- 如果只有 Pandoc，使用 `--provider pandoc-docx --docx <name>.docx` 先生成 DOCX。
- 可传 `--keep-docx` 在 PDF 导出时同时保留 DOCX，方便二次编辑。

## `wechat-draft-preview.html`（可选公众号草稿正文）

使用 `scripts/wechat_draft.py create-draft` 时生成：

- 内容来自 `dialogue-warm-card.html`、`article-warm-card.html` 或 `wechat-warm-card.html` 的 `<body>`。
- 本地图片会在真实上传时替换为微信公众号图片 URL。
- 干跑 `--dry-run` 时不上传，仍保留本地图片路径，方便本地预览。
- 不包含 `<script>` 或 `<style>`；推荐继续使用暖光卡片这类内联样式 HTML。

## `wechat-draft-result.json`（可选公众号草稿结果）

使用 `scripts/wechat_draft.py create-draft` 时生成；不记录密钥、token 或 cookie。

常见字段：

- `success`：草稿流程是否成功。
- `dry_run`：是否为干跑。
- `published`：是否已提交发布；默认 `false`。
- `updated`：是否更新已有草稿；传 `--draft-media-id` 时为 `true`。
- `mode`：`proxy` 或 `direct`。
- `input_html`：源 HTML 路径。
- `preview_html`：最终正文 HTML 路径。
- `title`：草稿标题。
- `author`：作者名。
- `digest`：摘要。
- `content_source_url`：阅读原文链接；默认空，只有显式传 `--content-source-url` 时写入。
- `cover_path`：封面本地路径。
- `thumb_media_id`：封面永久素材 ID；干跑为空。
- `draft_media_id`：公众号草稿 media_id。
- `draft_response`：创建草稿接口返回。
- `publish_response`：仅传 `--publish` 时出现。
- `image_uploads`：正文图片上传映射，包含本地路径和微信图片 URL。

## `media/frames/frame_*.jpg`（可选视频截图）

传 `--frame-count <N>` 时生成：

- 使用 FFmpeg 从下载的视频中均匀抽取 N 张截图。
- 默认避开视频开头和结尾，取中间更有信息量的画面。
- 截图路径会写入 `metadata.json.local_frame_paths` 和 `manifest.json.items[].frame_paths`。
- 当同时生成 `wechat.md` / `wechat-warm-card.html` 时，截图会自动插入公众号稿。

## `media/frames/article_*.jpg` / `dialogue_*.jpg`（可选文章关键帧）

使用 `extract-frames` 按指定时间点生成：

- `article_01.jpg`、`article_02.jpg`：单人口播图文稿关键帧。
- `dialogue_01.jpg`、`dialogue_02.jpg`：连麦/访谈图文稿关键帧。
- `<prefix>_contact_sheet.jpg`：截图总览图，用来快速复核图片质量。
- 这些图片由 agent 根据 `transcript_segments` 的内容节点挑选，通常比均匀抽帧更适合最终公众号文章。

## `notes.md`（可选下游产物）

当用户明确需要知识库笔记时，agent 可以读取 `copy.txt`、`metadata.json` 或 `transcript.md`，并生成同级 `notes.md` 作为知识库阅读版。

`notes.md` 应包含：

- 来源信息：标题、作者、平台链接、视频 ID。
- 整理说明：注明由视频转写忠实清洗而来。
- 核心内容：按自然语义分段。
- 关键要点：提炼视频中明确表达的内容。
- 可执行建议：仅从视频内容中提取，不额外编造。
- 待复核：列出 ASR 可能识别错误或上下文不确定的词句。

## 媒体文件

- `media/video.mp4`：视频文件，默认保留。
- `media/audio.mp3`：音频文件，默认保留。

如果接口没有音频直链，工具会下载视频并用 FFmpeg 抽取 `audio.mp3`。
