# 多平台内容分发架构设计

目标：多个信息源自动产出各平台形态的成品内容，并按各平台**实际可达的
自动化程度**投递。

**当前落地范围**：

| 信息源 | 产物 | 平台 |
|--------|------|------|
| GitHub Trending | 长图文、图卡组 | 微信公众号、小红书 |
| A 股主力资金流 | 1080×1920 竖屏视频 | 小红书视频笔记 |

抖音与视频号的分析保留在下文，架构已为其预留扩展点，但不在当前实现范围内。

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
Source ──► Enrich ──► Bundle ──► Renderer ──► Channel
采集       LLM 加工   统一内容对象  平台形态渲染   投递
```

五层职责边界：

- **Source**：只负责抓取原始数据，输出与平台无关的领域对象。可扩展多信息源。
- **Enrich**：LLM 加工（摘要、深读、标题候选、话题标签）。同样与平台无关。
  不是每个信息源都需要这一层——行情日报的标题与正文全是事实，直接由数据拼出，
  过一遍模型只会引入改写风险。
- **Bundle**：唯一的中间表示。下游所有平台都只依赖它，不依赖 Source。
- **Renderer**：把 Bundle 转成某平台的**成品形态**（长图文 / 图卡组 / 竖屏视频）。
- **Channel**：把成品**送出去**。同一个 Renderer 产物可以配不同 Channel。

关键设计点：Renderer 和 Channel 正交。小红书的图卡组既可以走「成稿包」人工发，
也可以走 Playwright 自动发，渲染逻辑完全不用改。

### 多信息源的组织：Feed

信息源与平台不是一对多而是多对多，所以 `pipeline.py` 里用 `Feed` 把
「一个信息源」和「它在各平台上的渲染器」绑在一起：

```python
FEEDS = (
    Feed("github", build_content_bundle,
         {"wechat_mp": article.render, "xhs": carddeck.render}),
    Feed("market", market.build_bundle,
         {"xhs_video": marketvideo.render}),
)
```

两条规则值得记住：

- **`build` 延迟到确认有平台启用之后才调用**。GitHub 那路要花 LLM 额度、
  行情那路要打三十来个行情接口，都不该为一个关掉的平台白跑。
- **信息源之间相互隔离**。任一信息源抛错只跳过它自己，其余照常产出；
  只有 `SystemExit`（缺配置）会中断整轮，因为那类错误改了配置才有意义。

小红书图文与视频用了 `xhs` 和 `xhs_video` 两个平台 key。它们其实是同一个账号，
但内容形态与信息源都不同，分开才能各写各的产物目录、各自开关。

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
class Bundle:
    """所有信息源共有的部分：一期内容的身份与社交平台文案。"""
    slug: str                        # 2026-08-17-github-trending
    date_text: str
    title: str                       # 主标题
    alt_titles: list[str]            # 钩子式标题候选
    lede: str                        # 一句话导语
    tags: list[str]                  # 话题标签，各平台按需截取

@dataclass
class ContentBundle(Bundle):
    repos: list[RepoItem]
    editorial: dict[int, Editorial]  # rank -> 编辑信息

@dataclass
class MarketBundle(Bundle):
    indexes: list[IndexQuote]
    sector_inflow: list[Sector]      # 各自带当日分钟级累计净流入曲线
    sector_outflow: list[Sector]
    stock_inflow: list[Stock]
    stock_outflow: list[Stock]
```

一个 dataclass 陷阱：**基类已有带默认值的字段，子类新增字段就必须也带默认值**，
否则 dataclass 拒绝生成 `__init__`。

领域类型（`RepoItem`、`Sector`、`Stock`…）一律住在 `core/models.py` 而不是各自的
采集模块里。否则渲染层要拿类型就得 `from sources.market import Sector`，
依赖方向就反了。

## 四、渲染层：一套内容，四种形态

四个平台的内容形态根本不同，不存在「同一份内容发四端」，只有
「同一份信息生成四种形态」。

```
                    ┌─► article.py   ──► 长图文 HTML + 900×383 封面   → 公众号   ✓
ContentBundle ──────┤
                    └─► carddeck.py  ──► 1080×1440 图卡组 + 笔记正文  → 小红书   ✓

MarketBundle ───────► marketvideo.py ──► 1080×1920 MP4 + 笔记正文    → 小红书视频 ✓
```

| Renderer | 产物 | 消费平台 | 状态 |
|----------|------|---------|------|
| `article.py` | `article.html` `article.md` `cover.png` | 公众号 | ✓ |
| `carddeck.py` | `card_01..06.png` `note.txt` | 小红书 | ✓ |
| `marketvideo.py` | `market.mp4` `note.txt` | 小红书视频 | ✓ |

### 视频资产：为什么帧是工厂函数

