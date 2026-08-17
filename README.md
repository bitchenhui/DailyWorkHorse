# wechatInforPush

每天北京时间约 **08:30**，聚合 [GitHub Trending](https://github.com/trending?since=daily) 综合榜与主流语言榜候选，**按今日新增 stars 严格降序**取 Top10，用大模型为全部项目生成中文摘要，并为前三名补充深度解读，经 **PushPlus** 推送到微信。

> 说明：GitHub 没有官方“全站日增 stars Top10”接口。本榜单是 Trending 综合榜与主流语言榜候选池内的日增排名，并非全 GitHub 的数学全量榜。

> 推送走 PushPlus 官方公众号；你自己的个人未认证公众号继续做内容经营，互不冲突。

## 半自动发布到个人公众号

Actions 每天同时生成并保存：

- `index.html`：在线预览页，支持一键复制公众号正文
- `article.html`：独立 HTML 成稿
- `article.md`：备用 Markdown 成稿
- `cover.png`：900×383 公众号头条封面，核心文字位于中央安全区

你的发布流程：

1. 从 PushPlus 打开最新成稿
2. 点击 **复制公众号正文**，粘贴到公众号编辑器
3. 下载并上传 `cover.png`
4. 预览并群发

Actions 的 `wechat-draft-*` Artifact 保存每期完整素材 30 天；GitHub Pages
展示最新一期。

## 消息长什么样

- 标题：`开源升温榜｜今日增长最快的 10 个 GitHub 项目`
- HTML 公众号卡片排版，适配微信移动端阅读
- **前三观察**：中文摘要 + 是什么 / 上涨原因 / 适合关注
- **第 4–10 名**：仓库链接、日增★、语言、总星、中文一句话总结

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

```
main.py                      # 抓取 + LLM + PushPlus
publisher.py                 # 公众号成稿、复制页与封面生成
requirements.txt
.env.example
.github/workflows/daily.yml  # 定时、Artifact 与 Pages 部署
tests/test_main.py
```

## 以后换成自己的服务号

若日后有了**已认证服务号**并开通 PushPlus 会员绑定成功，一般只需在 PushPlus 后台把默认渠道改成你的公众号，或在请求里指定对应 `channel`/`webhook`，脚本主体可复用。
