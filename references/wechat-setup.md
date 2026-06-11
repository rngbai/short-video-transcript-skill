# 公众号草稿环境配置

公众号上传是可选能力。只想把短视频整理成本地 Markdown、PDF 或知识库资料时，不需要配置公众号。

## 什么时候需要配置

只有这些场景需要配置：

- 把 `dialogue-warm-card.html` / `article-warm-card.html` 上传成公众号草稿。
- 自动上传正文截图和封面图。
- 更新已有公众号草稿。
- 显式执行发布动作。

## 需要准备的信息

- `WECHAT_APP_ID`：微信公众号 AppID。
- `WECHAT_APP_SECRET`：微信公众号 AppSecret。
- `WECHAT_MODE`：`proxy` 或 `direct`。
- `WECHAT_API_BASE`：仅 `proxy` 模式需要，用于复用已有代理服务。
- `WECHAT_DEFAULT_AUTHOR`：可选，公众号文章作者名。

## 配置文件位置

脚本按以下顺序读取配置：

1. 当前进程环境变量。
2. 项目根目录 `.shiyi-wechat/.env`。
3. 项目根目录 `config/shiyi-wechat/.env`。
4. 用户目录 `~/.shiyi-wechat/.env`。
5. 命令行显式传入的 `--env-file`。

推荐复制 `config/shiyi-wechat/.env.example` 为本地 `.env` 后填写真实值。真实 `.env` 已被 `.gitignore` 忽略，不要提交。

## 模式选择

`direct` 模式直接访问微信官方接口：

```text
WECHAT_MODE=direct
WECHAT_APP_ID=...
WECHAT_APP_SECRET=...
```

如果公众号后台开启了 IP 白名单，运行机器出口 IP 必须在白名单内。

`proxy` 模式适合已经有稳定代理服务的用户：

```text
WECHAT_MODE=proxy
WECHAT_API_BASE=https://your-proxy.example.com
WECHAT_APP_ID=...
WECHAT_APP_SECRET=...
```

## 验证命令

```powershell
python scripts/wechat_draft.py check-config
```

复用外部配置文件：

```powershell
python scripts/wechat_draft.py --env-file "C:\path\to\.env" check-config
```

创建草稿：

```powershell
python scripts/wechat_draft.py create-draft "output\<author>\<aweme_id>" --html dialogue-warm-card.html --cover media\frames\dialogue_01.jpg
```

更新已有草稿：

```powershell
python scripts/wechat_draft.py create-draft "output\<author>\<aweme_id>" --html dialogue-warm-card.html --cover media\frames\dialogue_01.jpg --draft-media-id "<media_id>"
```

默认只创建或更新草稿，不正式发布。只有显式传 `--publish` 才会提交发布。

## 安全规则

- 不要把 AppSecret、access_token、cookie 或代理密钥写进公开文档。
- 不要把真实 `.env` 提交到仓库。
- 默认不要把短视频链接写进公众号 `阅读原文`；确实需要时再传 `--content-source-url`。
- 发布前先在公众号后台人工预览，尤其检查图片、标题、摘要和原创/转载边界。
