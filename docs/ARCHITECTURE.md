# 多平台内容分发架构设计

目标：一个信息源（当前为 GitHub Trending）自动产出各平台形态的成品内容，
并按各平台**实际可达的自动化程度**投递。

**当前落地范围：微信公众号 + 小红书**。抖音与视频号的分析保留在下文，
架构已为其预留扩展点，但不在当前实现范围内。

## 一、前置约束（决定了架构形态）

当前账号资质：**个人未认证订阅号，无企业主体**。由此产生的硬约束：

| 平台 | 官方发布 API | 当前可用性 |
|------|-------------|-----------|
| 微信公众号 | 有（`draft/add` + `freepublish/submit`） | ✗ 仅限已认证订阅号/服务号；且需服务器 IP 白名单 |
| 抖音 | 有（开放平台内容管理） | ✗ 需企业主体 + 应用审核 |
| 小红书 | 无（开放平台仅电商向） | ✗ 笔记发布仅对 MCN/合作方 |
| 视频号 | 无 | ✗ 官方未提供创作者发布接口 |

结论：**短期内四端都无法走官方 API 自动发布**。因此自动化的价值边界在于
「把人的工作从 30 分钟压缩到 30 秒」，而不是「把人删掉」。架构必须让投递方式
可插拔，使得资质升级后无需重写内容层。

## 二、分层模型

```
Source ──► Enrich ──► ContentBundle ──► Renderer ──► Channel
采集       LLM 加工     统一内容对象      平台形态渲染   投递
```

五层职责边界：

- **Source**：只负责抓取原始数据，输出与平台无关的领域对象。可扩展多信息源。
- **Enrich**：LLM 加工（摘要、深读、标题候选、话题标签）。同样与平台无关。
- **ContentBundle**：唯一的中间表示。下游所有平台都只依赖它，不依赖 Source。
- **Renderer**：把 ContentBundle 转成某平台的**成品形态**（长图文 / 图卡组 / 竖版视频）。
- **Channel**：把成品**送出去**。同一个 Renderer 产物可以配不同 Channel。

关键设计点：Renderer 和 Channel 正交。小红书的图卡组既可以走「成稿包」人工发，
也可以走 Playwright 自动发，渲染逻辑完全不用改。

## 三、核心数据模型

`RepoItem` 与 `Editorial` 采用 **TypedDict**：运行时就是普通 dict，各层可直接互传
无需序列化，同时又有明确的字段契约，也避免了重构期间大面积改写取值方式。

```python
# core/models.py

class RepoItem(TypedDict):
    """信息源产出的单条领域对象。"""
    rank: int
    full_name: str
    url: str
    description: str
    language: str
    stars_total: int
    stars_today: int

class Editorial(TypedDict):
    """LLM 生成的编辑信息，rank 4 起 what/why/who 为空串。"""
    summary: str
    what: str
    why: str
    who: str

@dataclass
class ContentBundle:
    """平台无关的统一内容对象，是整个管线的腰。"""
    slug: str                        # 2026-08-17-github-trending
    date_text: str
    title: str                       # 主标题（公众号用）
    repos: list[RepoItem]
    editorial: dict[int, Editorial]  # rank -> 编辑信息
```

阶段 3 起会补充小红书/短视频所需的三个字段，由 Enrich 层一次性生成：

- `alt_titles: list[str]` —— 钩子式标题候选。小红书标题风格与公众号差异极大，
  让 LLM 一次输出多套比事后改写更省 token、也更可控。
- `lede: str` —— 一句话导语。
- `tags: list[str]` —— 话题标签，各平台按需截取。

## 四、渲染层：一套内容，四种形态

四个平台的内容形态根本不同，不存在「同一份内容发四端」，只有
「同一份信息生成四种形态」。

```
                    ┌─► article.py   ──► 长图文 HTML + 900×383 封面   → 公众号   ✓
ContentBundle ──────┼─► carddeck.py  ──► 1080×1440 图卡组 + 笔记正文  → 小红书   ✓
                    │                        │
                    │                        └──(复用图卡)
                    └─► shortvideo.py ──► 1080×1920 MP4 + 口播稿     → 抖音/视频号
```

**复用关系是这个设计的关键**：短视频不做真正的剪辑，而是复用小红书的图卡组，
用 TTS 生成配音、ffmpeg 把图卡按配音时长拼成竖版视频。这样一次图卡渲染工作
同时喂饱三个平台，边际成本极低。图卡渲染只依赖 Pillow，无需额外依赖。

| Renderer | 产物 | 消费平台 | 状态 |
|----------|------|---------|------|
| `article.py` | `article.html` `article.md` `cover.png` | 公众号 | ✓ |
| `carddeck.py` | `card_01..06.png` `note.txt` | 小红书 | ✓ |
| `shortvideo.py` | `video.mp4` `script.txt` | 抖音、视频号 | 未实现，需 TTS + ffmpeg |

### 图卡排版约束

图卡尺寸固定而内容长度不定，因此各卡都先测量文本行数、再把内容整体定位，
富余空间按 1:2 分给上下（略偏上比正居中自然）。另外两条是踩过的坑：

- **中文字体没有 emoji 字形**，直接绘制会出现豆腐块。`fonts.sanitize()` 会剥离
  emoji 区段，但避开版面自己在用的 ★、→、· 等符号。
- **标题不能硬截断**。小红书标题限 20 字，超长时只在句子级标点处回退，
  在空格或冒号处截断会留下「今日 GitHub 热榜：AI」这样的残句，宁可丢弃该候选。

## 五、投递层：四个档位

Channel 按自动化程度分四档，**每个平台配置走哪一档**，通过环境变量切换。
这样资质升级时只改配置，不动代码。

