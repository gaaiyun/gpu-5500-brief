"""Build the public site, source ledger, and a source-linked PDF report."""
from __future__ import annotations

import csv
import html
import json
import os
import re
import shutil
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

from research import report_markdown
from daily_card import render as render_card
from share_page import page_html as share_page

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def inline(text):
    text = html.escape(text)
    text = re.sub(r"\[([^\]]+)\]\((https://[^)]+)\)", lambda m: f'<link href="{m[2]}" color="#235946">{m[1]}</link>', text)
    return re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)


def make_pdf(markdown, output):
    font_path = os.getenv("REPORT_FONT")
    candidates = [font_path] if font_path else []
    candidates += ["C:/Windows/Fonts/simhei.ttf", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"]
    font = next((p for p in candidates if p and Path(p).exists()), None)
    if not font:
        raise RuntimeError("缺少中文字体，无法生成可验证的 PDF")
    pdfmetrics.registerFont(TTFont("CN", font))
    pdfmetrics.registerFontFamily("CN", normal="CN", bold="CN", italic="CN", boldItalic="CN")
    styles = {
        "body": ParagraphStyle("body", fontName="CN", fontSize=10, leading=17, spaceAfter=9, wordWrap="CJK", textColor=colors.HexColor("#202b27")),
        "h1": ParagraphStyle("h1", fontName="CN", fontSize=23, leading=32, spaceAfter=22, wordWrap="CJK"),
        "h2": ParagraphStyle("h2", fontName="CN", fontSize=15, leading=22, spaceBefore=10, spaceAfter=14, wordWrap="CJK"),
        "cell": ParagraphStyle("cell", fontName="CN", fontSize=8.4, leading=13, wordWrap="CJK"),
    }
    story = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if line == "<!-- page -->":
            story.append(PageBreak())
        elif line.startswith("# "):
            story.append(Paragraph(inline(line[2:]), styles["h1"]))
        elif line.startswith("## "):
            story.append(Paragraph(inline(line[3:]), styles["h2"]))
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r"[-: ]+", c) for c in cells):
                    rows.append([Paragraph(inline(c), styles["cell"]) for c in cells])
                i += 1
            count = len(rows[0])
            widths = [116, 93, 73, 229] if count == 4 else [128, 122, 261]
            table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#e9efeb")),("VALIGN",(0,0),(-1,-1),"TOP"),("LINEBELOW",(0,0),(-1,0),.7,colors.HexColor("#81968a")),("LINEBELOW",(0,1),(-1,-1),.35,colors.HexColor("#d4dfd8")),("LEFTPADDING",(0,0),(-1,-1),7),("RIGHTPADDING",(0,0),(-1,-1),7),("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8)]))
            story.extend([table, Spacer(1, 14)])
            continue
        else:
            story.append(Paragraph(inline(line), styles["body"]))
        i += 1
    def page_decor(canvas, doc):
        canvas.setFont("CN", 8)
        canvas.setFillColor(colors.HexColor("#536b5d"))
        canvas.drawString(42, 813, "GPU 5500 / 中国大陆价格研究")
        canvas.setStrokeColor(colors.HexColor("#d4dfd8"))
        canvas.line(42, 802, 553, 802)
        canvas.drawString(42, 28, "价格原始日期与报告生成日期分别记录；预测为低置信度情景")
        canvas.drawRightString(553, 28, str(doc.page))
    doc = SimpleDocTemplate(str(output), pagesize=(595.28,841.89), rightMargin=42, leftMargin=42, topMargin=57, bottomMargin=49,
                            title="中国大陆 RTX PRO 5500 价格预测与分销分析", author="GPU 5500 中国大陆渠道观察")
    doc.build(story, onFirstPage=page_decor, onLaterPages=page_decor)


def build():
    evidence = json.loads((ROOT / "data/evidence.json").read_text(encoding="utf-8"))
    state = json.loads((ROOT / "data/state.json").read_text(encoding="utf-8"))
    DIST.mkdir(exist_ok=True)
    for file in (ROOT / "web").iterdir():
        if file.is_file():
            shutil.copy2(file, DIST / file.name)
    for name in ("evidence.json", "state.json"):
        shutil.copy2(ROOT / "data" / name, DIST / name)
    # Expose daily history without full article copies or private business data.
    history = sorted((ROOT / "data/history").glob("*.json"))
    (DIST / "history.json").write_text(json.dumps([json.loads(p.read_text(encoding="utf-8")) for p in history], ensure_ascii=False), encoding="utf-8")
    # Every day's image stays published, so images in earlier group messages keep loading.
    (DIST / "daily").mkdir(exist_ok=True)
    for day_state in [json.loads(p.read_text(encoding="utf-8")) for p in history] + [state]:
        if day_state.get("channel") and day_state.get("forecast_review"):
            render_card(evidence, day_state, DIST / "daily" / f"{day_state['date']}.png")
            (DIST / "daily" / f"{day_state['date']}.html").write_text(share_page(day_state), encoding="utf-8")
    markdown = report_markdown(evidence, state)
    (DIST / "report.md").write_text(markdown, encoding="utf-8")
    make_pdf(markdown, DIST / "report.pdf")
    with (DIST / "evidence.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["记录", "原始日期", "金额或区间", "币种", "口径", "来源", "限制"])
        for p in evidence["prices"]:
            src = next(s for s in evidence["sources"] if s["id"] == p["source_id"])
            amount = p.get("value_cny", p.get("value_usd", f"{p.get('low_cny', '')}-{p.get('high_cny', '')}"))
            writer.writerow([p["id"],p["observed_at"],amount,"USD" if "value_usd" in p else "CNY",p["type"],src["url"],src["limitations"]])
        for r in (state.get("price_board") or {}).get("rows", []):
            if r["id"] == "channel_min_ask" or r["kind"] == "海外零售" or r["id"].startswith("feed:"):
                writer.writerow([r["id"], r["date"], r["native"], "原币", r["kind"], r["url"], r["note"]])
            if r["converted"]:
                writer.writerow([r["id"] + "_cny_vat", state["price_board"]["fx"]["date"], r["cny_vat"], "CNY",
                                 "按当日汇率折算并加 13% 增值税，不是新报价", r["url"], r["note"]])
    if state.get("channel"):
        with (DIST / "channel-series.csv").open("w",encoding="utf-8-sig",newline="") as stream:
            writer=csv.DictWriter(stream,fieldnames=["date","ask","bid","mid","high","low","activity"])
            writer.writeheader()
            writer.writerows(state["channel"]["series"])
    (DIST / ".nojekyll").touch()
    print("Built dist: website, report.pdf, report.md, evidence.csv, daily history")


if __name__ == "__main__":
    build()