`ImageAsset` 直接携带 PIL 对象，视频不能照搬：1080×1920 一帧就是 6MB，
二十多秒的量足以把内存吃穿。所以 `VideoAsset` 携带的是**帧工厂**：

```python
@dataclass
class VideoAsset:
    name: str
    frames: Callable[[], Iterator[Image.Image]]
```

不用列表是放不下，不用生成器是因为**生成器只能消费一次**，而投递未必只发生一次
（重试、多渠道）。第二次保存拿到已耗尽的迭代器只会静默写出空文件。

编码在 `renderers/encode.py`：原始像素逐帧管道给 ffmpeg，不落中间 PNG。
ffmpeg 依次从系统 PATH 和 `imageio-ffmpeg` 找；都没有就降级 GIF，
并且**把扩展名一起改掉**——`save()` 返回真实写出的路径，发布页据此引用，
否则页面会指向一个不存在的 `.mp4`。

容器参数不是随手填的：`yuv420p` 是手机端播放器的通用底线，缺了它有些客户端
只出声不出画；`+faststart` 让 moov 原子前置以便边下边播；另外补了一条无声
AAC 音轨，因为部分平台会拒收没有音频流的视频。

### 资金赛跑的排版约束

- **单一标尺，不给流出组单独放大**。流入前五只有二十几亿而流出前五近两百亿时，
  流入的条会短到几乎看不见——但这个悬殊本身就是当天最重要的信息（资金单边
  出逃），双标尺会把它抹平。折中办法是给条形一个最小可见长度兜底。
- **行高按条目数自适应**，卡片高取行距的固定比例而非「行距减固定间隙」。
  后者在个股段 12 行时几乎把间隙吃光，两行稍微挨近就糊成一片。
- **名次交换要过迟滞阈值**。数值接近的两行会每帧互换、各自向中点收敛后叠在
  一起，画面上表现为「少了一行、另一处空出一格」。
- **数据放完后要继续滑行到各就各位再定格**。收盘那一刻名次往往刚翻转，
  直接定格就会把观众唯一会认真读的那一帧停在换位半路上。

前两条靠肉眼看成片很难定位——症状都只是「少了一行」。所以布局推演被抽成了
`marketvideo.layout()`，不碰像素，可以直接断言「同一帧里没有两行叠在一起」。

### 图卡排版约束

图卡尺寸固定而内容长度不定，1080×1440 的画布几乎总比内容大，所以真正的问题
不是「放不下」而是「填不满」。处理原则是**让留白落在卡片外面**：

- **详情卡的白卡高度跟着内容伸缩**（860–1320px）再整体居中。留白出现在
  白卡与背景之间时像是设计，出现在白卡内部就只是没填满。
- **列表卡把富余空间摊进条目间距**而不是堆在底部，条目少时靠拉开间距撑满。
- **封面的分隔线位置带上下夹逼**，短标题时不至于中段空一大块，长标题时也不会
  把 TOP5 预告挤到底部说明上。

另外几条是踩过的坑：

- **中文字体没有 emoji 字形**，直接绘制会出现豆腐块。`fonts.sanitize()` 会剥离
  emoji 区段，但避开版面自己在用的 ★、→、· 等符号。
- **标题不能硬截断**。小红书标题限 20 字，超长时只在句子级标点处回退，
  在空格或冒号处截断会留下「今日 GitHub 热榜：AI」这样的残句，宁可丢弃该候选。
- **超长 token 必须能按字符拆开**。`owner/some-very-long-repo-name` 在折行时是
  一个不可分割的单元，若整体宽于一行又不强制拆分，就会直接画出画布外。

排版调试用 `python -m tools.preview`：拿内置的压力测试夹具（超长仓库名、超长与
超短摘要、缺失深读字段）渲染到 `dist-preview/`，不联网也不消耗 LLM 额度。
上面两条边界问题都是这个夹具在真实数据之前先暴露出来的。

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

T1 的发布页是**一套模板服务所有平台**：有富文本就给富文本复制按钮，有图片就给
图卡网格加批量下载。新增平台不需要新写页面。

### 总览页扫磁盘，而不是收集本次产物

两个信息源跑在各自的定时任务里（08:30 与 15:10），runner 每次都是全新的：
下午那趟的 `dist/` 里根本没有上午产出的公众号成稿。如果总览页由「本次运行的
`RenderResult` 列表」生成，每跑一次就会丢掉另一半——文件还在站点上，
只是首页不再有入口。

所以每个平台目录自带一份 `meta.json`（平台、标题、日期、内容摘要），
`write_overview(root)` 只做一件事：扫 `root/*/meta.json` 并渲染。这样总览页
与「谁在什么时候跑过」彻底解耦。逐条标日期，某一趟失败时能看出哪条是陈的。

配套地，工作流在生成前先把线上站点克隆回 `dist/`，`BundleChannel` 又只清空
自己那个平台的子目录，两趟运行因此互不覆盖。

