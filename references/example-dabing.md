# 示例：大冰短视频整理成公众号图文稿

这个案例来自一次真实跑通的工作流，用来说明本 skill 的最终效果。仓库只保留脱敏说明，不提交视频、截图、公众号后台链接或任何草稿 token。

## 输入

- 平台：抖音
- 作者：冰言冰语
- 内容类型：大冰讲述/连麦类视频
- 目标：整理成适合公众号阅读的图文稿，并创建公众号草稿

## 推荐流程

```powershell
# 1. 采集、下载、转写
python scripts/short_video_collect.py collect "<抖音分享文本或链接>" --platform auto --out output --model medium --limit 1

# 2. 按内容节点抽取关键帧
python scripts/douyin_collect.py extract-frames "output/<author>/<aweme_id>" --times 00:00:08 00:05:35 00:09:35 00:13:20 --prefix dialogue --contact-sheet

# 3. Agent 基于 metadata.json / transcript_segments 整理 dialogue.md
# 4. 渲染公众号暖光卡片 HTML
python scripts/douyin_collect.py render-article "output/<author>/<aweme_id>" --input dialogue.md --html dialogue-warm-card.html

# 5. 可选：上传到微信公众号草稿
python scripts/wechat_draft.py create-draft "output/<author>/<aweme_id>" --html dialogue-warm-card.html --cover media/frames/dialogue_01.jpg
```

## 输出效果

示例文章标题：

```text
一一大哥的故事：德高为兄
```

一句话重点：

```text
一个孩子在该站出来的时候，替这个世界守住了常识。
```

典型产物：

- `dialogue.md`：内容母版，适合二次编辑、知识库沉淀和版本管理。
- `dialogue-warm-card.html`：公众号视觉母版，暖光卡片风，适合预览、复制和草稿上传。
- `media/frames/dialogue_*.jpg`：视频关键帧，增强图文阅读感。
- `wechat-draft-preview.html`：本地预览正文。
- `wechat-draft-result.json`：草稿接口结果，不包含密钥。

## 公众号注意事项

- 不要把微信公众号后台编辑链接提交到仓库或贴到公开文档；后台链接通常包含 `token`。
- README 中只展示脱敏案例，不展示真实草稿 `media_id`、后台 URL、AppSecret、access_token 或代理密钥。
- 公开文章正文不要包含“这不是逐字稿”、原视频链接、音频时长、ASR 校对说明、候选标题列表等工作流信息。
- 默认不设置“阅读原文”；只有用户明确需要时再传 `--content-source-url`。
