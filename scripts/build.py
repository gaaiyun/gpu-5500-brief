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

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def source_link(evidence, source_id, label=None):
    source = next(s for s in evidence["sources"] if s["id"] == source_id)
    return f"[{label or source['name']}]({source['url']})"


def report_markdown(e, state):
    s = lambda key, label=None: source_link(e, key, label)
    review = state["forecast_review"]
    status = {"low_confidence":"低置信度，有条件使用", "review_required":"需要复核，不宜直接据此报盘", "expired":"已失效，仅供历史回顾"}[review["status"]]
    failures = [c["source_id"] for c in state["checks"] if c["status"] != "ok"]
    official = next((c for c in state["checks"] if c["source_id"] == "nvidia"), {})
    official_now = official.get("signals", {}).get("note", "没有取得有效官方状态") if official.get("status") == "ok" else "本轮采集失败，当前状态未确认"
    prediction_intro = "2026-10-25 首次判断：在官方价格、明确配额和成交证据出现前，未来 30-60 天的公开预售报价可能围绕 90,000-100,000 元/张讨论。"
    if not review["numeric_forecast_active"]:
        prediction_intro += "这项数值预测现已失效，下文仅保留历史情景，不能据此作当前报盘。"
    else:
        prediction_intro += "本轮仍按原版本复核，不延长原观察期限。"
    return f"""# 中国大陆 RTX PRO 5500 价格预测与分销分析

资料截止：{state['date']}（北京时间）｜预测首次发布：2026-10-25｜价格单位：人民币/张

## 判断与适用范围

本报告将 95,000 元视为有媒体来源的历史预售锚点。它来自 10 月 13 日的报道，本轮没有直接向卖方复询，不能称为 10 月 25 日的新报价或现货成交价。{s('smm', 'SMM 原文')}

{prediction_intro}95,000 元为历史预算参考，预测置信度低。该区间是研究者的主观情景设定，没有经过成交数据拟合；数量、税费和交期不一致时不能直接比较。

当前预测状态：**{status}**。锚点距采集日 {review['anchor_age_days']} 天。{'；'.join(review['reasons']) or '尚未发现足以替换原锚点的已核验新价格。'}

截至本轮，尚未取得可独立验证的大陆批发成交单、到仓数量或最新可执行卖方报盘。报告不能给出可靠的批量成交中枢、销量或销售利润预测。

研究对象为 NVIDIA RTX PRO 5500 Blackwell Workstation Edition。公开报价尚未统一是否含税、最小采购量、付款方式、交付日期、质保和风冷/液冷配置。报告中的价格不包括默认推定的整机、机房或集成服务。

## 当前最有用的决策

有可履行货源时，先取得当日有效报盘，再记录客户对数量、交期、税票和付款条件的接受程度；在这些条件核实前，不据此承诺固定交期，也不把拟采购数量写成可售库存。旧锚点失效时停止据此报价。

<!-- page -->

## 价格证据：哪些数字能说明什么

| 信息 | 公开数值 | 原始日期 | 可支持的结论 |
| --- | --- | --- | --- |
| SMM 转述大陆供应商预售 | 95,000 元 | 2026-10-13 | 有来源的卖方预售参考，非成交 |
| SMM 文中行业估计 | 90,000-95,000 元 | 2026-10-13 | 从业者预期；与上一行不是独立样本 |
| 财联社受访者估计 | 约 85,000 元 | 2026-10-09 | 早期估价，非买方真实出价 |
| 财联社其他受访者估计 | 或超过 100,000 元 | 2026-10-09 | 上行情景，非已核实高价成交 |
| 路透匿名信源所述订单单价 | 约 11,400 美元 | 2026-10-20 | 美元订单参考，税费和交付条款不明 |

前两行来自同一篇 {s('smm', 'SMM 报道')}。该报道自身也明确提示非官方定价和上市时间尚未公布。{s('cls', '财联社原始采访')}同日记录了高低不同的估计，体现受访者预期分歧。

关于美元价格：本报告核查了署名 Thomson Reuters 的{s('reuters', 'WBOW 全文转载')}。报道所述价格来自匿名消息源。未明确币种结算时间、折扣、税费、区域和服务条件前，不用任意汇率把它换成大陆分销底价，也不将其称为 NVIDIA 官方 MSRP。

聚合平台的 91,400 元卖盘均价与 88,700 元买盘均价不进入本报告的价格基准。本轮静态页面未复现目标条目，搜索索引的日期也有不一致。没有逐笔参与者、库存及成交信息，无法证明两个均价可由同一笔交易同时实现。{s('qudao', '平台地址')}

对上述两个数做纯算术：差额 2,700 元；以卖盘为分母为 2.95%，以中间价 90,050 元为分母为 3.00%，以买盘为分母为 3.04%。此前的 2.7% 不准确。这些比例均不等于可实现毛利。

<!-- page -->

## 交付与供需：价格为何可能偏强，也可能失真

{s('nvidia', 'NVIDIA 官方产品页')}在 2026-10-25 首次人工核查时显示 Coming Soon，配备 84 GB GDDR7，并注明规格为初步数据、可能变化；当时所查页面没有公开售价或确定上市日期。本轮自动检查结果：{official_now}。工作站版的定位不能直接证明某个数据中心部署方案的性能、散热和运维适配已完成。

路透 10 月 20 日报道援引匿名信源称：三家中国大型科技企业合计订购超过 300 万张，中国客户总订单超过 600 万张；2027 年全球计划产量可能不超过 300 万张，部分合作伙伴或仅获得请求量的 5%-10%；样品预计 12 月，商业交付预计 2027 年一季度。上述数量、比例和时点均是报道中的信源说法，尚非厂商公开承诺。{s('reuters', 'Reuters 全文转载')}

这些报道支持供应偏紧的假设，却不足以测算价格涨幅。不同客户可能重复下单或撤单，全球全年产量与中国当前订单也不是同一时间、地域和合同口径。不能把 600 万除以 300 万后推导价格翻倍，或用 5%-10% 作为本批货源的实际获配率。

更直接的证据是{s('tansun', '天阳科技 2026-070 号公告')}：发行人披露签订 20,000 张采购合同，安排分批交付、分批付款，并披露原厂原因下可能延期、减量及卖方免责。公告没有提供可用于本报告的单卡价格、合同总金额或确定交期。公告证明发行人披露了合同，不证明设备已经交付。

研究推断：客户可能为能够核验的短交期和履约保障支付溢价；同一型号下，可靠交付与不确定预售之间可能形成价格差。但本轮没有足够配对报价去量化该溢价，不能把它写成一个已观察到的百分比。

首批实际交付增加后，报价既可能因兑现需求而上移，也可能因排队订单撤回而回落。2027 年一季度应以实际配额、到货和客户验收更新判断，本报告不提前给出该季度成交均价。

<!-- page -->

## 预测情景与失效条件

预测首次发布于 2026-10-25，观察期限至 2026-12-24；每日检查有效性，未出现已核验新价格时不重置预测发布日期。

| 情景 | 研究区间（元/张） | 需要看到的证据 |
| --- | --- | --- |
| 供应改善 / 需求降温 | 80,000-90,000 | 多家有效报盘下调、需求撤回或可交付供应增加 |
| 基准 | 90,000-100,000 | 旧预售锚点仍有参考意义，暂无可核验供需突变 |
| 首批供应偏紧 | 100,000-115,000 | 可核验短交期配额稀缺，客户愿意付款锁货 |

区间构造方法：以 95,000 元为起点，选择约 -15% 到 +20% 的主观敏感性范围，再取整至便于讨论的区间。精确敏感性数值为：-15% 对应 80,750 元、-5% 对应 90,250 元、+5% 对应 99,750 元、+20% 对应 114,000 元。区间端点不是额外采集到的市场报价。

三个情景没有经过统计校准，不是置信区间，也没有可辩护的发生概率。基准情景表达研究方向，不能据此承诺成交。低价订金广告不构成供应改善的证据；大额订单标题也不构成十万元以上成交的证据。

以下情况触发重新判断：官方首次公开价格；至少两家相互独立、税费和交期可比较的有效卖方报价；可核验成交或验收；供应条款显著变化。自动程序发现官网状态变化时只标记待复核，不凭 Coming Soon 字样消失就宣布上市。

系统在锚点超过 14 天时提示陈旧风险；超过 30 天或预测期限届满时停止把数值区间作为有效预测展示。这是本项目的证据管理规则，不是价格变化规律。历史情景仍保留供回顾。

<!-- page -->

## 分销测算：先统一口径，再决定报价

报价需要同时明确：型号和配置、数量、是否现货、交付时间、税票与运费、预付款比例、延期处理、验收条件和质保责任。确认每一批货的销售权利与可履行数量后，再给客户正式报盘。

在统一税务和会计口径后，设净销售收入为 R、对应采购成本为 C、物流与资金等可归属费用为 F，则经营贡献额为 R-C-F，经营贡献率为 (R-C-F)/R。此处不是财报毛利率，未必包含全部管理费用和所得税。

| 纯算术示例 | 净收入 R | 采购 C + 费用 F | 经营贡献 / 贡献率 |
| --- | --- | --- | --- |
| 成本较低 | 95,000 | 85,000 + 2,000 | 8,000 / 8.42% |
| 成本接近报价 | 95,000 | 90,000 + 2,000 | 3,000 / 3.16% |
| 采购即达锚点 | 95,000 | 95,000 + 2,000 | -2,000 / -2.11% |

这些收入与成本完全是假设金额，已经假定在同一税务口径。表中的 95,000 元净收入不等于已报道报价的税后收入；公开预售价是否含税尚未披露。没有你们的真实采购和税费数据，不能给出实际利润率或利润底线。

如果总可归属成本为 K，目标经营贡献率为 m，则所需净销售收入为 K/(1-m)。例如假设 K=90,000 元，m=5%，收入需约 94,737 元；m=8% 时需约 97,826 元。数量折扣的前提是实际成本或履约成本确有下降，不能仅凭采购量大就推定供应方会打折。

上游因原厂原因免责，而下游仍要求固定交期赔偿时，分销商承担的风险可能超过表面价差。报价时需要把资金占用和可合理估计的履约成本计入测算。只有预售权利时，销售文件应写明预售及条件，不能称为现货。

<!-- page -->

## 每日更新方式与本轮采集情况

网站通过 GitHub Actions 按每天北京时间 00:35 计划触发：核查已知来源、检索近期新闻标题、检查官方页面状态，生成当日日报和预测有效性复核，再部署静态网站。GitHub 的定时任务可能延迟，页面以实际采集时间为准。新闻标题只作为待核实线索，不自动变成价格或成交事实。

本轮检查时间：{state['checked_at']}。核心来源成功 {len(state['checks'])-len(failures)}/{len(state['checks'])}；失败来源：{', '.join(failures) or '无'}。标题检索接口成功 {sum(f['status']=='ok' for f in state['feeds'])}/{len(state['feeds'])}。来源失败时保留上一次有效状态并展示失败，不能把上次数据标为今日采集成功。

当日新增已核验价格记录：{state['new_verified_price_count']}。自动流程检查公开页面和新闻线索；新增价格必须复核来源、口径和可执行条件后写入证据表。系统对没有新证据的日期明确写出沿用原判断，不为了每日更新而改变数字。

当前尚缺：大陆可核验成交样本、同日且可比较的独立供应商报盘、实际到货配额及你们自己的采购成本。随着这些资料取得，应优先更新锚点，而不是提高预测文字的确定性。

## 来源清单与使用方式

1. {s('nvidia')}。无固定文章发布日期；本轮采集核查。用于产品状态及规格，不提供大陆定价。
2. {s('smm')}。2026-10-13 14:41。用于历史预售报价与行业估价，卖方未直接复询。
3. {s('cls')}。2026-10-09 19:09。用于受访者估价及当时的不确定性。
4. {s('reuters')}。2026-10-20。使用署名路透的全文转载；匿名信源数据未获厂商公开确认。
5. {s('tansun')}。2026-10-13，四页公告 PDF。属于发行人原始披露的镜像，不是交易所网页。
6. {s('qudao')}。本轮不能复核为特定日期有效挂牌，排除出预测锚点。

全文将来源可访问、来源所述事实、研究推断和情景假设分别表述。未取得的资料不代表市场上不存在；本报告只陈述本轮核查所能支持的范围。
"""


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
    (DIST / ".nojekyll").touch()
    print("Built dist: website, report.pdf, report.md, evidence.csv, daily history")


if __name__ == "__main__":
    build()
