"""Render the daily image pushed to the DingTalk group."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont

W, M, GAP = 1080, 44, 16
BG = (243, 245, 248)
CARD = (255, 255, 255)
INK = (17, 24, 39)
TEXT = (55, 65, 81)
MUTED = (107, 114, 128)
LINE = (229, 231, 235)
HEAD = (15, 23, 42)
ASK = (37, 99, 235)
BID = (225, 29, 72)
UP = (225, 29, 72)
DOWN = (5, 150, 105)
AMBER = (217, 119, 6)
SITE = "https://gaaiyun.github.io/gpu-5500-brief/"
SCENARIO_COLORS = {"soft": (209, 250, 229), "base": (219, 234, 254), "tight": (254, 243, 199)}
CHIP = {"reuters": (255, 237, 213), "trendforce": (224, 231, 255), "smm": (220, 252, 231),
        "tansun": (243, 232, 255), "cls": (254, 226, 226), "nvidia": (236, 252, 203)}

FONT_SETS = [  # (regular, bold, ttc index)
    ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),
    ("C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simhei.ttf", 0),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
]


class Fonts:
    def __init__(self):
        found = next((s for s in FONT_SETS if Path(s[0]).exists()), None)
        if not found:
            raise RuntimeError("缺少中文字体，无法生成日报图")
        self.regular, self.bold, self.index = found
        bold_ok = Path(self.bold).exists()
        self.bold = self.bold if bold_ok else self.regular
        # SimHei/WenQuanYi lack a half-width yen glyph.
        self.yen = "¥" if ("msyh" in self.regular or "Noto" in self.regular) else "￥"
        self.cache = {}

    def __call__(self, size, bold=False):
        key = (size, bold)
        if key not in self.cache:
            self.cache[key] = ImageFont.truetype(self.bold if bold else self.regular, size, index=self.index)
        return self.cache[key]


def wrap(draw, text, font, width, max_lines=4):
    lines, line = [], ""
    for char in text:
        # Closing punctuation stays on the line it ends.
        if draw.textlength(line + char, font=font) > width and line and char not in "，。；：、）」》%":
            lines.append(line)
            line = char
        else:
            line += char
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…"
    return lines


def pick_items(state):
    from intelligence import SOURCE_LABELS
    items = [dict(x, source=x.get("source") or SOURCE_LABELS.get(x["source_id"], x["source_id"])) for x in (state.get("intelligence") or {}).get("items", []) if x["source_id"] != "qudao"]
    dated = sorted([x for x in items if x["source_id"] != "nvidia"], key=lambda x: x["date"], reverse=True)
    return dated + [x for x in items if x["source_id"] == "nvidia"]


def render(evidence, state, output):
    market = state.get("channel")
    if not market:
        raise ValueError("日报图需要有效渠道快照")
    F = Fonts()
    yuan = lambda v: f"{F.yen}{v:,.0f}"
    wan = lambda v: f"{v / 10000:.2f}万"
    p, stats = market["latest"], market["stats"]
    forecast, review = evidence["forecast"], state["forecast_review"]
    img = Image.new("RGBA", (W, 4200), BG)
    d = ImageDraw.Draw(img)

    def card(y0, y1):
        d.rounded_rectangle([M, y0, W - M, y1], radius=18, fill=CARD, outline=LINE)

    def chip(x, y, text, fill, color=INK, size=19):
        width = d.textlength(text, font=F(size)) + 22
        d.rounded_rectangle([x, y, x + width, y + size + 14], radius=(size + 14) // 2, fill=fill)
        d.text((x + 11, y + 7 + size // 2), text, font=F(size), fill=color, anchor="lm")
        return x + width + 8

    # Header band.
    d.rectangle([0, 0, W, 214], fill=HEAD)
    d.text((M, 40), "RTX PRO 5500 · 大陆行情日报", font=F(44, True), fill=(255, 255, 255))
    d.text((M, 104), f"84GB GDDR7 工作站卡 · 人民币/张 · 渠道数据截至 {p['date']}", font=F(22), fill=(148, 163, 184))
    d.text((W - M, 46), state["date"], font=F(32, True), fill=(255, 255, 255), anchor="ra")
    official = next((c for c in state["checks"] if c["source_id"] == "nvidia"), {})
    official_text = "官方 Coming Soon" if official.get("status") == "ok" and official.get("signals", {}).get("coming_soon") else "官方状态待复核"
    status = {"low_confidence": "预测 条件情景", "review_required": "预测 待复核", "expired": "预测 已到期"}[review["status"]]
    healthy = sum(c["status"] == "ok" for c in state["checks"])
    x = M
    for text in (official_text, status, f"来源 {healthy}/{len(state['checks'])} 可访问", f"渠道 {'已更新' if state.get('channel_status') == 'ok' else '沿用上次'}"):
        x = chip(x, 152, text, (30, 41, 59), (226, 232, 240))
    y = 238

    # KPI cards.
    cw = (W - 2 * M - 3 * GAP) / 4
    kpis = [("卖方均价", yuan(p["ask"]), f"日 {stats['day_pct']:+.2f}% · 周 {stats['week_pct']:+.2f}%", ASK, UP if stats["day_pct"] >= 0 else DOWN),
            ("买方均价", yuan(p["bid"]), f"求购最高 {yuan(market['max_bid'])}", BID, MUTED),
            ("买卖差", yuan(stats["spread"]), f"占中间值 {stats['spread_pct']:.2f}%", INK, MUTED),
            ("最低挂价", yuan(market["min_ask"]), f"{market.get('delivery') or '交期未标明'}", INK, AMBER)]
    for i, (label, value, sub, color, sub_color) in enumerate(kpis):
        x0 = M + i * (cw + GAP)
        d.rounded_rectangle([x0, y, x0 + cw, y + 142], radius=16, fill=CARD, outline=LINE)
        d.rectangle([x0 + 18, y + 22, x0 + 22, y + 44], fill=color)
        d.text((x0 + 32, y + 33), label, font=F(21), fill=MUTED, anchor="lm")
        d.text((x0 + 18, y + 58), value, font=F(36, True), fill=color)
        d.text((x0 + 18, y + 108), sub, font=F(18), fill=sub_color)
    y += 142 + GAP

    # 14-day chart.
    rows = market["series"][-14:]
    card(y, y + 430)
    d.text((M + 24, y + 22), "14日渠道买卖均价", font=F(26, True), fill=INK)
    d.text((M + 24, y + 62), f"区间高 {wan(stats['period_high'])} · 区间低 {wan(stats['period_low'])} · 柱形为挂牌活跃度", font=F(19), fill=MUTED)
    lx = W - M - 24
    for label, color in (("买方均价", BID), ("卖方均价", ASK)):
        lx -= d.textlength(label, font=F(19))
        d.text((lx, y + 30), label, font=F(19), fill=TEXT)
        d.rounded_rectangle([lx - 30, y + 40, lx - 8, y + 45], radius=2, fill=color)
        lx -= 50
    left, right, top, bottom = M + 104, W - M - 120, y + 112, y + 340
    lo_v = min(r["bid"] for r in rows)
    hi_v = max(r["ask"] for r in rows)
    pad = max((hi_v - lo_v) * .18, 500)
    lo, hi = lo_v - pad, hi_v + pad
    xs = lambda i: left + i / max(len(rows) - 1, 1) * (right - left)
    ys = lambda v: bottom - (v - lo) / (hi - lo) * (bottom - top)
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        d.line([(left, ys(v)), (right, ys(v))], fill=LINE, width=1)
        d.text((left - 14, ys(v)), wan(v), font=F(18), fill=MUTED, anchor="rm")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.polygon([(xs(i), ys(r["ask"])) for i, r in enumerate(rows)] + [(xs(i), ys(r["bid"])) for i, r in reversed(list(enumerate(rows)))], fill=(37, 99, 235, 26))
    max_act = max(max(r["activity"] for r in rows), 1)
    for i, r in enumerate(rows):
        h = r["activity"] / max_act * 34
        od.rounded_rectangle([xs(i) - 7, bottom + 48 - h, xs(i) + 7, bottom + 48], radius=3, fill=(148, 163, 184, 120))
    img.alpha_composite(overlay)
    d = ImageDraw.Draw(img)
    for field, color in (("ask", ASK), ("bid", BID)):
        pts = [(xs(i), ys(r[field])) for i, r in enumerate(rows)]
        d.line(pts, fill=color, width=4, joint="curve")
        ex, ey = pts[-1]
        d.ellipse([ex - 7, ey - 7, ex + 7, ey + 7], fill=CARD, outline=color, width=4)
        d.text((ex + 16, ey), yuan(rows[-1][field]), font=F(20, True), fill=color, anchor="lm")
    step = max(1, (len(rows) - 1) // 4)
    for i in sorted(set(list(range(0, len(rows), step)) + [len(rows) - 1])):
        if i != len(rows) - 1 and len(rows) - 1 - i < step / 2:
            continue
        d.text((xs(i), bottom + 58), rows[i]["date"][5:].replace("-", "/"), font=F(18), fill=MUTED, anchor="ma")
    y += 430 + GAP

    # Price map: scenario bands with current reference points.
    base = next(s for s in forecast["scenarios"] if s["id"] == "base")
    card(y, y + 340)
    d.text((M + 24, y + 22), "价格坐标 · 未来30-60天预售情景", font=F(26, True), fill=INK)
    range_text = f"基准 {base['low'] / 10000:.1f}-{base['high'] / 10000:.1f} 万/张" if review["numeric_forecast_active"] else "原预测已到期"
    d.text((W - M - 24, y + 24), range_text, font=F(26, True), fill=ASK, anchor="ra")
    scen = forecast["scenarios"]
    v0, v1 = min(s["low"] for s in scen), max(s["high"] for s in scen)
    ax0, ax1, axy = M + 40, W - M - 40, y + 236
    px = lambda v: ax0 + (min(max(v, v0), v1) - v0) / (v1 - v0) * (ax1 - ax0)
    for s in scen:
        d.rectangle([px(s["low"]), axy - 16, px(s["high"]), axy + 16], fill=SCENARIO_COLORS.get(s["id"], LINE))
        d.text(((px(s["low"]) + px(s["high"])) / 2, axy + 30), s["name"].split(" / ")[0], font=F(18), fill=TEXT, anchor="ma")
    for v in range(v0, v1 + 1, 5000):
        d.text((px(v), axy + 62), f"{v / 10000:g}万", font=F(16), fill=MUTED, anchor="ma")
    ti = next((x for x in evidence["prices"] if x["id"] == "theinformation_price"), None)
    if ti:
        d.line([(px(ti["low_cny"]), axy - 24), (px(ti["high_cny"]), axy - 24)], fill=AMBER, width=4)
    marks = [(market["min_ask"], "最低挂价", AMBER), (p["bid"], "平台买均", BID), (p["ask"], "平台卖均", ASK),
             (forecast["anchor_cny"], "SMM预售", INK)]
    if ti:
        marks.append(((ti["low_cny"] + ti["high_cny"]) / 2, "The Information", AMBER))
    marks.sort(key=lambda m: m[0])
    # Stack labels on as many rows as needed so close prices never overprint.
    rows_right = []
    for v, label, color in marks:
        mx = px(v)
        d.line([(mx, axy - 16), (mx, axy + 16)], fill=color, width=3)
        text = f"{label} {wan(v) if label != 'The Information' else '8.5-9万'}"
        width = d.textlength(text, font=F(18, True))
        left_edge = min(max(mx - width / 2, M + 24), W - M - 24 - width)
        level = next((i for i, r in enumerate(rows_right) if left_edge > r + 10), len(rows_right))
        if level == len(rows_right):
            rows_right.append(0)
        rows_right[level] = left_edge + width
        ty = axy - 44 - level * 30
        d.line([(mx, ty + 11), (mx, axy - 16)], fill=color, width=1)
        d.text((left_edge, ty), text, font=F(18, True), fill=color, anchor="lm")
    y += 340 + GAP

    # Today's judgement from the daily brief.
    brief = {b["title"]: b["text"] for b in state["daily_brief"]["items"]}
    lines_src = [(k, brief[k]) for k in ("报价位置", "平台变化", "交期差异", "下一步核实") if k in brief]
    body = [(k, wrap(d, t, F(21), W - 2 * M - 160, 3)) for k, t in lines_src]
    h = 74 + sum(len(ls) * 32 + 14 for _, ls in body)
    card(y, y + h)
    d.text((M + 24, y + 22), "今日判断", font=F(26, True), fill=INK)
    ty = y + 70
    for k, ls in body:
        d.text((M + 24, ty), k, font=F(21, True), fill=ASK)
        for line in ls:
            d.text((M + 140, ty), line, font=F(21), fill=TEXT)
            ty += 32
        ty += 14
    y += h + GAP

    # Intelligence cards.
    items = pick_items(state)
    d.text((M + 4, y + 8), f"市场情报 · {len(items)} 条", font=F(28, True), fill=INK)
    d.text((W - M, y + 14), "事实 / 影响 / 跟进 / 来源", font=F(19), fill=MUTED, anchor="ra")
    y += 58
    inner = W - 2 * M - 48
    for item in items:
        summary = wrap(d, item["summary"], F(21), inner, 4)
        impact = wrap(d, item["impact"], F(21), inner - 70, 3)
        watch = wrap(d, item["watch"], F(20), inner - 70, 2)
        h = 120 + len(summary) * 32 + 10 + len(impact) * 32 + 8 + len(watch) * 30 + 44
        card(y, y + h)
        x = chip(M + 24, y + 20, item.get("source") or item["source_id"], CHIP.get(item["source_id"], LINE), INK, 18)
        d.text((x + 4, y + 36), f"{item['date']} · {item['kind']}", font=F(18), fill=MUTED, anchor="lm")
        d.text((M + 24, y + 66), item["title"], font=F(25, True), fill=INK)
        ty = y + 110
        for line in summary:
            d.text((M + 24, ty), line, font=F(21), fill=TEXT)
            ty += 32
        ty += 10
        d.text((M + 24, ty), "影响", font=F(21, True), fill=ASK)
        for line in impact:
            d.text((M + 94, ty), line, font=F(21), fill=INK)
            ty += 32
        ty += 8
        d.text((M + 24, ty), "跟进", font=F(20, True), fill=AMBER)
        for line in watch:
            d.text((M + 94, ty), line, font=F(20), fill=TEXT)
            ty += 30
        d.line([(M + 24, ty + 8), (W - M - 24, ty + 8)], fill=LINE, width=1)
        d.text((M + 24, ty + 18), f"来源：{item.get('source') or item['source_id']} · {urlparse(item['url']).netloc}", font=F(17), fill=MUTED)
        y += h + 12

    # Footer.
    y += 10
    note = "口径：渠道价为宽泛采销平台参考，不是成交价；媒体价格未统一税费、数量和交期。没有新证据时不改预测。"
    for line in wrap(d, note, F(18), W - 2 * M, 2):
        d.text((M, y), line, font=F(18), fill=MUTED)
        y += 28
    generated = datetime.fromisoformat(state["checked_at"]).strftime("%Y-%m-%d %H:%M")
    d.text((M, y + 6), f"采集 {generated} 北京时间 · 完整情报与报告 {SITE}", font=F(18), fill=ASK)
    y += 6 + 28 + M
    img.crop((0, 0, W, int(y))).convert("RGB").save(output, optimize=True)
    return output
