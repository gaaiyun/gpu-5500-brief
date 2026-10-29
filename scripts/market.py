"""Normalize the public channel feed and retain its statistical limitations."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta

API_URL = "https://qudao.co/api/trends?timeframe=daily"


def number(value, name, allow_zero=False):
    if isinstance(value, bool):
        raise ValueError(f"{name}: invalid boolean")
    n = float(value)
    if not math.isfinite(n) or n < 0 or (n == 0 and not allow_zero):
        raise ValueError(f"{name}: invalid number")
    return int(n) if n.is_integer() else n


def normalize_product(item):
    rows = []
    seen = set()
    for point in item.get("chartData", []):
        day = date.fromisoformat(point["dateStr"])
        if day.isoformat() in seen:
            raise ValueError("渠道数据存在重复日期")
        seen.add(day.isoformat())
        rows.append({"date": day.isoformat(), "mid": number(point["avgPrice"], "mid"),
                     "ask": number(point["avgSupplyPrice"], "ask"),
                     "bid": number(point["avgDemandPrice"], "bid"),
                     "high": number(point["high"], "high"), "low": number(point["low"], "low"),
                     "activity": number(point["volume"], "activity", True)})
    rows.sort(key=lambda x: x["date"])
    if not rows:
        raise ValueError("目标型号没有日序列")
    for row in rows:
        if row["ask"] < row["bid"] or row["high"] < row["low"]:
            raise ValueError("渠道字段大小关系异常")
    last = rows[-1]
    previous = rows[-2] if len(rows) > 1 else last
    week_ago = rows[-8] if len(rows) >= 8 else rows[0]
    fixed = sum(abs(p["ask"] - p["mid"] * 1.015) <= 1 and abs(p["bid"] - p["mid"] * .985) <= 1 for p in rows)
    recurring = len(rows) > 2 and all((rows[i]["activity"] - rows[i-1]["activity"]) % 45 == 32 for i in range(1,len(rows)))
    attrs = item.get("spec_attributes") or {}
    return {"name": item["name"], "model": item.get("model", ""), "unit": item.get("unit", "张"),
            "series": rows, "latest": last,
            "min_ask": number(item["currentMinSupply"], "min_ask"),
            "max_bid": number(item["currentMaxDemand"], "max_bid"),
            "quote_date": attrs.get("最新报价日期"), "delivery": attrs.get("期货交期", "未标明"),
            "condition": attrs.get("货况说明", "未标明"),
            "stats": {"spread": last["ask"] - last["bid"],
                      "spread_pct": (last["ask"] - last["bid"]) / ((last["ask"] + last["bid"]) / 2) * 100,
                      "day_change": last["mid"]-previous["mid"],
                      "day_pct": (last["mid"] / previous["mid"]-1)*100,
                      "week_pct": (last["mid"] / week_ago["mid"]-1)*100,
                      "period_high": max(p["high"] for p in rows), "period_low": min(p["low"] for p in rows),
                      "fixed_offset_points": fixed, "point_count": len(rows), "activity_cycle": recurring}}


def parse_channel(payload, checked_at):
    if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(payload.get("data"), list):
        raise ValueError("渠道接口没有返回成功的数据集")
    products = payload["data"]
    candidates = [x for x in products if re.search(r"RTX\s*PRO\s*5500", x.get("name", ""), re.I) and "84" in x.get("name", "")]
    if len(candidates) != 1:
        raise ValueError("目标型号缺失或匹配不唯一")
    target = normalize_product(candidates[0])
    now = datetime.fromisoformat(checked_at).date()
    latest_date = date.fromisoformat(target["latest"]["date"])
    if latest_date > now:
        raise ValueError("渠道数据日期在未来")
    target.update(source_url=API_URL, homepage="https://qudao.co/", collected_at=checked_at,
                  age_days=(now-latest_date).days, verification="platform_reference",
                  independent_market_samples=False,
                  data_sha256=hashlib.sha256(json.dumps(candidates[0],sort_keys=True,ensure_ascii=False).encode()).hexdigest())
    watchlist = []
    patterns = [r"RTX PRO 6000 D 84", r"RTX PRO 5000 72", r"RTX PRO 6000 工作站版 96", r"RTX 5090 32GB 涡轮", r"RTX 5090 32GB 风扇"]
    for pattern in patterns:
        # Some models are listed twice; the entry carrying a quote date is the one a seller actually priced.
        matches = sorted((x for x in products if re.search(pattern,x.get("name", ""), re.I)),
                         key=lambda x: not (x.get("spec_attributes") or {}).get("最新报价日期"))
        candidate = matches[0] if matches else None
        if candidate:
            try:
                product = normalize_product(candidate)
                watchlist.append({k:product[k] for k in ["name","model","unit","latest","stats","quote_date","min_ask","condition"]})
            except (ValueError,KeyError,TypeError):
                continue
    target["watchlist"] = watchlist
    target["audit"] = [
        {"title":"均价关系", "detail":f"{target['stats']['fixed_offset_points']}/{len(target['series'])} 个日点符合卖均≈中间值×1.015、买均≈中间值×0.985。两条线不视为独立价格样本。"},
        {"title":"低价交付", "detail":f"最低挂价对应 {target['condition']}；交期 {target['delivery']}；原报价日期 {target['quote_date'] or '未标明'}。"},
        {"title":"活跃度口径", "detail":"接口 volume 对应平台页面的挂牌活跃度；本次仅保留为平台活跃度指标。"},
        {"title":"统计方法", "detail":"卖家样本、去重、权重及成交凭据未公开；保留完整序列与采集时间供后续比对。"}]
    if target["stats"]["activity_cycle"]:
        target["audit"].append({"title":"数量规律", "detail":"本次序列活跃度按固定步长循环，作为数据质量提示；不能据此判断真实交易需求。"})
    return target


def series_values(market):
    return [[r[k] for k in ("mid","ask","bid","high","low","activity")] for r in market["series"]]


def channel_template(market, previous):
    """Flag a curve that is a formula or yesterday's numbers under shifted dates; such a curve carries no daily move."""
    stats = market["stats"]
    formula = stats["point_count"] >= 7 and stats["fixed_offset_points"] == stats["point_count"]
    same_values = bool(previous and previous.get("series")) and series_values(previous) == series_values(market)
    if same_values and previous["latest"]["date"] == market["latest"]["date"]:
        # A rerun on the same day sees identical dates; keep what the first run of the day found.
        redated = (previous.get("template") or {}).get("redated", False)
    else:
        redated = same_values
    reasons = []
    if redated:
        reasons.append(f"{stats['point_count']} 个日点与上次采集逐点相同，只是日期顺延")
    if formula:
        reasons.append("卖均、买均恰为中间值×1.015、×0.985")
    if stats.get("activity_cycle"):
        reasons.append("挂牌活跃度按固定步长循环")
    return {"synthetic": redated or formula, "redated": redated, "formula": formula, "reasons": reasons}


