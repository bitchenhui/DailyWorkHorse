"""A 股资金流采集：行业板块与个股的分钟级主力净流入曲线。

选源结论（实测，别再重走一遍）：

- **数据全在东方财富**，``fflow/kline`` 一个接口就能给出全天每分钟一个点的
  主力净流入序列，板块与个股共用，只是 ``secid`` 前缀不同。
- **主源用 ``push2delay``**，``push2`` 只作降级。前者是延时行情，限流宽松得多；
  日报收盘后才跑，延时对我们毫无影响。
- **``push2his`` 直接放弃**，实测 0/5 全部超时。
- 早先「东财不可用」的判断是错的：那是**突发限流**，头几个请求放行、打快了就
  把 IP 关几分钟。按本文件的节奏走，实测 8/8 一次通过、全程 3 秒。

三个必须记住的数据语义：

- **序列是累计值不是每分钟增量**。09:31 那个点是开盘头一分钟的净流入，
  15:00 那个点等于全天合计。想要每分钟净额得自己做差分。
- **主力 = 超大单 + 大单**，与中小单净额之和恒为零，所以「主力流入」的另一面
  永远是散户在接盘，这是接口的定义决定的，不是当天的行情特征。
- **板块列表混了三级行业且无法从数据里区分层级**，必须按名字白名单筛到
  申万一级，详见 ``LEVEL1_INDUSTRIES`` 上方的说明。
"""

from __future__ import annotations

import time
from datetime import datetime

import requests

from core.config import CST
from core.console import safe_print
from core.models import (
    FlowPoint,
    IndexQuote,
    MarketBundle,
    NothingToPublish,
    Sector,
    Stock,
)

# 主源在前，降级在后；``_get`` 会按 attempt 轮换。
HOSTS = ("push2delay.eastmoney.com", "push2.eastmoney.com")
CLIST = "/api/qt/clist/get"
FFLOW = "/api/qt/stock/fflow/kline/get"
ULIST = "/api/qt/ulist.np/get"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
REFERER = "https://data.eastmoney.com/"

TIMEOUT = 10
MAX_ATTEMPTS = 4
# 成功后的间隔足够小（一天就跑一次，总量二十来个请求），
# 失败后退避要够大，因为失败基本都是撞上了限流。
OK_PAUSE = 0.06
ERR_PAUSE = 0.4

# 沪深主板 + 创业板 + 科创板，``f:!2`` 排除 B 股与退市整理。
STOCK_FS = (
    "m:0+t:6+f:!2,m:0+t:13+f:!2,m:0+t:80+f:!2,"
    "m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:7+f:!2,m:1+t:3+f:!2"
)
SECTOR_FS = "m:90+t:2"

# f12 代码 f14 名称 f2 现价 f3 涨跌幅 f62 主力净流入 f184 主力净占比
STOCK_FIELDS = "f12,f14,f2,f3,f62,f184"
SECTOR_FIELDS = "f12,f14,f3,f62,f184"
INDEXES = ("1.000001", "0.399001", "0.399006")

# 一个完整交易日的曲线：09:31–11:30 与 13:01–15:00，各 120 个点。
# 实测末点时刻就等于当前时刻（接口虽叫 delay 但资金流 kline 是实时的），
# 所以「末点到没到 15:00」可以直接当作「收盘了没有」来用。
SESSION_CLOSE = "15:00"

# 收盘后再宽限几分钟，接口写完最后一个点需要一点时间。
# 过了这个点曲线还不完整，那就不是「还没收盘」而是上游滞后了——
# 两者的处理天差地别，见 ``build_bundle``。
DATA_DEADLINE = "15:05"

# 每页硬上限 100，给再大的 pz 也只回 100。板块共 496 个，五页取完。
PAGE_SIZE = 100
SECTOR_PAGES = 6

# 申万一级行业，31 个。
#
# 为什么必须写死这份名单：``m:90+t:2`` 把申万一级、二级、三级混在一起返回，
# 而**没有任何字段能区分层级**——代码段是历史分配顺序（BK12 里既有一级的
# 「电子」也有二级的「白酒Ⅱ」），罗马数字后缀只是重名时的消歧标记
# （「面板」没后缀却是三级）。
#
# 不筛的后果不是难看而是错：「电子 -143 亿」和它的子行业「半导体 -74 亿」
# 会各占一行，同一笔钱数两遍，榜单看着像五个行业在跌，其实是两个。
LEVEL1_INDUSTRIES = frozenset(
    {
        "农林牧渔", "基础化工", "钢铁", "有色金属", "电子", "家用电器",
        "食品饮料", "纺织服饰", "轻工制造", "医药生物", "公用事业",
        "交通运输", "房地产", "商贸零售", "社会服务", "综合", "建筑材料",
        "建筑装饰", "电力设备", "机械设备", "国防军工", "计算机", "传媒",
        "通信", "银行", "非银金融", "汽车", "煤炭", "石油石化", "环保",
        "美容护理",
    }
)


