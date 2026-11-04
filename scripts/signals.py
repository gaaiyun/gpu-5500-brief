"""Signals that move more often than a verified price: what people online quote, what channels announce, how much the
card is being discussed, and what comes next. All of it is labelled unverified or derived; none of it enters the price range."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from intelligence import numeric_values

MENTION_DAYS = 14
MENTION_RANGE = (60_000, 200_000)
OTHER_CARDS = re.compile(r"5090|6000|5000|4500|4090|H20|H200|950PR|昇腾|华为|Ascend", re.I)
NUM = r"(\d{1,2}(?:\.\d{1,2})?)"
# "万" must mean yuan: 8万张 is a quantity and 1.14万美元 is another currency.
WAN = r"万(?!张|颗|块|片|枚|台|卡|人|美元|亿|个|套)"
MENTION_WAN = re.compile(rf"5500[^。；;！？!?\n]{{0,40}}?{NUM}\s*(?:万\s*元?\s*)?[—–\-~～至到]+\s*{NUM}\s*{WAN}|5500[^。；;！？!?\n]{{0,40}}?{NUM}\s*{WAN}", re.I)
MENTION_YUAN = re.compile(r"5500[^。；;！？!?\n]{0,40}?(\d{2,3},?\d{3})\s*元", re.I)
CHANNEL_WORDS = re.compile(r"到货|将到|现货|开放预定|可预定|接受预定|预定|预订|接单|入库|开售|上架|供货|备货|交付")
HEAT_DAYS = 30
TAKE_LIMIT = 160
DATE_WORDS = re.compile(r"\d{4}\s*年|\d{1,2}\s*月(?:\s*\d{1,2}\s*日)?|(?<!\d)\d{1,2}-\d{1,2}(?!\d)|\d+\s*天|Q\d|\d\s*季度")


def _mention(match):
    groups = [g for g in match.groups() if g]
    if not groups:
        return None
    if match.re is MENTION_YUAN:
        values = [int(groups[0].replace(",", ""))]
    else:
        values = [round(float(g) * 10000) for g in groups]
    if OTHER_CARDS.search(match.group(0)) or not all(MENTION_RANGE[0] <= v <= MENTION_RANGE[1] for v in values):
        return None
    return min(values), max(values)


def find_prices(text):
    """(low, high) per price printed right after the model name; a price attached to another card does not count."""
    found = []
    for pattern in (MENTION_WAN, MENTION_YUAN):
        for match in pattern.finditer(text or ""):
            price = _mention(match)
            if price and price not in found:
                found.append(price)
    return found


def collect_mentions(rows, old, today):
    """What articles and post snippets say the card costs, one row per publisher and price, kept for two weeks."""
    merged = {(m["publisher"], m["low"], m["high"]): m for m in (old or []) if isinstance(m, dict) and m.get("publisher")}
    for row in rows:
        published = str(row.get("published_at") or "")
        text = " ".join(str(row.get(k) or "") for k in ("title", "snippet", "text"))
        for low, high in find_prices(text) if published else []:
            key = (row.get("publisher") or "未标明", low, high)
            merged.setdefault(key, {"date": published, "publisher": key[0], "low": low, "high": high,
                                    "url": row.get("url", ""), "found_via": row.get("found_via", "")})
    start = (today - timedelta(days=MENTION_DAYS)).isoformat()
    kept = [m for m in merged.values() if start <= m["date"] <= today.isoformat()]
    return sorted(kept, key=lambda m: (m["date"], m["publisher"]), reverse=True)


def clean_mentions(rows):
    """Only well-formed rows reach the site; these come from search snippets and the cloud analyst."""
    kept = []
    for row in rows or []:
        try:
            low, high = int(row["low"]), int(row["high"])
            date.fromisoformat(row["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if MENTION_RANGE[0] <= low <= high <= MENTION_RANGE[1] and not re.search(r"<|>|javascript:", str(row.get("publisher", ""))):
            url = str(row.get("url") or "")
            kept.append({"date": row["date"], "publisher": str(row.get("publisher") or "未标明")[:40], "low": low, "high": high,
                         "url": url if url.startswith("https://") else "", "found_via": str(row.get("found_via") or "")[:30]})
    return kept


def mention_price(mention):
    low, high = mention["low"] / 10000, mention["high"] / 10000
    return f"{low:g}万元" if low == high else f"{low:g}万-{high:g}万元"


def channel_signals(leads):
    """Distributor posts saying stock is coming or orders are open. Their own marketing, so listed as claims."""
    rows = []
    for lead in leads:
        if lead.get("source_type") not in ("公众号", "社媒", "电商/渠道", "其他"):
            continue
        if "5500" in lead.get("title", "") and CHANNEL_WORDS.search(lead["title"]):
            rows.append({"date": lead.get("published_at", ""), "publisher": lead.get("publisher", ""), "title": lead["title"], "url": lead["url"]})
    return rows


def update_heat(old, rows, today):
    """Articles found per day. Search results are capped, so this is a relative gauge and never shrinks a day already counted."""
    seen = {}
    start = today - timedelta(days=7)
    for row in rows:
        day = row.get("published_at")
        if isinstance(day, str):
            try:
                day = date.fromisoformat(day)
            except ValueError:
                continue
        if not day or not start <= day <= today:
            continue
        key = re.sub(r"[\W_]+", "", str(row.get("title", ""))).casefold()
        kind = "wechat" if row.get("source_type") == "公众号" or row.get("found_via") == "搜狗微信" else "media"
        if key:
            seen.setdefault(day.isoformat(), {"media": set(), "wechat": set()})[kind].add(key)
    heat = dict(old or {})
    for day, kinds in seen.items():
        before = heat.get(day) or {}
        heat[day] = {k: max(int(before.get(k) or 0), len(v)) for k, v in kinds.items()}
    cutoff = (today - timedelta(days=HEAT_DAYS)).isoformat()
    return dict(sorted((d, v) for d, v in heat.items() if d >= cutoff))


def heat_text(heat, today):
    yesterday = (today - timedelta(days=1)).isoformat()
    day = (heat or {}).get(yesterday)
    if not day:
        return None
    week = [sum(heat.get((today - timedelta(days=n)).isoformat(), {}).values()) for n in range(2, 9)]
    average = sum(week) / 7
    total = day.get("media", 0) + day.get("wechat", 0)
    note = "明显升温" if average and total >= 2 * average and total >= 4 else ""
    return (f"昨日检索到 {total} 篇新文章（媒体 {day.get('media', 0)}、公众号 {day.get('wechat', 0)}），"
            f"此前 7 日日均 {average:.1f} 篇" + (f"，{note}" if note else "") + "。搜索结果有上限，只看相对变化。")


def calendar_text(calendar, today, limit=3):
    """The next dated events with a countdown; `why` says what to listen for."""
    upcoming = sorted((e for e in calendar or [] if date.fromisoformat(e["date"]) >= today), key=lambda e: e["date"])[:limit]
    parts = []
    for event in upcoming:
        days = (date.fromisoformat(event["date"]) - today).days
        when = "今天" if days == 0 else f"还有 {days} 天"
        parts.append(f"{event['date'][5:]} {event['label']}（{when}，{event['why']}）")
    return "；".join(parts) + "。" if parts else None


def clean_take(take, today, allowed):
    """The cloud analyst's note for the day. Stale, oversized or carrying a number the evidence lacks: it is not shown."""
    if not isinstance(take, dict):
        return None
    text = str(take.get("text") or "").strip()
    try:
        age = (today - date.fromisoformat(str(take.get("date")))).days
    except ValueError:
        return None
    if not text or not 0 <= age <= 1 or len(text) > TAKE_LIMIT or re.search(r"<|>|javascript:", text):
        return None
    # Dates and countdowns are not claims about the market; prices and quantities must already be in the evidence.
    if not numeric_values(DATE_WORDS.sub(" ", text)) <= allowed:
        return None
    return {"date": take["date"], "text": text}


def allowed_numbers(evidence, feed_items, rows):
    """Every figure the note may use: the evidence file, the checked feed items and today's price table."""
    return numeric_values(json.dumps([evidence.get("sources"), evidence.get("prices"), evidence.get("forecast"), evidence.get("supply"),
                                      feed_items, rows], ensure_ascii=False))


def extend_brief(state, evidence, today):
    """Add what is computed after the feed is loaded. The analyst's note leads; dated events and heat follow the supply line."""
    items = state["daily_brief"]["items"]
    feed = state.get("feed") or {}
    take = clean_take(feed.get("take"), today, allowed_numbers(evidence, feed.get("items"), (state.get("price_board") or {}).get("rows")))
    feed["take"] = take
    if take:
        items.insert(0, {"title": "今日点评", "text": f"{take['text']}（AI 据下列证据整理）"})
    after = next((i + 1 for i, b in enumerate(items) if b["title"] == "供应与交付"), len(items))
    events = calendar_text(evidence.get("calendar"), today)
    if events:
        items.insert(after, {"title": "接下来", "text": events})
        after += 1
    heat = heat_text(feed.get("heat"), today)
    if heat:
        items.insert(after, {"title": "讨论热度", "text": heat})
