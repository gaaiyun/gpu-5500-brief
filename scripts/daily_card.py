"""Render the daily image pushed to the DingTalk group."""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont

W, M, GAP = 1080, 40, 18
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
# Type scale. Body text is sized for reading in a phone chat bubble, not for print.
T_TITLE, T_H2, T_H3, T_BODY, T_SMALL, T_TINY = 54, 36, 33, 29, 25, 22
LH = 44  # body line height

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
    # Numbers, dates and Latin words wrap as a unit; CJK wraps per character.
    for token in re.findall(r"[A-Za-z0-9.,%+\-/:~¥￥]+|.", text):
        # Closing punctuation stays on the line it ends.
        if draw.textlength(line + token, font=font) > width and line.strip() and token not in "，。；：、）」》%":
            lines.append(line)
            line = token.lstrip()
        else:
            line += token
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
    img = Image.new("RGBA", (W, 7000), BG)
    d = ImageDraw.Draw(img)
    PAD = 28  # inner card padding

    def card(y0, y1):
        d.rounded_rectangle([M, y0, W - M, y1], radius=20, fill=CARD, outline=LINE)

    def chip(x, y, text, fill, color=INK, size=T_TINY):
        width = d.textlength(text, font=F(size)) + 26
        d.rounded_rectangle([x, y, x + width, y + size + 18], radius=(size + 18) // 2, fill=fill)
        d.text((x + 13, y + 9 + size // 2), text, font=F(size), fill=color, anchor="lm")
        return x + width + 10

    # Header band.
    d.rectangle([0, 0, W, 268], fill=HEAD)
    d.text((M, 36), "RTX PRO 5500 大陆行情日报", font=F(T_TITLE, True), fill=(255, 255, 255))
    d.text((M, 112), f"{state['date']} · 84GB · 人民币/张 · 渠道截至 {p['date'][5:]}", font=F(T_SMALL), fill=(148, 163, 184))
    official = next((c for c in state["checks"] if c["source_id"] == "nvidia"), {})
    official_text = "官方 Coming Soon" if official.get("status") == "ok" and official.get("signals", {}).get("coming_soon") else "官方状态待复核"
    status = {"low_confidence": "预测 条件情景", "review_required": "预测 待复核", "expired": "预测 已到期"}[review["status"]]
    healthy = sum(c["status"] == "ok" for c in state["checks"])
    x = M
    for text in (official_text, status, f"来源 {healthy}/{len(state['checks'])} 可访问"):
        x = chip(x, 182, text, (30, 41, 59), (226, 232, 240))
    y = 268 + GAP + 6

    # KPI cards, 2 x 2.
    cw = (W - 2 * M - GAP) / 2
    kpis = [("卖方均价", yuan(p["ask"]), f"日 {stats['day_pct']:+.2f}%  周 {stats['week_pct']:+.2f}%", ASK, UP if stats["day_pct"] >= 0 else DOWN),
            ("买方均价", yuan(p["bid"]), f"求购最高 {yuan(market['max_bid'])}", BID, MUTED),
            ("买卖差", yuan(stats["spread"]), f"占中间值 {stats['spread_pct']:.2f}%", INK, MUTED),
            ("最低挂价", yuan(market["min_ask"]), f"交期 {market.get('delivery') or '未标明'}", INK, AMBER)]
    kh = 176
    for i, (label, value, sub, color, sub_color) in enumerate(kpis):
        x0 = M + (i % 2) * (cw + GAP)
        y0 = y + (i // 2) * (kh + GAP)
        d.rounded_rectangle([x0, y0, x0 + cw, y0 + kh], radius=20, fill=CARD, outline=LINE)
        d.rectangle([x0 + PAD, y0 + 26, x0 + PAD + 6, y0 + 54], fill=color)
        d.text((x0 + PAD + 18, y0 + 40), label, font=F(T_SMALL), fill=MUTED, anchor="lm")
        d.text((x0 + PAD, y0 + 66), value, font=F(52, True), fill=color)
        d.text((x0 + PAD, y0 + 134), sub, font=F(T_TINY), fill=sub_color)
    y += 2 * kh + GAP + GAP

    # 14-day chart.
    rows = market["series"][-14:]
    ch = 560
    card(y, y + ch)
    d.text((M + PAD, y + 24), "14日渠道买卖均价", font=F(T_H2, True), fill=INK)
    d.text((M + PAD, y + 78), f"区间高 {wan(stats['period_high'])} · 区间低 {wan(stats['period_low'])} · 柱形为挂牌活跃度", font=F(T_TINY), fill=MUTED)
    lx = W - M - PAD
    for label, color in (("买方均价", BID), ("卖方均价", ASK)):
        lx -= d.textlength(label, font=F(T_TINY))
        d.text((lx, y + 32), label, font=F(T_TINY), fill=TEXT)
        d.rounded_rectangle([lx - 34, y + 44, lx - 10, y + 50], radius=3, fill=color)
        lx -= 58
    left, right, top, bottom = M + 120, W - M - 170, y + 140, y + 430
    lo_v = min(r["bid"] for r in rows)
    hi_v = max(r["ask"] for r in rows)
    pad = max((hi_v - lo_v) * .18, 500)
    lo, hi = lo_v - pad, hi_v + pad
    xs = lambda i: left + i / max(len(rows) - 1, 1) * (right - left)
    ys = lambda v: bottom - (v - lo) / (hi - lo) * (bottom - top)
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        d.line([(left, ys(v)), (right, ys(v))], fill=LINE, width=1)
        d.text((left - 16, ys(v)), wan(v), font=F(T_TINY), fill=MUTED, anchor="rm")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.polygon([(xs(i), ys(r["ask"])) for i, r in enumerate(rows)] + [(xs(i), ys(r["bid"])) for i, r in reversed(list(enumerate(rows)))], fill=(37, 99, 235, 26))
    max_act = max(max(r["activity"] for r in rows), 1)
    for i, r in enumerate(rows):
        h = r["activity"] / max_act * 40
        od.rounded_rectangle([xs(i) - 8, bottom + 58 - h, xs(i) + 8, bottom + 58], radius=3, fill=(148, 163, 184, 120))
    img.alpha_composite(overlay)
    d = ImageDraw.Draw(img)
    for field, color in (("ask", ASK), ("bid", BID)):
        pts = [(xs(i), ys(r[field])) for i, r in enumerate(rows)]
        d.line(pts, fill=color, width=5, joint="curve")
        ex, ey = pts[-1]
        d.ellipse([ex - 8, ey - 8, ex + 8, ey + 8], fill=CARD, outline=color, width=5)
        d.text((ex + 18, ey), yuan(rows[-1][field]), font=F(T_SMALL, True), fill=color, anchor="lm")
    step = max(1, (len(rows) - 1) // 4)
    for i in sorted(set(list(range(0, len(rows), step)) + [len(rows) - 1])):
        if i != len(rows) - 1 and len(rows) - 1 - i < step / 2:
            continue
        d.text((xs(i), bottom + 70), rows[i]["date"][5:].replace("-", "/"), font=F(T_TINY), fill=MUTED, anchor="ma")
    y += ch + GAP

    # Price map: scenario bands with current reference points.
    base = next(s for s in forecast["scenarios"] if s["id"] == "base")
    scen = forecast["scenarios"]
    v0, v1 = min(s["low"] for s in scen), max(s["high"] for s in scen)
    ax0, ax1 = M + 44, W - M - 44
    px = lambda v: ax0 + (min(max(v, v0), v1) - v0) / (v1 - v0) * (ax1 - ax0)
    ti = next((x for x in evidence["prices"] if x["id"] == "theinformation_price"), None)
    marks = [(market["min_ask"], "最低挂价", AMBER), (p["bid"], "平台买均", BID), (p["ask"], "平台卖均", ASK),
             (forecast["anchor_cny"], "SMM预售", INK)]
    if ti:
        marks.append(((ti["low_cny"] + ti["high_cny"]) / 2, "The Information", AMBER))
    marks.sort(key=lambda m: m[0])
    # Stack labels on as many rows as needed so close prices never overprint.
    placed, rows_right = [], []
    for v, label, color in marks:
        mx = px(v)
        text = f"{label} {wan(v) if label != 'The Information' else '8.5-9万'}"
        width = d.textlength(text, font=F(T_TINY, True))
        left_edge = min(max(mx - width / 2, M + PAD), W - M - PAD - width)
        level = next((i for i, r in enumerate(rows_right) if left_edge > r + 12), len(rows_right))
        if level == len(rows_right):
            rows_right.append(0)
        rows_right[level] = left_edge + width
        placed.append((mx, left_edge, level, text, color))
    axy = y + 100 + len(rows_right) * 38 + 34
    ph = axy - y + 118
    card(y, y + ph)
    d.text((M + PAD, y + 24), "价格坐标 · 30-60天预售情景", font=F(T_H2, True), fill=INK)
    range_text = f"基准 {base['low'] / 10000:.1f}-{base['high'] / 10000:.1f}万" if review["numeric_forecast_active"] else "原预测已到期"
    d.text((W - M - PAD, y + 26), range_text, font=F(T_H2, True), fill=ASK, anchor="ra")
    for s in scen:
        d.rectangle([px(s["low"]), axy - 18, px(s["high"]), axy + 18], fill=SCENARIO_COLORS.get(s["id"], LINE))
        d.text(((px(s["low"]) + px(s["high"])) / 2, axy + 32), s["name"].split(" / ")[0], font=F(T_TINY), fill=TEXT, anchor="ma")
    for v in range(v0, v1 + 1, 10000):
        d.text((px(v), axy + 74), f"{v / 10000:g}万", font=F(20), fill=MUTED, anchor="ma")
    if ti:
        d.line([(px(ti["low_cny"]), axy - 27), (px(ti["high_cny"]), axy - 27)], fill=AMBER, width=5)
    for mx, left_edge, level, text, color in placed:
        ty = axy - 52 - level * 38
        d.line([(mx, axy - 18), (mx, axy + 18)], fill=color, width=3)
        d.line([(mx, ty + 14), (mx, axy - 18)], fill=color, width=1)
        d.text((left_edge, ty), text, font=F(T_TINY, True), fill=color, anchor="lm")
    y += ph + GAP

    # Today's judgement from the daily brief.
    brief = {b["title"]: b["text"] for b in state["daily_brief"]["items"]}
    lines_src = [(k, brief[k]) for k in ("报价位置", "平台变化", "交期差异", "下一步核实") if k in brief]
    label_w = d.textlength("下一步核实", font=F(T_BODY, True)) + 20
    text_w = W - 2 * M - 2 * PAD - label_w
    body = [(k, wrap(d, t, F(T_BODY), text_w, 3)) for k, t in lines_src]
    h = 92 + sum(len(ls) * LH + 16 for _, ls in body) + 8
    card(y, y + h)
    d.text((M + PAD, y + 24), "今日判断", font=F(T_H2, True), fill=INK)
    ty = y + 92
    for k, ls in body:
        d.text((M + PAD, ty), k, font=F(T_BODY, True), fill=ASK)
        for line in ls:
            d.text((M + PAD + label_w, ty), line, font=F(T_BODY), fill=TEXT)
            ty += LH
        ty += 16
    y += h + GAP

    # Intelligence cards.
    items = pick_items(state)
    d.text((M + 4, y + 10), f"市场情报 · {len(items)} 条", font=F(T_H2, True), fill=INK)
    y += 72
    tag_w = d.textlength("影响", font=F(T_BODY, True)) + 18
    inner = W - 2 * M - 2 * PAD
    for item in items:
        title = wrap(d, item["title"], F(T_H3, True), inner, 2)
        summary = wrap(d, item["summary"], F(T_BODY), inner, 5)
        impact = wrap(d, item["impact"], F(T_BODY), inner - tag_w, 4)
        watch = wrap(d, item["watch"], F(T_SMALL), inner - tag_w, 2)
        source = wrap(d, f"来源：{item['source']} · {urlparse(item['url']).netloc}", F(T_TINY), inner, 2)
        h = (24 + 44 + 18 + len(title) * 46 + 10 + len(summary) * LH + 14 + len(impact) * LH + 10
             + len(watch) * 38 + 22 + len(source) * 32 + 22)
        card(y, y + h)
        chip(M + PAD, y + 24, item["source"], CHIP.get(item["source_id"], LINE), INK, T_TINY)
        d.text((W - M - PAD, y + 24 + 20), item["date"], font=F(T_TINY), fill=MUTED, anchor="rm")
        ty = y + 24 + 44 + 18
        for line in title:
            d.text((M + PAD, ty), line, font=F(T_H3, True), fill=INK)
            ty += 46
        ty += 10
        for line in summary:
            d.text((M + PAD, ty), line, font=F(T_BODY), fill=TEXT)
            ty += LH
        ty += 14
        d.text((M + PAD, ty), "影响", font=F(T_BODY, True), fill=ASK)
        for line in impact:
            d.text((M + PAD + tag_w, ty), line, font=F(T_BODY), fill=INK)
            ty += LH
        ty += 10
        d.text((M + PAD, ty), "跟进", font=F(T_SMALL, True), fill=AMBER)
        for line in watch:
            d.text((M + PAD + tag_w, ty), line, font=F(T_SMALL), fill=TEXT)
            ty += 38
        ty += 8
        d.line([(M + PAD, ty), (W - M - PAD, ty)], fill=LINE, width=1)
        ty += 14
        for line in source:
            d.text((M + PAD, ty), line, font=F(T_TINY), fill=MUTED)
            ty += 32
        y += h + 14

    # Footer.
    y += 12
    note = "口径：渠道价为宽泛采销平台参考，不是成交价；媒体价格未统一税费、数量和交期。没有新证据时不改预测。"
    for line in wrap(d, note, F(T_TINY), W - 2 * M, 3):
        d.text((M, y), line, font=F(T_TINY), fill=MUTED)
        y += 34
    generated = datetime.fromisoformat(state["checked_at"]).strftime("%Y-%m-%d %H:%M")
    d.text((M, y + 6), f"采集 {generated} 北京时间", font=F(T_TINY), fill=MUTED)
    d.text((M, y + 42), f"完整情报与报告 {SITE}", font=F(T_TINY), fill=ASK)
    y += 42 + 34 + M
    img.crop((0, 0, W, int(y))).convert("RGB").save(output, optimize=True)
    return output
