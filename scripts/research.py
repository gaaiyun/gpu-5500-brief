"""Concise price research from dated evidence and the current channel snapshot."""


def report_markdown(e, state):
    sources={s['id']:s for s in e['sources']}
    link=lambda key,label:f"[{label}]({sources[key]['url']})"
    market=state.get('channel')
    if not market:
        raise ValueError('价格研究报告需要有效渠道快照；请先完成采集')
    p=market['latest'];stats=market['stats'];review=state['forecast_review']
    gap=e['forecast']['anchor_cny']-p['ask']
    expiry='原预测已到期，下列区间保留作历史回顾。' if not review['numeric_forecast_active'] else '基准判断维持，出现新官方价格或可执行报盘后重估。'
    low=market['min_ask'];quote_date=market.get('quote_date') or '未标明';delivery=market.get('delivery') or '未标明'
    low_note=(f"{low:,} 元的原始条目为{market.get('condition') or '未标明货况'}，交期{delivery}，原报价日期 {quote_date}。"
              f"平台监测日期 {p['date']} 不能替代这条原始报价日期；这笔低价能否继续锁定、何时付款需另行确认。")
    cycle='，挂牌活跃度也呈固定步长循环' if stats.get('activity_cycle') else ''
    pattern=(f"平台 {stats['fixed_offset_points']}/{stats['point_count']} 个日点近似满足“卖均=中间值×1.015、买均=中间值×0.985”{cycle}。"
             "因此，本报告把它用于报价对照和线索跟踪，预测判断主要看独立报盘及实际交付变化。")
    official=next((c for c in state['checks'] if c['source_id']=='nvidia'),{})
    if official.get('status')!='ok':official_text='NVIDIA 产品页本轮未采集成功，上市状态沿用上次记录待复核'
    elif official.get('signals',{}).get('coming_soon'):official_text=f"NVIDIA 产品页 {state['date']} 仍显示 Coming Soon"
    else:official_text='NVIDIA 产品页的 Coming Soon 标记已变化，需人工确认是否开售'
    base=next(s for s in e['forecast']['scenarios'] if s['id']=='base')
    inside=base['low']<=p['ask']<=base['high']
    base_note=(f"{base['low']/10000:g}万-{base['high']/10000:g}万元的基准覆盖当前平台卖均和SMM预售锚点。" if inside
               else f"当前平台卖均 {p['ask']:,} 元已落在 {base['low']/10000:g}万-{base['high']/10000:g}万元基准区间之外，需复核基准情景。")
    return f"""# RTX PRO 5500：大陆价格判断

{state['date']}｜渠道数据截至 {p['date']}｜人民币 / 张

## 报价判断

未来 30-60 天预售报价的基准情景维持 **90,000-100,000 元**，95,000 元为当前可引用的大陆预售锚点。大媒体口径（The Information，经 TrendForce 转述）为 85,000-90,000 元，平台卖均 {p['ask']:,} 元{'落在两者之间' if 90000<=p['ask']<=95000 else '在两者之外，需复核报价位置'}。决定成交价的关键是交期、税票及可交付数量。{expiry}

## 价格依据

| 价格层次 | 金额 | 日期 | 依据 |
| --- | --- | --- | --- |
| 平台卖方均价 | {p['ask']:,} | {p['date']} | 宽泛采销日序列 |
| 平台买方均价 | {p['bid']:,} | {p['date']} | 宽泛采销日序列 |
| 平台最低挂价 | {low:,} | {quote_date} | {market.get('condition') or delivery} |
| 大陆供应商预售 | 95,000 | 2026-10-13 | SMM 采访报道 |
| 大媒体售价区间 | 85,000-90,000 | 2026-10-21 | The Information，经 TrendForce 转述 |
| 较早受访者估价 | 约85,000 | 2026-10-09 | 财联社采访 |
| 美元订单参考 | USD 11,400 | 2026-10-20 | 路透独家，匿名信源 |

渠道买卖差 {stats['spread']:,} 元，约为中间值的 {stats['spread_pct']:.2f}%。SMM 预售锚点比平台卖均高 {gap:,} 元，算术差为 {gap/p['ask']*100:.2f}%。平台中间值日变动 {stats['day_pct']:+.2f}%，较七日前 {stats['week_pct']:+.2f}%。{link('qudao','渠道原始接口')}；{link('smm','SMM 原文')}；{link('trendforce','TrendForce')}；{link('cls','财联社采访')}。

{low_note}

{pattern}

## 供给与交付

{official_text}，产品为 84GB GDDR7 工作站版。页面提供规格，尚未提供本报告可用的大陆官方售价。{link('nvidia','官方产品页')}。

路透 10 月 20 日独家报道援引匿名信源：中国三家科技企业合计订购超过 300 万张，中国客户总订单超过 600 万张；2027 年全球计划产量可能不超过 300 万张，合作方或只获配申请量的 5%-10%。样品预计 12 月，商业交付预计 2027 年一季度。订单压力支持首批供应偏紧的判断，但排队数量不能直接换算价格涨幅。{link('reuters','Reuters 独家（BNN Bloomberg 转载）')}。

天阳科技 10 月 13 日公告披露 20,000 张采购合同，采用分批交货、分批付款；原厂原因导致延期或无法供货时，卖方可按合同约定免责。合同数量不等于到货数量，首批实际到货节奏仍待披露。{link('tansun','发行人公告 2026-070')}。

## 未来 30-60 天情景

| 情景 | 预售报价区间 | 改判所需变化 |
| --- | --- | --- |
| 基准 | 90,000-100,000 | 交付预期维持，供应商继续接受9万元以上报盘 |
| 需求降温 | 80,000-90,000 | 两家以上独立卖方有效报价下调，或客户撤回订单 |
| 首批供给偏紧 | 100,000-115,000 | 已核验短交期配额稀缺，客户愿意付款锁货 |

{base_note}上下行情景围绕9.5万元作价格敏感性分析，不赋发生概率。1月之后的成交价格应结合首批到货、获配数量及客户验收重新判断。

## 每日跟踪重点

1. 价格：新增可执行卖方报价、平台买卖差及原报价日期。
2. 供给：官方上市状态、配额确认、发货、到仓和验收。
3. 条款：付款节点、交付责任及税票口径。
4. 判断：保持或修改情景的具体证据；没有新证据时保留上一版本。

本轮采集 {state['checked_at']}。来源可访问 {sum(c['status']=='ok' for c in state['checks'])}/{len(state['checks'])}。每日计划于北京时间 00:35 更新网页、渠道序列与本报告，页面记录实际执行时间。

## 来源与口径

{link('qudao','宽泛采销公开接口')}：平台发布的14天历史序列，已保留采集快照。{link('smm','SMM（10月13日）')}：大陆预售报价。{link('trendforce','TrendForce（10月21日）')}：转述 The Information 售价区间及路透配额信息。{link('cls','财联社（10月9日）')}：从业者估价。{link('reuters','Reuters 独家（10月20日）')}：匿名信源所述订单与供应。{link('tansun','天阳科技公告（10月13日）')}：采购合同及条款。{link('nvidia','NVIDIA')}：官方产品状态。

价格表分别标明平台参考、预售、媒体售价、估价和美元订单口径；现阶段尚缺大陆批发成交及可比较的当日独立报盘。报告首次预测日期 2026-10-25，原观察期限至 2026-12-24。
"""
