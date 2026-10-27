"""Daily share page: one link that carries the image, the intelligence and every source link."""
from __future__ import annotations

from html import escape

from daily_card import pick_items

SITE = "https://gaaiyun.github.io/gpu-5500-brief/"


def page_url(day):
    return f"{SITE}daily/{day}.html"


def image_url(day):
    return f"{SITE}daily/{day}.png"


def body_html(state):
    """Plain tags only, so the same body renders in the share page and in a PushPlus message."""
    market = state["channel"]
    p, stats = market["latest"], market["stats"]
    day = state["date"]
    e = escape
    parts = [
        f"<p><b>渠道（{e(p['date'])}）</b>卖均 ¥{p['ask']:,}，买均 ¥{p['bid']:,}，中间值日变动 {stats['day_pct']:+.2f}%；"
        f"最低挂价 ¥{market['min_ask']:,}（交期 {e(market.get('delivery') or '未标明')}，原报价 {e(market.get('quote_date') or '未标明')}）。"
        f"来源：<a href=\"{e(market.get('homepage') or market['source_url'])}\">宽泛采销</a></p>",
        f"<p><img src=\"{e(image_url(day))}\" alt=\"RTX PRO 5500 行情日报 {e(day)}\" style=\"width:100%;height:auto\"></p>",
        "<h3>今日判断</h3>",
    ]
    for item in state["daily_brief"]["items"]:
        parts.append(f"<p><b>{e(item['title'])}</b>：{e(item['text'])}</p>")
    parts.append("<h3>市场情报</h3>")
    for n, item in enumerate(pick_items(state), 1):
        parts.append(
            f"<p><b>{n}. {e(item['title'])}</b>（{e(item['date'])}）<br>"
            f"事实：{e(item['summary'])}<br>"
            f"影响：{e(item['impact'])}<br>"
            f"跟进：{e(item['watch'])}<br>"
            f"来源：<a href=\"{e(item['url'])}\">{e(item['source'])}</a></p>")
    feed = [x for x in (state.get("feed") or {}).get("items", []) if x.get("age_days", 99) <= 14]
    if feed:
        parts.append("<h3>全网追踪（AI 读原文核对）</h3>")
        for item in feed[:6]:
            checks = "".join(f"<br>【{e(c['status'])}】{e(c['text'])}" + (f" <a href=\"{e(c['ref'])}\">出处</a>" if c["ref"] else "")
                             for c in item.get("claims", []))
            parts.append(
                f"<p><b>[{e(item.get('tier', '核实'))}·{e(item['grade_label'])}] {e(item['title'])}</b>（{e(item['published_at'])}，{e(item['publisher'])}）<br>"
                f"事实：{e(item['summary'])}<br>影响：{e(item['impact'])}<br>跟进：{e(item['watch'])}{checks}<br>"
                f"来源：<a href=\"{e(item['url'])}\">{e(item['publisher'])}</a></p>")
    parts.append("<p>口径：渠道价为宽泛采销平台参考，不是成交价；媒体价格未统一税费、数量和交期。没有新证据时不改预测。</p>")
    parts.append(f"<p>完整曲线、报价对照与研究报告：<a href=\"{SITE}\">{SITE}</a></p>")
    return "\n".join(parts)


def page_html(state):
    day = state["date"]
    p = state["channel"]["latest"]
    title = f"RTX PRO 5500 大陆行情日报 {day}"
    summary = f"卖均 ¥{p['ask']:,} · 买均 ¥{p['bid']:,} · 6 条带来源的市场情报"
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title><meta name="description" content="{escape(summary)}">
<meta property="og:title" content="{escape(title)}"><meta property="og:description" content="{escape(summary)}">
<meta property="og:image" content="{escape(image_url(day))}">
<style>
:root{{--bg:#f3f5f8;--card:#fff;--ink:#111827;--text:#374151;--muted:#6b7280;--link:#2563eb;--line:#e5e7eb}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f172a;--card:#111827;--ink:#f3f4f6;--text:#d1d5db;--muted:#9ca3af;--link:#60a5fa;--line:#1f2937}}}}
body{{margin:0;background:var(--bg);color:var(--text);font:17px/1.75 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}}
main{{max-width:760px;margin:0 auto;padding:16px;background:var(--card);min-height:100vh;box-sizing:border-box}}
h1{{color:var(--ink);font-size:24px;line-height:1.35;margin:4px 0 12px}} h3{{color:var(--ink);font-size:20px;margin:24px 0 6px;padding-top:14px;border-top:1px solid var(--line)}}
p{{margin:10px 0;overflow-wrap:anywhere}} a{{color:var(--link)}} img{{border-radius:10px;display:block}}
</style></head>
<body><main><h1>{escape(title)}</h1>
{body_html(state)}
</main></body></html>
"""
