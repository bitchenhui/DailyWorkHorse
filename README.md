# wechatInforPush

每天北京时间约 **08:30**，聚合 [GitHub Trending](https://github.com/trending?since=daily) 综合榜与主流语言榜候选，**按今日新增 stars 严格降序**取 Top10，用大模型生成中文摘要与前三名深度解读，再分别产出 **微信公众号** 与 **小红书** 两份可直接发布的成稿，并经 **PushPlus** 推一条微信通知。

> 说明：GitHub 没有官方“全站日增 stars Top10”接口。本榜单是 Trending 综合榜与主流语言榜候选池内的日增排名，并非全 GitHub 的数学全量榜。

> 通知走 PushPlus 官方公众号；你自己的个人未认证公众号继续做内容经营，互不冲突。

## 半自动分发

个人未认证订阅号拿不到公众号发布 API，小红书也不对个人开放笔记接口，
所以自动化边界划在**成稿**上：机器做到 100% 成品，你只负责最后一次粘贴上传。
设计取舍与后续升级路径见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

每天产出的 `dist/` 结构：

```
dist/
  index.html          # 分发总览，手机上打开这一页
  wechat_mp/
    index.html        # 一键复制正文、下载封面
    article.html      # 独立 HTML 成稿
    article.md        # 备用 Markdown 成稿
    cover.png         # 900×383 头条封面
  xhs/
    index.html        # 一键复制文案、批量下载图卡
    card_01..06.png   # 1080×1440 竖版图卡
    note.txt          # 笔记正文（含话题标签）
```

发布流程（两个平台各约 30 秒）：

1. 从 PushPlus 通知打开**分发总览**
2. 公众号：复制正文 → 粘贴到编辑器 → 上传封面 → 群发
3. 小红书：按顺序上传 6 张图卡 → 粘贴文案 → 发布

图卡自动排版：封面含 Top5 预告，前三名各一张详情卡，第 4–10 名两张列表卡。
中文字体没有 emoji 字形，渲染时会自动剥离表情符号，避免出现豆腐块。

Actions 的 `daily-drafts-*` Artifact 保存每期完整素材 30 天；GitHub Pages
展示最新一期。

## 内容长什么样

公众号长图文：

- 标题：`开源升温榜｜今日增长最快的 10 个 GitHub 项目`
- HTML 卡片排版，适配微信移动端阅读
- **前三观察**：中文摘要 + 是什么 / 上涨原因 / 适合关注
- **第 4–10 名**：仓库链接、日增★、语言、总星、中文一句话总结

小红书笔记：

- 标题由大模型另出一版钩子式短句（限 20 字），备选标题附在成稿页
- 图卡承载信息主体，正文保留完整项目名以命中站内搜索
- 话题标签自动生成，覆盖开源、语言、应用方向

## 一次性配置

### 1. PushPlus

1. 微信关注公众号 **「pushplus 推送加」**
2. 打开 [pushplus.plus](https://www.pushplus.plus) 登录，复制 **token**
3. **完成实名认证**（未实名会报错 code 905）：[https://verify.pushplus.plus](https://verify.pushplus.plus)

### 2. 大模型

脚本自动识别接口风格：

- `LLM_API_BASE` 含 `anthropic` → 走 Anthropic Messages（如 MiniMax）
- 否则 → 走 OpenAI `chat/completions`

| 平台 | `LLM_API_BASE` | `LLM_MODEL` |
|------|----------------|-------------|
| MiniMax | `https://api.minimaxi.com/anthropic` | `MiniMax-M3` |
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |

### 3. GitHub Secrets

仓库 → **Settings → Secrets and variables → Actions → New repository secret**，添加：

| Name | 说明 |
|------|------|
| `PUSHPLUS_TOKEN` | PushPlus token |
| `LLM_API_KEY` | 大模型 API Key |
| `LLM_API_BASE` | API Base URL（不要末尾多余路径以外的 `/chat/completions`） |
| `LLM_MODEL` | 模型名 |

可选的仓库 **Variables**（Settings → Secrets and variables → Actions → Variables）：

| Name | 说明 |
|------|------|
| `ENABLED_PLATFORMS` | 启用哪些平台，逗号分隔，留空为全部。只做公众号就填 `wechat_mp` |

### 4. 打开 Actions 与 Pages

1. 到 **Actions** 页启用工作流
2. 到 **Settings → Pages → Build and deployment → Source** 选择
   **GitHub Actions**
3. 在 **Daily GitHub Trending WeChat** 中点 **Run workflow** 手动试跑

定时：UTC `30 0 * * *`，即北京时间 **08:30**。GitHub 调度可能延迟数分钟。

## 本地试跑

```bash
cd D:\work\wechatInforPush
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# 编辑 .env 填入真实值后：
# PowerShell 临时注入环境变量再运行，或自行用 dotenv
$env:PUSHPLUS_TOKEN="..."
$env:LLM_API_KEY="..."
$env:LLM_API_BASE="https://api.deepseek.com"
$env:LLM_MODEL="deepseek-chat"
python main.py
```

只生成素材、不推送：

```powershell
python main.py --dry-run
start dist\index.html
```

## 文件说明

按 `采集 → 加工 → 内容对象 → 渲染 → 投递` 分层，设计与后续多平台扩展见
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

```
main.py                      # CLI 入口
pipeline.py                  # 编排：采集 → 加工 → 逐平台渲染 → 逐平台投递
core/                        # 内容模型、LLM 客户端、配置、控制台
sources/github_trending.py   # 采集：抓取、去重、按日增 stars 重排
enrich/editorial.py          # LLM 中文摘要与 Top3 深度解读
enrich/social.py             # LLM 小红书钩子标题、导语、话题标签
renderers/article.py         # 公众号长图文 HTML + 900×383 封面
renderers/carddeck.py        # 小红书 1080×1440 图卡组 + 笔记正文
renderers/fonts.py           # 字体加载、中英混排折行、emoji 剥离
renderers/theme.py           # 共用色板与字体栈
channels/bundle.py           # 成稿包与平台通用发布页
channels/overview.py         # 分发总览页
channels/pushplus.py         # 微信消息通知
requirements.txt
.env.example
.github/workflows/daily.yml  # 定时、Artifact 与 Pages 部署
tests/
```

## 以后升级投递方式

各平台的投递档位由 `<PLATFORM>_TIER` 环境变量控制，目前只实现 `bundle`（成稿包）。
若日后拿到**已认证服务号**，可实现 `api` 档位走公众号官方发布接口，
内容与渲染层无需改动。详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

若开通 PushPlus 会员并绑定自己的公众号，也可在 PushPlus 后台把默认渠道改掉，
或在请求里指定对应 `channel`/`webhook`，通知链路可复用。
