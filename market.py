"""A股行情抓取（腾讯行情免费接口）。

注: 原用东方财富 push2 接口，实测会静默断连，改为腾讯 qt.gtimg.cn + proxy.finance.qq.com。
"""

import requests

from douyin import DouyinError

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

INDEX_CODES = {
    "上证指数": "sh000001",
    "深证成指": "sz399001",
    "创业板指": "sz399006",
    "科创50": "sh000688",
}
QUOTE_URL = "https://qt.gtimg.cn/q={codes}"
RANK_URL = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/mktHs/rank"
# t=01/averatio 行业板块、t=02/averatio 概念板块（按涨跌幅排序）
SECTOR_TYPES = {"industry": "01", "concept": "02"}


def _fetch_indices() -> list:
    resp = requests.get(
        QUOTE_URL.format(codes=",".join(INDEX_CODES.values())),
        headers={"User-Agent": UA}, timeout=15)
    resp.raise_for_status()
    resp.encoding = "gbk"
    out = []
    for line in resp.text.strip().split(";"):
        if "=" not in line:
            continue
        p = line.split('="', 1)[1].rstrip('"').split("~")
        if len(p) < 33:
            continue
        out.append({
            "name": p[1],
            "price": float(p[3]) if p[3] else None,
            "change": float(p[31]) if p[31] else None,
            "change_pct": float(p[32]) if p[32] else None,
        })
    return out


def _fetch_sectors(type_: str, limit: int = 15) -> list:
    resp = requests.get(
        RANK_URL,
        params={"l": limit, "p": 1, "t": f"{type_}/averatio"},
        headers={"User-Agent": UA}, timeout=15)
    resp.raise_for_status()
    data = resp.json().get("data") or []
    out = []
    for item in data:
        zdf = item.get("bd_zdf")
        out.append({
            "name": item.get("bd_name", ""),
            "change_pct": float(zdf) if zdf else None,
        })
    return out


def fetch_market_data() -> dict:
    """返回 {indices, industry, concept}。任一接口失败抛 DouyinError。"""
    try:
        return {
            "indices": _fetch_indices(),
            "industry": _fetch_sectors(SECTOR_TYPES["industry"]),
            "concept": _fetch_sectors(SECTOR_TYPES["concept"]),
        }
    except DouyinError:
        raise
    except Exception as e:
        raise DouyinError(f"行情接口获取失败: {e}")
