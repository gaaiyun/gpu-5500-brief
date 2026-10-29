"""Render the daily image pushed to the DingTalk group."""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont

from feed import claim_tally

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


def forecast_on(evidence, day):
    """The forecast version in force on that day, so earlier images keep the numbers the group saw."""
    versions = sorted(evidence.get("forecast_history", []) + [evidence["forecast"]], key=lambda f: f["issued_at"])
    return next((f for f in reversed(versions) if f["issued_at"] <= day), versions[0])


def render(evidence, state, output):
    market = state.get("channel")
    if not market:
        raise ValueError("日报图需要有效渠道快照")
    F = Fonts()
    yuan = lambda v: f"{F.yen}{v:,.0f}"
    wan = lambda v: f"{v / 10000:.2f}万"
    p, stats = market["latest"], market["stats"]
    forecast, review = forecast_on(evidence, state["date"]), state["forecast_review"]
    # Days before the price board existed keep their original layout, so images in old group messages stay as sent.
    board = state.get("price_board")
    fx = (board or {}).get("fx") or {}
    board_rows = {r["id"]: r for r in (board or {}).get("rows", [])}
    board_changes = {c["id"]: c for c in (board or {}).get("changes", [])}
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
    subtitle = f"汇率 {fx['date'][5:]}" if fx.get("rates") else f"渠道截至 {p['date'][5:]}"
    d.text((M, 112), f"{state['date']} · 84GB · 人民币/张 · {subtitle}", font=F(T_SMALL), fill=(148, 163, 184))
    official = next((c for c in state["checks"] if c["source_id"] == "nvidia"), {})
    official_text = "官方 Coming Soon" if official.get("status") == "ok" and official.get("signals", {}).get("coming_soon") else "官方状态待复核"
    status = {"low_confidence": "预测 条件情景", "review_required": "预测 待复核", "expired": "预测 已到期"}[review["status"]]
    healthy = sum(c["status"] == "ok" for c in state["checks"])
    x = M
    for text in (official_text, status, f"来源 {healthy}/{len(state['checks'])} 可访问"):
        x = chip(x, 182, text, (30, 41, 59), (226, 232, 240))
    y = 268 + GAP + 6

    # What changed since yesterday's report comes first; a quiet day says so instead of showing a fake move.
    digest = state.get("digest")
    if board and digest:
        inner = W - 2 * M - 2 * PAD
        tag_w = d.textlength("海外零售", font=F(T_TINY, True)) + 30
        laid = [(i["tag"], wrap(d, i["text"], F(T_SMALL), inner - tag_w - 12, 2)) for i in digest["items"]]
        head = wrap(d, digest["headline"], F(T_H3, True), inner, 2)
        h = 30 + len(head) * 46 + 16 + sum(len(ls) * 38 + 14 for _, ls in laid) + (0 if laid else 38) + 20
        d.rounded_rectangle([M, y, W - M, y + h], radius=20, fill=(255, 251, 235) if digest["quiet"] else (236, 253, 245), outline=LINE)
        ty = y + 30
        for line in head:
            d.text((M + PAD, ty), line, font=F(T_H3, True), fill=AMBER if digest["quiet"] else DOWN)
            ty += 46
        ty += 16
        tag_fill = {"新报价": (220, 252, 231), "网上挂价": (254, 243, 199), "海外零售": (219, 234, 254), "情报": (243, 232, 255),
                    "官方": (254, 226, 226), "汇率": (241, 245, 249), "线索": (241, 245, 249), "新闻": (241, 245, 249)}
        for tag, lines in laid:
            chip(M + PAD, ty - 4, tag, tag_fill.get(tag, LINE), INK, T_TINY)
            for line in lines:
                d.text((M + PAD + tag_w + 12, ty), line, font=F(T_SMALL), fill=TEXT)
                ty += 38
            ty += 14
        if not laid:
            d.text((M + PAD, ty), "过去一天没有新报道、新线索或汇率变动。", font=F(T_SMALL), fill=MUTED)
        y += h + GAP

    # KPI cards, 2 x 2.
    cw = (W - 2 * M - GAP) / 2
    if board:
        dom, usd = board.get("domestic"), board_rows.get("reuters_usd")
        retail = next((r for r in board["rows"] if r["kind"] == "海外零售" and r["cny_vat"]), None)
        move = (board_changes.get("reuters_usd") or {}).get("delta")
        kpis = [("大陆报价", f"{dom['low'] / 10000:g}–{dom['high'] / 10000:g}万" if dom else "—",
                 f"{dom['count']} 条来源 · 最新 {dom['latest_date'][5:]}" if dom else "暂无", ASK, MUTED)]
        if usd and usd["cny_vat"]:
            kpis.append(("路透订单价 含税折算", yuan(usd["cny_vat"]),
                         f"{usd['native']} × {fx['rates']['USD']}" + (f" · 日 {move:+,}" if move else ""), INK,
                         MUTED if not move else UP if move > 0 else DOWN))
        elif usd:
            kpis.append(("路透订单价", usd["native"], "汇率未取得，未折算", INK, MUTED))
        if retail:
            kpis.append(("海外零售 含税折算", yuan(retail["cny_vat"]), f"{retail['native'].split('（')[0]} · {retail['label']}", INK, MUTED))
        kpis.append(("渠道最低挂价", yuan(market["min_ask"]),
                     f"{market.get('delivery') or '交期未标明'} · 原报价 {(market.get('quote_date') or '未标明')[5:]}", INK, AMBER))
        kpis = kpis[:4]
    else:
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
    y += ((len(kpis) + 1) // 2) * (kh + GAP)

    # Reference trend: each day's values use only what was known that day.
    series = state.get("price_series") or []
    if board and len(series) >= 2:
        ch = 700
        card(y, y + ch)
        d.text((M + PAD, y + 24), "参考价走势", font=F(T_H2, True), fill=INK)
        for k, line in enumerate(wrap(d, "按当日可得信息逐日回算：蓝线随人民币中间价变，色带为已披露大陆报价区间，▲为当天出现新报价。",
                                      F(T_TINY), W - 2 * M - 2 * PAD, 2)):
            d.text((M + PAD, y + 76 + k * 32), line, font=F(T_TINY), fill=MUTED)
        lx = W - M - PAD
        for label, color in (("渠道挂价", AMBER), ("路透含税折算", ASK)):
            lx -= d.textlength(label, font=F(T_TINY))
            d.text((lx, y + 32), label, font=F(T_TINY), fill=TEXT)
            d.rounded_rectangle([lx - 34, y + 44, lx - 10, y + 50], radius=3, fill=color)
            lx -= 58
        left, right, top, bottom = M + 120, W - M - 190, y + 170, y + 520
        values = [v for pt in series for v in (pt["low"], pt["high"], pt["channel"], pt["usd_vat"], *pt["team"]) if v]
        tick = 5000 if max(values) - min(values) > 12000 else 2000
        lo, hi = (min(values) // tick) * tick - tick / 2, (max(values) // tick + 1) * tick + tick / 2
        xs = lambda i: left + i / max(len(series) - 1, 1) * (right - left)
        ys = lambda v: bottom - (v - lo) / (hi - lo) * (bottom - top)
        for v in range(int((lo // tick + 1) * tick), int(hi), tick):
            d.line([(left, ys(v)), (right, ys(v))], fill=LINE, width=1)
            d.text((left - 16, ys(v)), f"{v / 10000:g}万", font=F(T_TINY), fill=MUTED, anchor="rm")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for i, pt in enumerate(series):
            if pt["low"] is not None:
                x0, x1 = xs(max(i - .5, 0)), xs(min(i + .5, len(series) - 1))
                od.rectangle([x0, ys(pt["high"]) - 3, x1, ys(pt["low"]) + 3], fill=(37, 99, 235, 30))
        img.alpha_composite(overlay)
        d = ImageDraw.Draw(img)
        for field, color in (("channel", AMBER), ("usd_vat", ASK)):
            pts = [(xs(i), ys(pt[field])) for i, pt in enumerate(series) if pt[field]]
            if len(pts) >= 2:
                d.line(pts, fill=color, width=5 if field == "usd_vat" else 3, joint="curve")
            if pts:
                ex, ey = pts[-1]
                d.ellipse([ex - 7, ey - 7, ex + 7, ey + 7], fill=CARD, outline=color, width=4)
                d.text((ex + 16, ey + (14 if field == "channel" else -14)), yuan(series[-1][field]), font=F(T_SMALL, True), fill=color, anchor="lm")
        for i, pt in enumerate(series):
            for v in pt["team"]:
                d.ellipse([xs(i) - 7, ys(v) - 7, xs(i) + 7, ys(v) + 7], fill=BID)
            if pt["events"] or pt["team"]:
                tx = xs(i)
                d.polygon([(tx, bottom + 18), (tx - 9, bottom + 34), (tx + 9, bottom + 34)], fill=DOWN)
        step = max(1, (len(series) - 1) // 5)
        for i in sorted(set(list(range(0, len(series), step)) + [len(series) - 1])):
            if i != len(series) - 1 and len(series) - 1 - i < step / 2:
                continue
            d.text((xs(i), bottom + 46), series[i]["date"][5:].replace("-", "/"), font=F(T_TINY), fill=MUTED, anchor="ma")
        first = next((pt for pt in series if pt["usd_vat"]), None)
        if first and first is not series[-1]:
            delta = series[-1]["usd_vat"] - first["usd_vat"]
            last_event = max((pt["date"] for pt in series if pt["events"] or pt["team"]), default="")
            note = (f"路透含税折算自 {first['date'][5:]} 起 {delta:+,} 元（{delta / first['usd_vat'] * 100:+.2f}%），全部来自汇率变化。"
                    + (f"最近一次新报价出现在 {last_event[5:]}。" if last_event else ""))
            for k, line in enumerate(wrap(d, note, F(T_TINY), W - 2 * M - 2 * PAD - 2 * T_TINY, 2)):
                d.text((M + PAD, y + ch - 84 + k * 32), line, font=F(T_TINY), fill=TEXT)
        y += ch + GAP

    if board:
        # Price evidence: each quote with its own date; converted rows say so.
        inner = W - 2 * M - 2 * PAD
        laid = []
        for r in board["rows"]:
            age = "当日" if r["age_days"] == 0 else f"{r['age_days']} 天前"
            when = f"{r['date']}（{age}）"
            if r["kind"] == "海外零售":
                ok, last = r.get("check_status") == "ok", r.get("checked")
                when = f"{r['date']} 起此价未变，" + (f"{last[5:]} 核对" if ok and last else
                                                    f"本轮未读到页面，最后核对 {last[5:]}" if last else "本轮未读到页面")
            meta = " · ".join(x for x in (when, r["kind"], r["native"] if r["converted"] or not r["low"] else "", r["note"]) if x)
            change = board_changes.get(r["id"])
            flag = ("今日新报价" if change["kind"] == "新报价" else f"汇率 {change['delta']:+,}") if change else ""
            value = r["text"] if r["low"] else "未折算"
            laid.append((r, wrap(d, meta, F(T_TINY), inner, 2), flag, value))
        # Closing punctuation may run past the wrap width, so leave room for it.
        # With the digest at the top, the change line would only repeat it.
        summary = [] if digest else wrap(d, board["summary"], F(T_SMALL), inner - d.textlength("今日变化", font=F(T_SMALL, True)) - 18 - 2 * T_SMALL, 4)
        h = 96 + sum(48 + len(m) * 32 + 22 for _, m, _, _ in laid) + (14 + len(summary) * 38 if summary else 0) + 24
        card(y, y + h)
        d.text((M + PAD, y + 24), "价格证据表", font=F(T_H2, True), fill=INK)
        rate_note = f"{fx['label']} {fx['date'][5:]}" + ("（沿用）" if fx.get("status") == "carried" else "") if fx.get("rates") else "汇率未取得"
        d.text((W - M - PAD, y + 34), rate_note, font=F(T_TINY), fill=MUTED, anchor="ra")
        ty = y + 96
        for r, meta, flag, value in laid:
            d.text((M + PAD, ty), r["label"], font=F(T_BODY, True), fill=INK)
            if flag:
                chip(M + PAD + d.textlength(r["label"], font=F(T_BODY, True)) + 14, ty - 2, flag, (254, 243, 199), AMBER, 20)
            d.text((W - M - PAD, ty), value, font=F(T_BODY, True), fill=ASK if r["converted"] else INK, anchor="ra")
            ty += 48
            for line in meta:
                d.text((M + PAD, ty), line, font=F(T_TINY), fill=MUTED)
                ty += 32
            ty += 10
            d.line([(M + PAD, ty), (W - M - PAD, ty)], fill=LINE, width=1)
            ty += 12
        ty += 14
        if summary:
            d.text((M + PAD, ty), "今日变化", font=F(T_SMALL, True), fill=AMBER)
        for line in summary:
            d.text((M + PAD + d.textlength("今日变化", font=F(T_SMALL, True)) + 18, ty), line, font=F(T_SMALL), fill=INK)
            ty += 38
        y += h + GAP
    else:
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
    smm = next(x["value_cny"] for x in evidence["prices"] if x["id"] == "smm_presale")
    if board:
        marks = [(market["min_ask"], "渠道挂价", AMBER), (smm, "SMM预售", INK)]
        if board_rows.get("reuters_usd", {}).get("cny_vat"):
            marks.append((board_rows["reuters_usd"]["cny_vat"], "路透含税折算", ASK))
    else:
        marks = [(market["min_ask"], "最低挂价", AMBER), (p["bid"], "平台买均", BID), (p["ask"], "平台卖均", ASK),
                 (smm, "SMM预售", INK)]
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
    for v in range(-(-v0 // 10000) * 10000, v1 + 1, 10000):
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
    # Today's change is already under the evidence table.
    lines_src = [(b["title"], b["text"]) for b in state["daily_brief"]["items"] if not (board and b["title"] == "今日变化")]
    label_w = max(d.textlength(k, font=F(T_BODY, True)) for k, _ in lines_src) + 20
    text_w = W - 2 * M - 2 * PAD - label_w
    body = [(k, wrap(d, t, F(T_BODY), text_w, 4 if board else 3)) for k, t in lines_src]
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

    # Agent-verified web intelligence from the last week.
    # Only A/B items go into the image; C items and leads stay in the site and the message text as links.
    feed = [x for x in (state.get("feed") or {}).get("items", []) if x.get("age_days", 99) <= 7 and x["grade"] in ("A", "B")][:3]
    if feed:
        y += 12
        d.text((M + 4, y + 10), f"全网追踪 · {len(feed)} 条", font=F(T_H2, True), fill=INK)
        d.text((W - M, y + 22), "AI 读原文核对", font=F(T_TINY), fill=MUTED, anchor="ra")
        y += 72
        for item in feed:
            title = wrap(d, item["title"], F(T_H3, True), inner, 2)
            summary = wrap(d, item["summary"], F(T_BODY), inner, 4)
            impact = wrap(d, item["impact"], F(T_BODY), inner - tag_w, 3)
            source = wrap(d, f"来源：{item['publisher']} · {urlparse(item['url']).netloc}", F(T_TINY), inner, 2)
            # Second-hand posts carry their claim check, with the problem claims spelled out.
            flagged = [c for c in item.get("claims", []) if c["status"] in ("无出处", "与出处不符")][:2]
            checks = []
            if item.get("claims"):
                checks = wrap(d, f"核对：{claim_tally(item)}", F(T_SMALL, True), inner, 2)
                for c in flagged:
                    checks += wrap(d, f"【{c['status']}】{c['text']}", F(T_SMALL), inner, 2)
            h = (24 + 44 + 18 + len(title) * 46 + 10 + len(summary) * LH + 14 + len(impact) * LH
                 + (len(checks) * 38 + 10 if checks else 0) + 22 + len(source) * 32 + 22)
            card(y, y + h)
            grade_fill = {"A": (220, 252, 231), "B": (254, 243, 199)}.get(item["grade"], LINE)
            chip(M + PAD, y + 24, f"{item.get('tier', '核实')} · {item['grade']} {item['grade_label']}", grade_fill, INK, T_TINY)
            d.text((W - M - PAD, y + 44), item["published_at"], font=F(T_TINY), fill=MUTED, anchor="rm")
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
            if checks:
                ty += 10
                for i, line in enumerate(checks):
                    d.text((M + PAD, ty), line, font=F(T_SMALL, i == 0), fill=AMBER if i == 0 else BID)
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
    note = ("口径：海外价格按当日汇率折算，汇率变动不是新报价，未含关税运费；渠道挂价为平台期货报盘，不是成交价；媒体价格未统一税费、数量和交期。没有新证据时不改预测。"
            if board else "口径：渠道价为宽泛采销平台参考，不是成交价；媒体价格未统一税费、数量和交期。没有新证据时不改预测。")
    for line in wrap(d, note, F(T_TINY), W - 2 * M, 3):
        d.text((M, y), line, font=F(T_TINY), fill=MUTED)
        y += 34
    generated = datetime.fromisoformat(state["checked_at"]).strftime("%Y-%m-%d %H:%M")
    d.text((M, y + 6), f"采集 {generated} 北京时间", font=F(T_TINY), fill=MUTED)
    d.text((M, y + 42), f"完整情报与报告 {SITE}", font=F(T_TINY), fill=ASK)
    y += 42 + 34 + M
    img.crop((0, 0, W, int(y))).convert("RGB").save(output, optimize=True)
    return output
