# daily-brief

两个信息源各有各的定时任务，各自产出成稿并经 **PushPlus** 推一条微信通知：

| 定时（北京时间） | 信息源 | 内容 | 去哪儿 |
|------------------|--------|------|--------|
| **08:30** | GitHub Trending | 前一天日增 stars Top10 + 大模型中文摘要与前三深度解读 | 微信公众号长图文、小红书图卡 |
| **15:10** | A 股主力资金流 | 25 秒竖屏视频：行业与个股的资金赛跑 | 小红书视频笔记 |

> 行情为什么排在下午：视频画的是**当日**分钟级资金流曲线，必须等 A 股 15:00
> 收盘，卡在 15:00 整点会丢掉尾盘集合竞价。非交易日行情源会自己识别并跳过。

两趟运行共用同一个站点：每趟先把线上已发布的内容取回来，只覆盖自己那个平台的
目录，所以上午发的公众号成稿不会被下午这趟抹掉。总览页列的是**站点上现有什么**，
并逐条标出日期，某一趟失败时一眼能看出哪条是陈的。

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
    index.html        # 分字段复制、下载封面
    article.html      # 独立 HTML 成稿
    article.md        # 备用 Markdown 成稿
    cover.png         # 900×383 头条封面
    meta.json         # 供总览页扫描的说明
  xhs/
    index.html        # 分字段复制、批量下载图卡
    card_01..06.png   # 1080×1440 竖版图卡
    note.txt          # 完整笔记存档（标题 + 正文 + 话题）
    meta.json
  xhs_video/
    index.html        # 页内可直接播放，分字段复制
    market.mp4        # 1080×1920 竖屏，H.264 + 静音音轨
    note.txt          # 完整笔记存档
    meta.json