def session() -> requests.Session:
    client = requests.Session()
    client.headers.update({"User-Agent": USER_AGENT, "Referer": REFERER})
    return client


def _to_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _get(
    client: requests.Session, path: str, params: dict[str, str]
) -> dict | None:
    """取一个接口的 ``data``，按 host 轮换重试；全失败返回 None。

    「HTTP 200 但 data 为 null」是东财限流时的常见形态，必须和网络错误一样
    当作失败继续降级，否则会拿着空壳往下走。
    """
    problems: list[str] = []
    for attempt in range(MAX_ATTEMPTS):
        host = HOSTS[attempt % len(HOSTS)]
        try:
            response = client.get(
                f"https://{host}{path}", params=params, timeout=TIMEOUT
            )
            response.raise_for_status()
            data = response.json().get("data")
        except (requests.RequestException, ValueError) as error:
            problems.append(f"{host.split('.')[0]}:{type(error).__name__}")
            data = None
        else:
            if data is not None:
                time.sleep(OK_PAUSE)
                return data
            problems.append(f"{host.split('.')[0]}:空")
        time.sleep(ERR_PAUSE * (attempt + 1))

    safe_print(f"  采集失败 {path} {params.get('secid', params.get('fs', ''))}"
               f" · {problems}")
    return None


def _rows(data: dict | None) -> list[dict]:
    """排行榜的 ``diff``，个别参数组合下会退化成字典，统一成列表。"""
    diff = (data or {}).get("diff")
    if isinstance(diff, dict):
        return list(diff.values())
    return diff if isinstance(diff, list) else []


def _ranking(
    client: requests.Session,
    fs: str,
    fields: str,
    top: int,
    ascending: bool,
) -> list[dict]:
    """按主力净流入（f62）排序取榜。``ascending`` 为真时取净流出一端。"""
    return _rows(
        _get(
            client,
            CLIST,
            {
                "fid": "f62",
                "po": "0" if ascending else "1",
                "pz": str(top),
                "pn": "1",
                "np": "1",
                "fltt": "2",
                "invt": "2",
                "fs": fs,
                "fields": fields,
            },
        )
    )


def stock_secid(code: str) -> str:
    """沪市（6 开头，含 9 开头的 B 股）前缀 1，深市与北交所前缀 0。"""
    return f"{'1' if code[:1] in '69' else '0'}.{code}"


def sector_secid(code: str) -> str:
    """板块统一走 90 市场号。"""
    return f"90.{code}"


def fetch_flow_series(
    client: requests.Session, secid: str
) -> tuple[str, list[FlowPoint]]:
    """某标的分钟级累计主力净流入，返回（交易日, 曲线）。

    ``fields2`` 只要 f51（时间）与 f52（主力净流入）；其余档位（小单、中单、
    大单、超大单）画面上用不到，少要几个字段也少一分被限流的理由。

    交易日要一并带出来：接口在非交易时段返回的是**上一个交易日**的完整曲线，
    不校验就会把上周五的行情打上今天的日期发出去。
    """
    data = _get(
        client,
        FFLOW,
        {
            "secid": secid,
            "klt": "1",
            "lmt": "0",
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52",
        },
    )
    day = ""
    points: list[FlowPoint] = []
    for line in (data or {}).get("klines") or []:
        parts = str(line).split(",")
        if len(parts) < 2:
            continue
        stamp = parts[0]
        # "2026-08-17 09:31" → 日期与 "09:31"，画面上只用得到时刻。
        if " " in stamp:
            day, clock = stamp.split(" ")[0], stamp.split(" ")[1][:5]
        else:
            clock = stamp[:5]
        points.append({"time": clock, "net_inflow": _to_float(parts[1])})
    return day, points


