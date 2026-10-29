"""Price evidence board: every dated quote with its age, foreign prices converted at the day's exchange rate.

A converted price moves with the exchange rate; it is never presented as a new quote.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone

CN_VAT = 0.13
FX_PROVIDERS = (
    ("chinamoney", "人民币汇率中间价", "https://www.chinamoney.com.cn/r/cms/www/chinamoney/data/fx/ccpr.json"),
    ("frankfurter", "欧洲央行参考汇率", "https://api.frankfurter.dev/v1/latest?base=USD&symbols=CNY,EUR,GBP"),
    ("erapi", "ExchangeRate-API 日汇率", "https://open.er-api.com/v6/latest/USD"),
)
# Yuan per unit; anything outside is a parsing error, not a market move.
RATE_BOUNDS = {"USD": (5, 9), "EUR": (5, 11), "GBP": (6, 13)}
SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}
FEED_PRICE_MAX_AGE = 30


def parse_fx(provider, payload):
    """Return ({currency: yuan per unit}, rate date)."""
    if provider == "chinamoney":
        found = {r.get("vrtEName", "").split("/")[0]: float(r["price"]) for r in payload["records"]}
        rates, day = {c: found[c] for c in RATE_BOUNDS}, payload["data"]["lastDate"][:10]
    else:
        usd = payload["rates"]
        rates = {"USD": usd["CNY"], "EUR": usd["CNY"] / usd["EUR"], "GBP": usd["CNY"] / usd["GBP"]}
        day = payload["date"] if provider == "frankfurter" else \
            datetime.fromtimestamp(payload["time_last_update_unix"], timezone.utc).date().isoformat()
    date.fromisoformat(day)
    for currency, (low, high) in RATE_BOUNDS.items():
        if not low <= rates[currency] <= high:
            raise ValueError(f"{currency} 汇率 {rates[currency]} 超出合理范围")
    return {c: round(v, 4) for c, v in rates.items()}, day


def fetch_fx(get_json, previous, checked_at):
    errors = []
    for provider, label, url in FX_PROVIDERS:
        try:
            rates, day = parse_fx(provider, get_json(url))
            return {"status": "ok", "provider": provider, "label": label, "url": url, "date": day, "rates": rates,
                    "checked_at": checked_at, "error": "；".join(errors)}
        except Exception as error:
            errors.append(f"{provider}: {str(error)[:100]}")
    if previous and previous.get("rates"):
        return dict(previous, status="carried", checked_at=checked_at, error="；".join(errors))
    return {"status": "failed", "rates": None, "checked_at": checked_at, "error": "；".join(errors)}


def _offers(node):
    if isinstance(node, list):
        for item in node:
            yield from _offers(item)
    elif isinstance(node, dict):
        if node.get("@type") in ("Offer", "AggregateOffer"):
            yield node
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from _offers(value)


def parse_listing(html, currency):
    """Lowest schema.org offer price in the page's JSON-LD for the given currency."""
    found = []
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(block, strict=False)
        except ValueError:
            continue
        for offer in _offers(data):
            value = offer.get("lowPrice", offer.get("price"))
            if offer.get("priceCurrency") == currency and value not in (None, ""):
                found.append(float(str(value).replace(",", "")))
    if not found:
        raise ValueError(f"页面结构化数据里没有 {currency} 报价")
    return min(found)


def check_listing(listing, previous, get_text, checked_at):
    today = checked_at[:10]
    base = previous or {"price": listing["price"], "price_since": listing["price_seen_at"], "last_success_at": None}
    try:
        price = parse_listing(get_text(listing["url"]), listing["currency"])
        # A wildly different number is more likely an accessory or a parsing slip than a repricing.
        if not .5 <= price / listing["price"] <= 2:
            raise ValueError(f"页面价 {price} 与登记价 {listing['price']} 相差过大，需人工复核")
        result = {"id": listing["id"], "status": "ok", "price": price, "checked_at": checked_at, "last_success_at": checked_at,
                  "price_since": base["price_since"]}
        if price != base["price"]:
            result.update(price_since=today, previous_price=base["price"])
        elif base.get("previous_price"):
            result["previous_price"] = base["previous_price"]
        return result
    except Exception as error:
        return {**base, "id": listing["id"], "status": "failed", "checked_at": checked_at, "error": str(error)[:200]}


def money(value):
    return f"¥{value:,.0f}"


def _age(day, today):
    return (today - date.fromisoformat(day)).days


def _row(rid, label, kind, url, day, today, native, low, high=None, note="", quote_key="", since=None):
    high = low if high is None else high
    text = money(low) if low == high else f"{money(low)}–{high:,.0f}"
    return {"id": rid, "label": label, "kind": kind, "url": url, "date": day, "age_days": _age(day, today),
            "since": since or day, "native": native, "low": low, "high": high, "cny": None, "cny_vat": None,
            "converted": False, "text": text, "note": note, "quote_key": quote_key or native}


def _converted(row, cny):
    vat = round(cny * (1 + CN_VAT))
    return dict(row, cny=round(cny), cny_vat=vat, low=vat, high=vat, converted=True,
                text=f"≈{money(vat)} 含税")


