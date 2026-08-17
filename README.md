# wechatInforPush

每天北京时间约 **08:30**，抓取 [GitHub Trending](https://github.com/trending?since=daily) 候选，**按今日新增 stars 严格降序**取 Top10，用大模型为日增最高的前三名写中文深度解读，经 **PushPlus** 推送到微信。

> 说明：GitHub Trending 页面顺序是平台热度算法，不等于日增 stars 排序；本脚本会本地重排后再出榜。

> 推送走 PushPlus 官方公众号；你自己的个人未认证公众号继续做内容经营，互不冲突。

## 消息长什么样

- 标题：`🔥 GitHub 今日热榜 · YYYY-MM-DD`
- **深度精选 Top3**：是什么 / 为何火 / 适合谁
- **完整榜单 Top10**：链接、日增★、语言、总星、简介

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

### 4. 打开 Actions

推送本仓库后，到 **Actions** 页启用工作流。可点 **Daily GitHub Trending WeChat → Run workflow** 手动试推一次（手动触发**不会** sleep 30 分钟）。

定时：UTC `0 0 * * *` + sleep 1800 ≈ 北京时间 **08:30**（GitHub cron 可能有数分钟到几十分钟延迟，属正常现象）。

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

## 文件说明

```
main.py                      # 抓取 + LLM + 推送
requirements.txt
.env.example
.github/workflows/daily.yml  # 定时任务
```

## 以后换成自己的服务号

若日后有了**已认证服务号**并开通 PushPlus 会员绑定成功，一般只需在 PushPlus 后台把默认渠道改成你的公众号，或在请求里指定对应 `channel`/`webhook`，脚本主体可复用。