- **T0 通知** ✓：PushPlus 推一条微信消息告知「今日内容已就绪」，附分发总览链接。
- **T1 成稿包** ✓（当前主力）：生成 `dist/<platform>/` 目录 + 发布页，
  人工 30 秒完成粘贴发布。
- **T2 UI 自动化**：Playwright 持久化登录态自动发布。只在本地或自建机器跑，
  **不进 GitHub Actions**（登录态是长期凭证，不适合放 CI；且平台风控对
  数据中心 IP 敏感）。
- **T3 官方 API**：资质达标后启用。

```python
# channels/base.py

class Channel(Protocol):
    name: str

    def preflight(self) -> None:
        """校验凭证/登录态是否可用，不可用时抛出可读错误。"""

    def deliver(self, bundle: ContentBundle, result: RenderResult) -> DeliveryResult:
        """投递。T1 实现为写盘 + 生成发布页；T2 为浏览器操作；T3 为 API 调用。"""
```

档位由 `<PLATFORM>_TIER` 环境变量选择，未实现的档位会抛出可读错误而非静默降级。
启用哪些平台由 `ENABLED_PLATFORMS` 控制，缺省全开。

| 平台 | 当前档位 | 升级条件 |
|------|---------|---------|
| 公众号 | T1 成稿包 ✓ | 完成微信认证（¥300/年）→ T3 API |
| 小红书 | T1 成稿包 ✓ | 稳定后可选 T2，注意风控 |
| 抖音 | 未启用 | 有企业主体 → T3 API |
| 视频号 | 未启用 | 无升级路径，长期 T1/T2 |

T1 的发布页是**一套模板服务所有平台**：有富文本就给富文本复制按钮，有纯文本就给
文案复制框，有图片就给图卡网格加批量下载。新增平台不需要新写页面。

## 六、目录结构

已实现的标 ✓，其余为后续阶段。

```
core/
  models.py       ✓  RepoItem / Editorial / ContentBundle
  llm.py          ✓  LLM 客户端，自动适配 Anthropic 与 OpenAI 风格
  config.py       ✓  .env 加载、环境变量、平台开关与档位、时区
  console.py      ✓  兼容非 UTF-8 终端的输出
sources/
  github_trending.py  ✓  抓取 + 去重 + 按日增 stars 重排
  base.py                Source 协议（多信息源时引入）
enrich/
  editorial.py    ✓  摘要 / Top3 深读 / 解析校验 / 兜底
  social.py       ✓  钩子标题 / 导语 / 话题标签，失败降级模板
renderers/
  base.py         ✓  Renderer 协议 + RenderResult + ImageAsset
  theme.py        ✓  共用色板与字体栈
  fonts.py        ✓  字体加载、中英混排折行、emoji 剥离
  format.py       ✓  星标数值格式化
  article.py      ✓  公众号长图文 + Markdown + 900×383 封面
  carddeck.py     ✓  小红书 1080×1440 图卡组 + 笔记正文
  shortvideo.py      竖版视频
channels/
  base.py         ✓  Channel 协议 + DeliveryResult
  pushplus.py     ✓  T0 通知
  bundle.py       ✓  T1 成稿包 + 平台通用发布页
  overview.py     ✓  分发总览页
  playwright/        T2，可选安装
  api/               T3，预留
pipeline.py       ✓  编排
main.py           ✓  CLI 入口
dist/
  index.html      ✓  分发总览页
  wechat_mp/      ✓  index.html / article.html / article.md / cover.png
  xhs/            ✓  index.html / card_01..06.png / note.txt
```

## 七、迁移路径

严格分阶段，每阶段结束时 `python -m unittest discover -s tests -t .` 必须通过，
且**每日推送不能中断**。

1. ~~**抽骨架，行为不变**~~ ✓：`main.py` 按上述目录拆分，引入 `ContentBundle`。
   验证方式：用固定 fixture 生成重构前后的渲染快照，`article.html` /
   `article.md` / `index.html` / `cover.png` 四件产物 SHA256 逐字节一致；
   原测试一行未改且全绿。
2. ~~**投递层抽象**~~ ✓：引入 `RenderResult` 与 `Channel` 协议，成稿包泛化为
   平台通用实现，接入 `ENABLED_PLATFORMS` 与 `<PLATFORM>_TIER` 开关。
   此阶段删除了阶段 1 遗留的向后兼容壳（`publisher.py`）。
3. ~~**小红书图卡**~~ ✓：新增 `enrich/social.py` 与 `renderers/carddeck.py`，
   产出 6 张图卡 + 笔记正文 + 话题标签。
4. ~~**分发总览页**~~ ✓：`dist/index.html` 改成各平台入口，
   微信通知里的链接也指向它。
5. **短视频**（可选）：TTS + ffmpeg。工作量约等于前四步之和，建议在前面跑顺
   并确认有持续产出意愿后再启动。

顺带修掉的既有问题：`requirements.txt` 缺少 `pillow`，而封面渲染依赖它，
Actions 环境下会 ImportError。

## 八、待决策项

- 小红书是否启用 T2 Playwright 自动发布？收益是省掉每天一次手动操作，
  代价是登录态维护 + 账号风险。建议先跑 T1 观察一两周。
- 图卡数量是否要随内容调整？当前固定「封面 + 前三详情 + 列表卡」共 6 张，
  小红书上限 18 张，若发现完读率低可考虑精简到 4 张。
- 短视频是否要做？涉及 TTS 选型（成本）与形态验证（GitHub 日报做成口播视频
  是否有人看）。建议先用小红书验证内容本身是否有受众。
- 是否引入第二个信息源（Hacker News / arXiv）？架构已支持，但内容定位需先想清楚。