def build_board(evidence, market, fx, listings, feed_items, today, previous):
    sources = {s["id"]: s for s in evidence["sources"]}
    rates = (fx or {}).get("rates")
    rows = []
    if market:
        quote_date = market.get("quote_date") or market["latest"]["date"]
        rows.append(_row("channel_min_ask", "宽泛采销最低挂价", "渠道挂牌", market.get("homepage") or market["source_url"],
                         quote_date, today, money(market["min_ask"]), market["min_ask"],
                         note=f"{market.get('condition') or '货况未标明'}，交期{market.get('delivery') or '未标明'}",
                         quote_key=f"{market['min_ask']}@{quote_date}"))
    for p in evidence["prices"]:
        if not p.get("board"):
            continue
        url = sources[p["source_id"]]["url"]
        if "value_usd" in p:
            row = _row(p["id"], p["board"], "订单报道", url, p["observed_at"], today, f"${p['value_usd']:,}", 0,
                       note="匿名信源；按当日汇率折算，不是新报价，未含关税", quote_key=f"{p['id']}:{p['value_usd']}")
            rows.append(_converted(row, p["value_usd"] * rates["USD"]) if rates else dict(row, low=None, high=None, text=row["native"]))
            continue
        low, high = p.get("value_cny", p.get("low_cny")), p.get("value_cny", p.get("high_cny"))
        rows.append(_row(p["id"], p["board"], "媒体报道", url, p["observed_at"], today,
                         money(low) if low == high else f"{money(low)}–{high:,}", low, high, note=p.get("board_note", "")))
    # Feed prices only enter once the sweep traced them to the article and graded the source A or B.
    for item in feed_items:
        price = item.get("price_cny")
        if not price or item.get("grade") not in ("A", "B") or item.get("age_days", 99) > FEED_PRICE_MAX_AGE:
            continue
        rows.append(_row(f"feed:{item['id']}", item["publisher"], "媒体报道", item["url"], item["published_at"], today,
                         money(price[0]) if price[0] == price[1] else f"{money(price[0])}–{price[1]:,}", price[0], price[1],
                         note=item["title"][:30], quote_key=f"{price[0]}-{price[1]}"))
    states = {x["id"]: x for x in listings}
    for listing in evidence.get("listings", []):
        state = states.get(listing["id"]) or {"price": listing["price"], "price_since": listing["price_seen_at"]}
        price, symbol = state["price"], SYMBOLS[listing["currency"]]
        native = f"{symbol}{price:,.2f}（含当地增值税 {listing['vat_rate'] * 100:.0f}%）"
        row = _row(listing["id"], listing["label"], "海外零售", listing["url"], state["price_since"], today, native, 0,
                   note=listing["note"], quote_key=f"{price}{listing['currency']}")
        # The first sighting of a listing is when tracking began, not a repricing.
        row.update(checked=(state.get("last_success_at") or "")[:10] or None, check_status=state.get("status", "ok"),
                   repriced=bool(state.get("previous_price")))
        cny = price / (1 + listing["vat_rate"]) * rates[listing["currency"]] if rates else None
        rows.append(_converted(row, cny) if cny else dict(row, low=None, high=None, text=native))

    domestic = sorted((r for r in rows if not r["converted"] and r["low"]), key=lambda r: r["date"], reverse=True)
    latest = max(domestic, key=lambda r: r["date"], default=None)
    board = {"rows": domestic + [r for r in rows if r["converted"] or not r["low"]], "fx": fx,
             "domestic": {"low": min(r["low"] for r in domestic), "high": max(r["high"] for r in domestic),
                          "count": len(domestic), "latest_label": latest["label"], "latest_date": latest["date"]} if domestic else None}
    board["changes"] = _changes(board["rows"], previous)
    board["summary"] = _summary(board, fx)
    return board


def _changes(rows, previous):
    if not previous:
        return []
    old = {r["id"]: r for r in previous.get("rows", [])}
    changes = []
    for row in rows:
        before = old.get(row["id"])
        if before is None:
            changes.append({"id": row["id"], "label": row["label"], "kind": "新报价", "text": f"新增 {row['label']} {row['native']}"})
        elif before["quote_key"] != row["quote_key"]:
            changes.append({"id": row["id"], "label": row["label"], "kind": "新报价",
                            "text": f"{row['label']} {before['native']} → {row['native']}"})
        elif row["converted"] and before.get("cny_vat") and row["cny_vat"] and before["cny_vat"] != row["cny_vat"]:
            delta = row["cny_vat"] - before["cny_vat"]
            changes.append({"id": row["id"], "label": row["label"], "kind": "汇率", "delta": delta,
                            "text": f"{row['label']} {delta:+,} 元"})
    return changes


def _summary(board, fx):
    quotes = [c["text"] for c in board["changes"] if c["kind"] == "新报价"]
    moves = [c["text"] for c in board["changes"] if c["kind"] == "汇率"]
    if quotes:
        parts = ["新报价：" + "；".join(quotes)]
    else:
        latest = max((r for r in board["rows"] if r["kind"] != "海外零售" or r["repriced"]), key=lambda r: r["since"], default=None)
        parts = [f"今日无新报价；最近一次报价更新是 {latest['label']}（{latest['since']}）" if latest else "今日无新报价"]
    status = (fx or {}).get("status")
    if status == "failed":
        parts.append("汇率未取得，海外价格只列原币")
    elif moves:
        parts.append(f"汇率折算（含税）变动：{'，'.join(moves)}（{fx['label']} {fx['date']}）")
    elif status == "carried":
        parts.append(f"汇率沿用 {fx['date']} 的{fx['label']}")
    return "。".join(parts) + "。"