发布用强推的单提交：`gh-pages` 装的是图片和视频，按天累积提交会让仓库体积
只涨不跌，而产物的历史版本没人回看——要回溯有 Artifact（保留 7 天）。
这个分支只是发布载体，源码始终在 `main` 上，强推没有丢失代码的风险。

### 「今天没得发」不等于「跑挂了」

拆成两条流水线后，行情那条每逢周末都无内容可发。若沿用「没产出就报错」，
一周两次红叉，真出故障时就淹在噪音里了。

所以 `core.models.NothingToPublish` 把预期内的空跑单独标出来，`distribute()`
把两类分开收集（`Outcome.idle` 与 `Outcome.failed`），`run()` 据此决定退出码。
行情源因此有三种出口，分界线是**这一天本该有片子吗**：

| 情形 | 异常 | 运行结果 |
|------|------|----------|
| 周末、节假日 | `NotATradingDay` | 成功，安静跳过 |
| 收盘前手动触发 | `SessionNotClosed` | 成功，安静跳过 |
| 收盘后曲线仍不全 | `MarketDataLagging` | **失败**，需要人来看 |

最后一行是关键：那天本该出片，安静跳过就成了「漏发一期还没人知道」。
判据是墙上时钟——过了 `DATA_DEADLINE`（15:05）数据还不完整，那就不是
「还没收盘」而是上游滞后。

可复制的纯文本一律拆成 `CopyField` 列表，每个字段一个独立复制按钮：

```python
copy_fields=[
    CopyField("标题", bundle.social_title, "小红书标题上限 20 字", rows=2),
    CopyField("正文", build_note_body(bundle), rows=16),
    CopyField("话题标签", "#GitHub #开源项目", "粘贴过去只是普通文字……", rows=2),
]
```

这一层拆分不是为了好看：发布后台的标题、正文、话题是**三个独立输入框**，给一大段
拼好的文本，人就得自己在手机上选中切分，正是最容易出错的地方。

## 六、目录结构

已实现的标 ✓，其余为后续阶段。