def daily_brief(evidence, market, previous, board=None):
    anchor = evidence["forecast"]["anchor_cny"]
    items = []
    domestic = (board or {}).get("domestic")
    if domestic:
        items.append({"title":"大陆报价", "text":f"已披露的大陆单卡报价在 {domestic['low']:,}-{domestic['high']:,} 元之间（{domestic['count']} 条来源），"
                                              f"最新一条是 {domestic['latest_label']}（{domestic['latest_date']}）。"})
    rows = {r["id"]: r for r in (board or {}).get("rows", [])}
    usd = rows.get("reuters_usd")
    if usd and usd["cny"]:
        fx = board["fx"]
        items.append({"title":"折算对照", "text":f"路透所述订单价 {usd['native']}，按{fx['label']} {fx['rates']['USD']}（{fx['date']}）折合 {usd['cny']:,} 元，"
                                              f"加 13% 增值税约 {usd['cny_vat']:,} 元。汇率变了这个数才变，不是新报价。"})
    if board:
        items.append({"title":"今日变化", "text":board["summary"]})
    if not market:
        items.append({"title":"渠道数据", "text":"本轮未取得有效渠道记录，保留公开报道中的预售锚点。"})
        return {"items":items, "channel_changes":[]}
    p, stats = market["latest"], market["stats"]
    template = market.get("template") or {}
    channel = f"最低挂价 {market['min_ask']:,} 元为{market['condition']}，交期 {market['delivery']}，原报价 {market['quote_date'] or '未标明'}。"
    if template.get("synthetic"):
        channel += "平台 14 日曲线" + "，".join(template["reasons"]) + "，不计入涨跌。"
    else:
        channel += f"平台中间值较上日 {stats['day_change']:+,} 元（{stats['day_pct']:+.2f}%），较七日前 {stats['week_pct']:+.2f}%。"
    items.append({"title":"渠道挂价", "text":channel})
    items.append({"title":"下一步核实", "text":f"取得短交期货源的当日报价与含税口径，与 {anchor:,} 元预售锚点对照。"})
    old = previous or {}
    changes = []
    fields = [("min_ask","最低挂价"),("quote_date","原报价日期"),("delivery","交期")]
    if not template.get("synthetic"):
        fields += [("ask","卖方均价"),("bid","买方均价"),("mid","中间值"),("activity","挂牌活跃度")]
    for key,label in fields:
        before, after = (old.get(key), market.get(key)) if key in ("min_ask","quote_date","delivery") else (old.get("latest", {}).get(key), p[key])
        if before is not None and before != after:
            change = {"field":key,"label":label,"before":before,"after":after}
            if isinstance(after, (int, float)):
                change["delta"] = after - before
            changes.append(change)
    return {"items":items, "channel_changes":changes}