```

发布流程（每项约 30 秒）：

1. 从 PushPlus 通知打开**分发总览**
2. 公众号：复制标题与正文 → 粘贴到编辑器 → 上传封面 → 群发
3. 小红书图文：按角标顺序上传 6 张图卡 → 分别复制标题、正文、话题 → 发布
4. 小红书视频：下载 mp4 → 选「视频笔记」上传 → 复制标题、正文、话题 → 发布

成稿页把标题、正文、话题拆成了独立的复制按钮，对应发布后台的各个输入框，
省得在手机上从一大段文本里选中切分。

图卡自动排版：封面含 Top5 预告，前三名各一张详情卡，第 4–10 名两张列表卡。
中文字体没有 emoji 字形，渲染时会自动剥离表情符号，避免出现豆腐块。

Actions 的 `drafts-*` Artifact 保存每期完整素材 30 天；GitHub Pages 由
`gh-pages` 分支提供，展示各信息源各自最新的一期。

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

A 股资金流视频（1080×1920，约 25 秒）：

- 封面：三大指数 + 当日资金之最
- 第一段：申万一级行业的资金赛跑，看钱从哪个行业流到哪个行业
- 第二段：个股赛跑，落到具体标的
- 条长是**当日累计**主力净流入，名次随分钟推进真实翻转——开盘领先的行业
  常在尾盘被反超，这是静态榜单给不了的东西
- 标题与正文直接由数据拼出，不走 LLM：这里全是事实，没有可改写的余地

> 视频每帧都挂免责声明。观众可能从任意一帧划入，声明只放片尾等于没放。

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
| `ENABLED_PLATFORMS` | 启用哪些平台，逗号分隔，留空为全部。可选 `wechat_mp`、`xhs`、`xhs_video`。只做公众号就填 `wechat_mp` |

关掉某个平台连带就跳过它背后的信息源：只填 `xhs_video` 时不会去调大模型，
只填 `wechat_mp,xhs` 时不会去打行情接口。

### 4. 打开 Actions 与 Pages

1. 到 **Actions** 页启用工作流
2. 手动试跑一次 **GitHub Trending**，让它建出 `gh-pages` 分支
3. 到 **Settings → Pages → Build and deployment → Source** 选
   **Deploy from a branch**，分支选 **`gh-pages` / (root)**

> ⚠️ 若你之前把 Source 设成了 **GitHub Actions**，这一步必须改过来。
> 站点现在由工作流直接推到 `gh-pages` 分支——只有让内容**留在分支上**，
> 两趟运行才能各自更新自己那部分而不互相覆盖。

两个工作流：

| 工作流 | 定时（UTC） | 北京时间 | 平台 |
|--------|-------------|----------|------|
| `GitHub Trending` | `30 0 * * *` | 08:30 | `wechat_mp,xhs` |
| `Market Flow` | `10 7 * * *` | 15:10 | `xhs_video` |

两者都调用同一个可复用工作流 `publish.yml`，装环境、跑测试、取回站点、生成、
推分支的步骤只维护一份。GitHub 调度可能延迟数分钟。

> 待验证：东方财富的行情接口在 GitHub 托管 runner（境外 IP）上是否可达。
> 若被限，`Market Flow` 那趟不会产出内容，但 `GitHub Trending` 完全不受影响；
> 届时可改用自托管 runner，或把行情那路挪到本地定时任务。

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

只跑行情视频那一路（不联网调大模型，几十秒出片）：

```powershell
$env:ENABLED_PLATFORMS="xhs_video"
python main.py --dry-run
start dist\xhs_video\index.html
```

只调排版，不联网也不消耗 LLM 额度（用内置的压力测试夹具：超长仓库名、超长与超短
摘要、缺失字段）：

```powershell
python -m tools.preview
start dist-preview\index.html
```

## 文件说明

按 `采集 → 加工 → 内容对象 → 渲染 → 投递` 分层，设计与后续多平台扩展见
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

```
main.py                      # CLI 入口
pipeline.py                  # 编排：逐信息源采集加工 → 逐平台渲染 → 逐平台投递
core/                        # 内容模型、LLM 客户端、配置、控制台
sources/github_trending.py   # 采集：抓取、去重、按日增 stars 重排
sources/market.py            # 采集：东财板块与个股的分钟级主力资金流
enrich/editorial.py          # LLM 中文摘要与 Top3 深度解读
enrich/social.py             # LLM 小红书钩子标题、导语、话题标签
renderers/article.py         # 公众号长图文 HTML + 900×383 封面
renderers/carddeck.py        # 小红书 1080×1440 图卡组 + 笔记正文
renderers/marketvideo.py     # 行情竖屏视频的帧序列与笔记文案
renderers/encode.py          # 帧序列 → MP4，缺 ffmpeg 时降级 GIF
renderers/fonts.py           # 字体加载、中英混排折行、emoji 剥离
renderers/theme.py           # 共用色板与字体栈
channels/bundle.py           # 成稿包与平台通用发布页
channels/overview.py         # 分发总览页
channels/pushplus.py         # 微信消息通知
tools/preview.py             # 压力测试夹具本地预览，调排版用
requirements.txt
.env.example
.github/workflows/
  publish.yml                # 可复用：装环境 → 测试 → 取回站点 → 生成 → 推分支
  github-trending.yml        # 08:30 触发，平台 wechat_mp,xhs
  market.yml                 # 15:10 触发，平台 xhs_video
tests/
```

## 以后升级投递方式

各平台的投递档位由 `<PLATFORM>_TIER` 环境变量控制，目前只实现 `bundle`（成稿包）。
若日后拿到**已认证服务号**，可实现 `api` 档位走公众号官方发布接口，
内容与渲染层无需改动。详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

若开通 PushPlus 会员并绑定自己的公众号，也可在 PushPlus 后台把默认渠道改掉，
或在请求里指定对应 `channel`/`webhook`，通知链路可复用。

小红书没有官方发笔记接口（开放平台只覆盖电商、广告与数据读取），因此不存在
「等资质到位就能走 API」的路径，全自动发布只能靠浏览器自动化，且有账号风险。
权衡见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) 的待决策项。