```
core/
  models.py       ✓  Bundle / ContentBundle / MarketBundle 与各领域 TypedDict
  llm.py          ✓  LLM 客户端，自动适配 Anthropic 与 OpenAI 风格
  config.py       ✓  .env 加载、环境变量、平台开关与档位、时区
  console.py      ✓  兼容非 UTF-8 终端的输出
sources/
  github_trending.py  ✓  抓取 + 去重 + 按日增 stars 重排
  market.py           ✓  东财板块与个股分钟级资金流 + 交易日校验
  base.py                Source 协议（信息源再多时引入）
enrich/
  editorial.py    ✓  摘要 / Top3 深读 / 解析校验 / 兜底
  social.py       ✓  钩子标题 / 导语 / 话题标签，失败降级模板
renderers/
  base.py         ✓  Renderer 协议 + RenderResult + ImageAsset + VideoAsset
  theme.py        ✓  共用色板与字体栈
  fonts.py        ✓  字体加载、中英混排折行、emoji 剥离
  format.py       ✓  星标数值格式化
  encode.py       ✓  帧序列 → MP4，缺 ffmpeg 时降级 GIF
  article.py      ✓  公众号长图文 + Markdown + 900×383 封面
  carddeck.py     ✓  小红书 1080×1440 图卡组 + 笔记正文
  marketvideo.py  ✓  行情 1080×1920 竖屏视频 + 笔记正文
channels/
  base.py         ✓  Channel 协议 + DeliveryResult
  pushplus.py     ✓  T0 通知
  bundle.py       ✓  T1 成稿包 + 平台通用发布页
  overview.py     ✓  分发总览页
  playwright/        T2，可选安装
  api/               T3，预留
tools/
  preview.py      ✓  压力测试夹具本地预览，调排版用
pipeline.py       ✓  编排：Feed 定义与信息源隔离
main.py           ✓  CLI 入口
dist/
  index.html      ✓  分发总览页
  wechat_mp/      ✓  index.html / article.html / article.md / cover.png
  xhs/            ✓  index.html / card_01..06.png / note.txt
  xhs_video/      ✓  index.html / market.mp4 / note.txt
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
5. ~~**第二个信息源：A 股资金流视频**~~ ✓：`Bundle` 提为基类，新增
   `MarketBundle`、`VideoAsset` 与 `renderers/encode.py`，`pipeline` 改为
   按 `Feed` 组织多信息源。
6. ~~**两个信息源各自定时**~~ ✓：GitHub 留在 08:30，行情排到收盘后的 15:10。
   两个工作流调用同一个可复用的 `publish.yml`。站点改由 `gh-pages` 分支承载、
   每趟先取回再增量更新，总览页改为扫描磁盘（见上一节）。

顺带修掉的既有问题：`requirements.txt` 缺少 `pillow`，而封面渲染依赖它，
Actions 环境下会 ImportError。

### 行情源的选型结论（实测，别再重走一遍）

- 数据全在东方财富，`fflow/kline` 一个接口就给出全天每分钟一个点的主力净流入
  序列，板块与个股共用，只是 `secid` 前缀不同。
- **主源用 `push2delay`**，`push2` 只作降级。前者是延时行情、限流宽松得多；
  收盘后才跑，延时对日报毫无影响。`push2his` 实测全部超时，放弃。
- 早先「东财不可用」的判断是错的：那是**突发限流**，头几个请求放行、打快了就
  把 IP 关几分钟。按当前节奏走，一次采集三十来个请求、几秒钟跑完。
- 富途 OpenAPI 排除：需要本地常驻并登录 `FutuOpenD` 网关，进不了 CI。

三个必须记住的数据语义：

- **序列是累计值不是每分钟增量**。09:31 那个点是开盘头一分钟的净流入，
  15:00 那个点等于全天合计。
- **主力 = 超大单 + 大单**，与中小单净额之和恒为零。所以「主力流入」的另一面
  永远是散户在接盘，这是接口定义决定的，不是当天的行情特征。
- **板块列表混了申万一二三级且无法从数据里区分层级**。代码段是历史分配顺序
  （`BK12` 里既有一级的「电子」也有二级的「白酒Ⅱ」），罗马数字后缀只是重名时的
  消歧标记（「面板」没后缀却是三级）。只能按名字白名单筛到申万一级 31 个行业。
  不筛的后果不是难看而是**错**：「电子 -143 亿」和它的子行业「半导体 -74 亿」
  会各占一行，同一笔钱数两遍，看着像五个行业在跌、其实是两个。

另外，接口在非交易时段返回的是**上一个交易日**的完整曲线。所以 `build_bundle`
会拿曲线里的日期和今天比对，对不上就抛 `NotATradingDay` 交由管线跳过——
周末、节假日与收盘前误跑都靠这一道拦住，不必让 cron 去猜交易日历。

## 八、待决策项

- 小红书是否启用 T2 Playwright 自动发布？调研结论（2026-08）：

  官方 `open.xiaohongshu.com` 需企业主体，且**能力集中在电商、广告与数据读取，
  压根没有面向创作者的发笔记接口**——所以这里不存在「等资质到位就能走 T3」的
  路径，与公众号性质不同。社区实际在用的是两条非官方路线：

  | 路线 | 做法 | 代价 |
  |------|------|------|
  | 浏览器自动化 | Playwright driving `creator.xiaohongshu.com`，复用持久化登录态 | 登录态 7–30 天需重新扫码；页面改版即失效 |
  | 逆向签名接口 | 直接请求 `web_api/sns/v2/note`，自行计算 `x-s`/`x-t` | 签名算法随版本更新，依赖第三方库持续跟进 |

  两条都违反平台用户协议，风险由账号承担。若要做，选浏览器自动化：慢但更接近
  真人操作，且失败时能截图定位。已有 `xhs-kit`、`xhs-mcp-py` 等封装好扫码登录与
  发布流程的库，不必从零写。

  **仍需人工的部分比想象中多**：话题标签必须在编辑器里逐个输入 `#` 再从下拉选择
  才会绑定真正的 topic id，直接粘贴 `#xxx` 文本只是普通文字、拿不到话题页流量。
  这意味着即使上了 T2，「全自动」也会牺牲掉一部分分发效果。

  建议先跑 T1 观察一两周：如果内容本身没有受众，自动化省下的 30 秒毫无意义。
- 图卡数量是否要随内容调整？当前固定「封面 + 前三详情 + 列表卡」共 6 张，
  小红书上限 18 张，若发现完读率低可考虑精简到 4 张。
- 短视频是否要做？涉及 TTS 选型（成本）与形态验证（GitHub 日报做成口播视频
  是否有人看）。建议先用小红书验证内容本身是否有受众。
- 是否再引入信息源（Hacker News / arXiv）？架构已支持，但内容定位需先想清楚。
- **东财接口在 GitHub 托管 runner（境外 IP）上是否可达，尚未验证**。目前只在
  本地跑通。若被限，行情源会按信息源隔离规则自行跳过、不影响 GitHub 日报；
  届时的选项是换自托管 runner，或把行情那路挪到本地定时任务。
- 行情视频要不要配音或配乐？纯静默视频在小红书的完播率通常吃亏，但 TTS 念资金
  流数据容易变成噪音。可先观察数据再定。
- 候选池只覆盖综合榜加 8 个语言榜，冷门语言的暴涨项目若没挤进综合榜就会漏掉。
  要补全得再加语言榜，代价是每次多几个请求。