def fetch_sectors(client: requests.Session) -> list[Sector]:
    """申万一级行业的当日资金流全表，按主力净流入从高到低。

    必须翻完所有页再筛：一级行业在按资金流排序的 496 条里是散布的，
    截前几页会漏掉。多出来的几个请求换的是「榜单互斥」这个正确性前提。
    """
    rows: list[dict] = []
    for page in range(1, SECTOR_PAGES + 1):
        page_rows = _rows(
            _get(
                client,
                CLIST,
                {
                    "fid": "f62",
                    "po": "1",
                    "pz": str(PAGE_SIZE),
                    "pn": str(page),
                    "np": "1",
                    "fltt": "2",
                    "invt": "2",
                    "fs": SECTOR_FS,
                    "fields": SECTOR_FIELDS,
                },
            )
        )
        rows.extend(page_rows)
        # 不满一页就是最后一页。据此收口，免得多请求一个空页——
        # 空 data 会被当成限流，白白重试四次还退避几秒。
        if len(page_rows) < PAGE_SIZE:
            break

    sectors: list[Sector] = [
        {
            "code": str(row.get("f12") or ""),
            "name": str(row.get("f14") or ""),
            "change_pct": _to_float(row.get("f3")),
            "net_inflow": _to_float(row.get("f62")),
            "net_ratio": _to_float(row.get("f184")),
            "series": [],
        }
        for row in rows
        if str(row.get("f14") or "") in LEVEL1_INDUSTRIES
    ]

    missing = len(LEVEL1_INDUSTRIES) - len(sectors)
    if missing:
        # 少几个不至于毁掉这一期，但说明上游改了名字，白名单该跟着更新。
        found = {sector["name"] for sector in sectors}
        safe_print(f"  警告：{missing} 个一级行业没匹配上 {sorted(LEVEL1_INDUSTRIES - found)}")

    sectors.sort(key=lambda sector: sector["net_inflow"], reverse=True)
    return sectors


def fetch_stocks(
    client: requests.Session, top: int = 8, ascending: bool = False
) -> list[Stock]:
    stocks: list[Stock] = []
    for row in _ranking(client, STOCK_FS, STOCK_FIELDS, top, ascending):
        code = str(row.get("f12") or "")
        if not code:
            continue
        stocks.append(
            {
                "code": code,
                "name": str(row.get("f14") or code),
                "price": _to_float(row.get("f2")),
                "change_pct": _to_float(row.get("f3")),
                "net_inflow": _to_float(row.get("f62")),
                "net_ratio": _to_float(row.get("f184")),
                "series": [],
            }
        )
    return stocks


def fetch_indexes(client: requests.Session) -> list[IndexQuote]:
    """三大指数快照，用批量接口一次拿全。"""
    data = _get(
        client,
        ULIST,
        {
            "secids": ",".join(INDEXES),
            "fields": "f12,f14,f2,f3",
            "fltt": "2",
            "invt": "2",
            "np": "1",
        },
    )
    return [
        {
            "code": str(row.get("f12") or ""),
            "name": str(row.get("f14") or ""),
            "price": _to_float(row.get("f2")),
            "change_pct": _to_float(row.get("f3")),
        }
        for row in _rows(data)
    ]


def _attach_series(
    client: requests.Session, items: list, secid_of, label: str
) -> tuple[str, str]:
    """就地补上分钟曲线，返回（交易日, 最晚时刻）。

    最晚时刻取各条曲线的最大值而非要求一致：个股盘中停牌会让它那条提前
    结束，那说明的是这只票停了，不是全市场收盘了。
    """
    day = ""
    last = ""
    for item in items:
        found, item["series"] = fetch_flow_series(client, secid_of(item["code"]))
        day = day or found
        if item["series"]:
            last = max(last, item["series"][-1]["time"])
    usable = sum(1 for item in items if item["series"])
    safe_print(f"  {label} {usable}/{len(items)} 条曲线，末点 {last or '—'}")
    return day, last


