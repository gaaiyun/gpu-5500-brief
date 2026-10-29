"""What changed since the previous day's report. The daily push leads with this, and says so plainly on a quiet day."""
from __future__ import annotations

from datetime import date

# A rate move or a new unverified lead is worth listing, but it is not news about the price.
NEWS_TAGS = ("官方", "新报价", "网上挂价", "海外零售", "情报")
MAX_ITEMS = 8


def _coming_soon(state):
    check = next((c for c in state.get("checks", []) if c["source_id"] == "nvidia" and c.get("status") == "ok"), None)
    return check.get("signals", {}).get("coming_soon") if check else None


def daily_digest(state, baseline):
    board = state.get("price_board") or {}
    kinds = {r["id"]: r["kind"] for r in board.get("rows", [])}
    items = []
    if baseline and None not in (_coming_soon(state), _coming_soon(baseline)) and _coming_soon(state) != _coming_soon(baseline):
        items.append({"tag": "官方", "text": "NVIDIA 产品页 Coming Soon 标记变化，需人工核实是否开售"})
    for change in board.get("changes", []):
        if change["kind"] == "新报价":
            kind = kinds.get(change["id"])
            items.append({"tag": kind if kind in ("海外零售", "网上挂价") else "新报价", "text": change["text"]})
    fx, old_fx = state.get("fx") or {}, (baseline or {}).get("fx") or {}
    if fx.get("rates") and old_fx.get("rates") and fx.get("date") != old_fx.get("date") and fx.get("label") == old_fx.get("label"):
        moves = [c["text"] for c in board.get("changes", []) if c["kind"] == "汇率"]
        items.append({"tag": "汇率", "text": f"{fx['label']}（美元）{old_fx['rates']['USD']}→{fx['rates']['USD']}"
                                             + (f"；含税折算 {'，'.join(moves)}" if moves else "")})
    if baseline:
        feed, old_feed = state.get("feed") or {}, baseline.get("feed") or {}
        seen = {x["id"] for x in old_feed.get("items", [])}
        for item in feed.get("items", []):
            if item["id"] not in seen and item.get("age_days", 99) <= 3:
                items.append({"tag": "情报", "text": f"[{item['grade']} {item['grade_label']}] {item['title']}（{item['publisher']}）", "url": item["url"]})
        seen = {x["url"] for x in old_feed.get("leads", [])}
        leads = [x for x in feed.get("leads", []) if x["url"] not in seen]
        if leads:
            items.append({"tag": "线索", "text": f"{len(leads)} 条未核实线索，如：{leads[0]['title']}（{leads[0]['publisher']}）", "url": leads[0]["url"]})
        seen = {x["url"] for x in baseline.get("headlines", [])}
        heads = [x for x in state.get("headlines", []) if x["url"] not in seen]
        if heads:
            items.append({"tag": "新闻", "text": f"{len(heads)} 条大媒体新标题，如：{heads[0]['title']}（{heads[0]['publisher']}）", "url": heads[0]["url"]})
    quotes = [r for r in board.get("rows", []) if r["kind"] != "海外零售" or r.get("repriced")]
    last = max(quotes, key=lambda r: r["since"], default=None)
    days = (date.fromisoformat(state["date"]) - date.fromisoformat(last["since"])).days if last else None
    news = [i for i in items if i["tag"] in NEWS_TAGS]
    if news:
        headline = f"今日 {len(news)} 条新报价或新动态"
    elif last:
        headline = f"今日无新报价，距最近一次新报价 {days} 天（{last['label']}，{last['since']}）"
    else:
        headline = "今日无新报价"
    return {"headline": headline, "items": items[:MAX_ITEMS], "quiet": not news, "days_since_quote": days,
            "last_quote": {"label": last["label"], "date": last["since"]} if last else None}
