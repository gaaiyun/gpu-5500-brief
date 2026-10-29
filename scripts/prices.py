"""Price evidence board: every dated quote with its age, foreign prices converted at the day's exchange rate.

A converted price moves with the exchange rate; it is never presented as a new quote.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date, datetime, timedelta, timezone

CN_VAT = 0.13
FX_HISTORY_URL = ("https://www.chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew?startDate={start}&endDate={end}"
                  "&currency=USD/CNY,EUR/CNY,GBP/CNY&pageNum=1&pageSize=50")
FX_HISTORY_DAYS = 60
SERIES_DAYS = 30
QUOTE_MAX_AGE = 30
QUOTE_TAX = ("含税", "不含税", "未知")
QUOTE_SOURCES = ("供应商报价", "客户询价", "同行群", "闲鱼", "其他")
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


def parse_fx_history(payload):
    """Central parity history: {date: {currency: yuan per unit}}. Only the parity is kept so the trend has one source."""
    names = payload["data"].get("searchlist") or payload["data"]["head"]
    history = {}
    for record in payload["records"]:
        found = {n.split("/")[0]: float(v) for n, v in zip(names, record["values"]) if v not in ("", "---")}
        rates = {c: found[c] for c in RATE_BOUNDS if c in found}
        if len(rates) == len(RATE_BOUNDS) and all(RATE_BOUNDS[c][0] <= v <= RATE_BOUNDS[c][1] for c, v in rates.items()):
            history[date.fromisoformat(record["date"]).isoformat()] = rates
    return history


def merge_fx_history(old, new, today):
    start = (today - timedelta(days=FX_HISTORY_DAYS)).isoformat()
    merged = {d: r for d, r in {**(old or {}), **new}.items() if d >= start}
    return dict(sorted(merged.items()))


def load_quotes(text, today):
    """Team-collected quotes from data/quotes.csv. Returns (rows, rejected); a bad line never stops the run."""
    rows, rejected = [], []
    lines = [l for l in (text or "").splitlines() if l.strip() and not l.lstrip().startswith("#") and not l.startswith("日期")]
    for line in lines:
        try:
            cells = next(csv.reader(io.StringIO(line)))
            cells += [""] * (7 - len(cells))
            day, price, tax, delivery, qty, source, note = (c.strip() for c in cells[:7])
            quoted = date.fromisoformat(day)
            if quoted > today:
                raise ValueError("日期在未来")
            if (today - quoted).days > QUOTE_MAX_AGE:
                continue
            value = float(price.replace(",", ""))
            if not 30_000 <= value <= 300_000:
                raise ValueError("单价不在 3万-30万元")
            if tax not in QUOTE_TAX or source not in QUOTE_SOURCES:
                raise ValueError("含税或来源类型不在可选项内")
            if qty and not qty.isdigit():
                raise ValueError("数量必须是整数")
            if re.search(r"[<>]|javascript:", line):
                raise ValueError("含标记或脚本")
            rows.append({"id": "quote:" + hashlib.sha1(line.strip().encode()).hexdigest()[:10], "date": quoted.isoformat(),
                         "price": int(value), "tax": tax, "delivery": delivery[:20], "qty": qty, "source": source, "note": note[:40]})
        except (ValueError, StopIteration) as error:
            rejected.append({"line": line[:80], "reason": str(error)})
    return sorted(rows, key=lambda r: r["date"], reverse=True), rejected


def build_series(evidence, market, fx_history, quotes, feed_items, today):
    """Daily reference values using only what was known on each day, so the line never benefits from hindsight."""
    events = [(p["observed_at"], p["board"], p.get("value_cny", p.get("low_cny")), p.get("value_cny", p.get("high_cny")))
              for p in evidence["prices"] if p.get("board") and "value_usd" not in p]
    events += [(x["published_at"], x["publisher"], *x["price_cny"]) for x in feed_items
               if x.get("price_cny") and x.get("grade") in ("A", "B")]
    usd = next((p for p in evidence["prices"] if p.get("board") and "value_usd" in p), None)
    channel = (market.get("quote_date") or market["latest"]["date"], market["min_ask"]) if market else None
    dated = [e[0] for e in events] + ([usd["observed_at"]] if usd else []) + [q["date"] for q in quotes]
    if not dated:
        return []
    start = max(today - timedelta(days=SERIES_DAYS - 1), date.fromisoformat(min(dated)))
    rates = sorted((d, r["USD"]) for d, r in (fx_history or {}).items())
    points = []
    for offset in range((today - start).days + 1):
        day = (start + timedelta(days=offset)).isoformat()
        known = [e for e in events if e[0] <= day]
        rate = next((r for d, r in reversed(rates) if d <= day), None)
        points.append({"date": day,
                       "low": min((e[2] for e in known), default=None), "high": max((e[3] for e in known), default=None),
                       "channel": channel[1] if channel and channel[0] <= day else None,
                       "usd_vat": round(usd["value_usd"] * rate * (1 + CN_VAT)) if usd and rate and usd["observed_at"] <= day else None,
                       "events": [e[1] for e in events if e[0] == day] + ([usd["board"]] if usd and usd["observed_at"] == day else []),
                       "team": [q["price"] for q in quotes if q["date"] == day]})
    return points


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


def build_board(evidence, market, fx, listings, feed_items, today, previous, quotes=()):
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

    # Team quotes are the freshest mainland prices but unverified: listed and dated, kept out of the published range.
    team = [_row(q["id"], f"团队询价 · {q['source']}", "团队询价", "", q["date"], today, money(q["price"]), q["price"],
                 note="，".join(x for x in (q["tax"], f"交期{q['delivery']}" if q["delivery"] else "", f"{q['qty']}张" if q["qty"] else "", q["note"]) if x)
                 + "；未公开核实") for q in quotes]
    domestic = sorted((r for r in rows if not r["converted"] and r["low"]), key=lambda r: r["date"], reverse=True)
    latest = max(domestic, key=lambda r: r["date"], default=None)
    board = {"rows": domestic + team + [r for r in rows if r["converted"] or not r["low"]], "fx": fx,
             "domestic": {"low": min(r["low"] for r in domestic), "high": max(r["high"] for r in domestic),
                          "count": len(domestic), "latest_label": latest["label"], "latest_date": latest["date"]} if domestic else None}
    # Parity and ECB rates differ by up to 1%; a switch of provider is not a market move.
    same_rate_source = ((previous or {}).get("fx") or {}).get("provider") == (fx or {}).get("provider")
    board["changes"] = [c for c in _changes(board["rows"], previous) if c["kind"] != "汇率" or same_rate_source]
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