def fetch(stock_top: int = 6) -> dict[str, object]:
    """采集一期视频所需的全部资金流数据。

    行业**不做截断**：视频的板块段要让 31 个申万一级行业同场赛跑，缺哪个都
    会让「钱从哪流到哪」缺一块。封面与文案只取两端，那是 ``MarketBundle``
    的属性负责切的事，与采集无关。

    个股反过来必须截断：全 A 五千多只跑不动，各取榜首 ``stock_top`` 只。

    请求量约 ``10 + 31 + 2*stock_top``，默认 53 个，十几秒跑完。
    """
    client = session()

    safe_print("抓取三大指数 …")
    indexes = fetch_indexes(client)
    for index in indexes:
        safe_print(f"  {index['name']} {index['price']} ({index['change_pct']:+.2f}%)")

    safe_print("抓取行业板块资金流排名 …")
    sectors = fetch_sectors(client)
    safe_print(f"  匹配到 {len(sectors)} 个申万一级行业")
    for sector in sectors[:3]:
        safe_print(f"  流入 {sector['name']} {sector['net_inflow'] / 1e8:+.2f} 亿")
    for sector in sectors[:-4:-1]:
        safe_print(f"  流出 {sector['name']} {sector['net_inflow'] / 1e8:+.2f} 亿")

    safe_print("抓取个股资金流排名 …")
    stock_inflow = fetch_stocks(client, stock_top, ascending=False)
    stock_outflow = fetch_stocks(client, stock_top, ascending=True)

    safe_print("抓取分钟级资金流曲线 …")
    day = ""
    last = ""
    for items, secid_of, label in (
        (sectors, sector_secid, "行业板块"),
        (stock_inflow, stock_secid, "个股流入"),
        (stock_outflow, stock_secid, "个股流出"),
    ):
        found, clock = _attach_series(client, items, secid_of, label)
        day = day or found
        last = max(last, clock)

    return {
        "trading_date": day,
        "last_clock": last,
        "indexes": indexes,
        "sectors": sectors,
        "stock_inflow": stock_inflow,
        "stock_outflow": stock_outflow,
    }


def build_title(date_text: str, sectors: list[Sector]) -> str:
    """标题直接从数据拼，不走 LLM——这里全是事实，没有可改写的余地。"""
    if not sectors:
        return f"{date_text} A股资金流向"
    top = sectors[0]
    return (
        f"{date_text} A股主力资金：{top['name']}净流入 "
        f"{top['net_inflow'] / 1e8:.0f} 亿"
    )


class NotATradingDay(NothingToPublish):
    """今天没有行情可讲——周末与节假日。

    非交易时段接口照样返回**上一个交易日**的完整曲线，不校验就会把上周五的
    行情打上今天的日期发出去。
    """


class SessionNotClosed(NothingToPublish):
    """还没收盘，曲线只有半天。

    半天的曲线画出来和全天的一模一样，看不出是残的——标题还写着「当日
    累计」。宁可这一趟不出片，也不能发一支名不副实的视频。

    这属于「本来就没得发」：定时任务排在收盘后，只有手动触发才会撞上。
    """


class MarketDataLagging(RuntimeError):
    """已经收盘了，曲线却还没补齐。

    刻意不归到 ``NothingToPublish``：这一天本该有片子。安静跳过等于漏发一期
    还没人知道，所以要让这次运行留下失败记录，重跑一次通常就好了。
    """


def build_bundle(stock_top: int = 6) -> MarketBundle:
    """采集并装配成管线用的 ``MarketBundle``。

    宁可少发一期，也不发一期错的，所以数据不合格一律抛错。抛哪一种要看
    「今天本该有片子吗」：

    - 周末节假日 → ``NotATradingDay``，安静跳过，运行照样算成功。
    - 收盘前手动触发 → ``SessionNotClosed``，同上。
    - 收盘后曲线还不全 → ``MarketDataLagging``，让这次运行失败。
      这一天本该出片，静默跳过就成了「漏发一期还没人知道」。
    """
    date_text = datetime.now(CST).strftime("%Y-%m-%d")
    data = fetch(stock_top)

    # 先查日期：非交易日拿到的是上一交易日的**完整**曲线，
    # 时刻校验会放行，只有日期能识破。
    day = str(data.get("trading_date") or "")
    if day != date_text:
        raise NotATradingDay(
            f"接口给到的是 {day or '未知日期'} 的行情，今天是 {date_text}"
        )

    last = str(data.get("last_clock") or "")
    if last < SESSION_CLOSE:
        detail = f"曲线只到 {last or '空'}，不足一个完整交易日（需到 {SESSION_CLOSE}）"
        if datetime.now(CST).strftime("%H:%M") >= DATA_DEADLINE:
            raise MarketDataLagging(f"{detail}；此刻早已过 {DATA_DEADLINE}，上游滞后")
        raise SessionNotClosed(detail)

    sectors: list[Sector] = data["sectors"]  # type: ignore[assignment]

    return MarketBundle(
        slug=f"{date_text}-market-flow",
        date_text=date_text,
        title=build_title(date_text, sectors),
        indexes=data["indexes"],  # type: ignore[arg-type]
        sectors=sectors,
        stock_inflow=data["stock_inflow"],  # type: ignore[arg-type]
        stock_outflow=data["stock_outflow"],  # type: ignore[arg-type]
    )
