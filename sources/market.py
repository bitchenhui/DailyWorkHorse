"""A 股资金流采集：行业板块与个股的分钟级主力净流入曲线。

选源结论（实测，别再重走一遍）：

- **数据全在东方财富**，``fflow/kline`` 一个接口就能给出全天每分钟一个点的
  主力净流入序列，板块与个股共用，只是 ``secid`` 前缀不同。
- **主源用 ``push2delay``**，``push2`` 只作降级。前者是延时行情，限流宽松得多；
  日报收盘后才跑，延时对我们毫无影响。
- **``push2his`` 直接放弃**，实测 0/5 全部超时。
- 早先「东财不可用」的判断是错的：那是**突发限流**，头几个请求放行、打快了就
  把 IP 关几分钟。按本文件的节奏走，实测 8/8 一次通过、全程 3 秒。

两个必须记住的数据语义：

- **序列是累计值不是每分钟增量**。09:31 那个点是开盘头一分钟的净流入，
  15:00 那个点等于全天合计。想要每分钟净额得自己做差分。
- **主力 = 超大单 + 大单**，与中小单净额之和恒为零，所以「主力流入」的另一面
  永远是散户在接盘，这是接口的定义决定的，不是当天的行情特征。
"""

from __future__ import annotations

import time
from typing import TypedDict

import requests

from core.console import safe_print

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


class FlowPoint(TypedDict):
    """分钟序列上的一个点。``net_inflow`` 是**当日累计**主力净流入（元）。"""

    time: str
    net_inflow: float


class Sector(TypedDict):
    code: str
    name: str
    change_pct: float
    net_inflow: float
    net_ratio: float
    series: list[FlowPoint]


class Stock(TypedDict):
    code: str
    name: str
    price: float
    change_pct: float
    net_inflow: float
    net_ratio: float
    series: list[FlowPoint]


class IndexQuote(TypedDict):
    code: str
    name: str
    price: float
    change_pct: float


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


def fetch_flow_series(client: requests.Session, secid: str) -> list[FlowPoint]:
    """某标的当日的分钟级累计主力净流入，拿不到时返回空列表。

    ``fields2`` 只要 f51（时间）与 f52（主力净流入）；其余档位（小单、中单、
    大单、超大单）画面上用不到，少要几个字段也少一分被限流的理由。
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
    points: list[FlowPoint] = []
    for line in (data or {}).get("klines") or []:
        parts = str(line).split(",")
        if len(parts) < 2:
            continue
        stamp = parts[0]
        # "2026-08-17 09:31" → "09:31"，画面上只用得到时刻。
        clock = stamp.split(" ")[1][:5] if " " in stamp else stamp[:5]
        points.append({"time": clock, "net_inflow": _to_float(parts[1])})
    return points


def _base_name(name: str) -> str:
    """去掉分类层级后缀，用于识别同一板块的重复条目。

    东财把「白酒Ⅱ」「白酒Ⅲ」当成两个板块返回，数值一模一样，
    直接上榜就是同一条信息占两行。
    """
    return name.rstrip("ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ") or name


def fetch_sectors(
    client: requests.Session, top: int = 5, ascending: bool = False
) -> list[Sector]:
    # 多要几条，去重后才够 top 个。
    rows = _ranking(client, SECTOR_FS, SECTOR_FIELDS, top + 5, ascending)

    sectors: list[Sector] = []
    seen: set[str] = set()
    for row in rows:
        code = str(row.get("f12") or "")
        if not code:
            continue
        base = _base_name(str(row.get("f14") or code))
        if base in seen:
            continue
        seen.add(base)
        sectors.append(
            {
                "code": code,
                # 用去掉层级后缀的名字：画面上「白酒」比「白酒Ⅱ」干净，
                # 而层级信息对观众没有意义。
                "name": base,
                "change_pct": _to_float(row.get("f3")),
                "net_inflow": _to_float(row.get("f62")),
                "net_ratio": _to_float(row.get("f184")),
                "series": [],
            }
        )
        if len(sectors) == top:
            break
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
) -> None:
    """就地补上分钟曲线，并报告有多少条真的拿到了。"""
    for item in items:
        item["series"] = fetch_flow_series(client, secid_of(item["code"]))
    usable = sum(1 for item in items if item["series"])
    safe_print(f"  {label} {usable}/{len(items)} 条曲线")


def fetch(sector_top: int = 5, stock_top: int = 6) -> dict[str, object]:
    """采集一期视频所需的全部资金流数据。

    默认条数对着竖屏画面定：板块段 5+5 行、个股段 6+6 行，再多就得压缩字号。
    请求量是 ``5 + 2*(sector_top + stock_top)``，默认 27 个，几秒钟跑完。
    """
    client = session()

    safe_print("抓取三大指数 …")
    indexes = fetch_indexes(client)
    for index in indexes:
        safe_print(f"  {index['name']} {index['price']} ({index['change_pct']:+.2f}%)")

    safe_print("抓取行业板块资金流排名 …")
    sector_inflow = fetch_sectors(client, sector_top, ascending=False)
    sector_outflow = fetch_sectors(client, sector_top, ascending=True)
    for sector in sector_inflow[:3]:
        safe_print(f"  流入 {sector['name']} {sector['net_inflow'] / 1e8:+.2f} 亿")
    for sector in sector_outflow[:3]:
        safe_print(f"  流出 {sector['name']} {sector['net_inflow'] / 1e8:+.2f} 亿")

    safe_print("抓取个股资金流排名 …")
    stock_inflow = fetch_stocks(client, stock_top, ascending=False)
    stock_outflow = fetch_stocks(client, stock_top, ascending=True)

    safe_print("抓取分钟级资金流曲线 …")
    _attach_series(client, sector_inflow, lambda code: f"90.{code}", "板块流入")
    _attach_series(client, sector_outflow, lambda code: f"90.{code}", "板块流出")
    _attach_series(client, stock_inflow, stock_secid, "个股流入")
    _attach_series(client, stock_outflow, stock_secid, "个股流出")

    return {
        "indexes": indexes,
        "sector_inflow": sector_inflow,
        "sector_outflow": sector_outflow,
        "stock_inflow": stock_inflow,
        "stock_outflow": stock_outflow,
    }
