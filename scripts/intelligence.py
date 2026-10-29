"""Source-specific concise briefs, optionally edited through Workers AI."""
import json
import os
import re
from pathlib import Path

import requests

ROOT=Path(__file__).resolve().parents[1]


SOURCE_LABELS={'qudao':'宽泛采销公开接口','smm':'SMM 上海有色网','reuters':'路透社独家（BNN Bloomberg 转载）',
               'trendforce':'TrendForce 集邦咨询（转述 The Information）','tansun':'天阳科技公告 2026-070',
               'cls':'财联社','nvidia':'NVIDIA 官网产品页'}


def fact_briefs(e,state):
    by_id={s['id']:s for s in e['sources']}
    channel=state.get('channel')
    rows=[
        ('smm','大陆供应商预售参考9.5万元','2026-10-13','媒体采访',
         'SMM 报道大陆供货商预售报价95,000元；行业估计90,000-95,000元。报道未披露供应商、数量和交付条款。',
         '95,000元可用作首轮报盘锚点，短交期和税票条件决定客户是否接受。','取得当日可执行报价和交期'),
        ('reuters','订单需求超过计划供应','2026-10-20','路透独家·匿名信源',
         '路透援引匿名信源称中国客户总订单超过600万张、2027年全球计划产量可能不超过300万张，合作方或只获配申请量的5%-10%；商业交付预计2027年一季度。',
         '首批配额偏紧有利于短交期货源报价；订单量不能直接推算实际获配。','跟踪样品、配额和商业发货'),
        ('trendforce','大媒体售价口径：8.5万-9万元','2026-10-21','行业研究机构转述',
         'TrendForce转述The Information：RTX PRO 5500在中国售价约85,000-90,000元，未披露税费、数量与交期。',
         '该区间低于SMM预售价95,000元，客户可能据此压价；高于该区间的报盘需以短交期或税票条件支撑。','核实该区间对应的交期与含税口径'),
        ('tansun','2万张采购合同，分批交付','2026-10-13','发行人公告',
         '天阳科技公告采购20,000张RTX PRO 5500，分批发货付款；原厂原因下存在延期、减量及卖方免责条款。',
         '分批交付与卖方免责条款使首批到货节奏不确定，短交期现货报价可能继续偏高。','核实配额及上下游交付责任'),
        ('cls','较早估价分歧：8.5万元到10万元以上','2026-10-09','媒体采访',
         '财联社受访者估计单卡约85,000元，另有受访者判断报价或超过100,000元；当时官方尚未定价。',
         '较宽预期区间说明报价仍受交期与供货把握影响，不宜把早期估价当采购底价。','以新报盘替换旧估价')]
    official=next((c for c in state['checks'] if c['source_id']=='nvidia'),{})
    note=official.get('signals',{}).get('note','官方页面待核查') if official.get('status')=='ok' else '本轮采集未成功，产品状态待核查'
    rows.append(('nvidia','产品状态与上市节点',state['date'],'官方页面',
                 f'RTX PRO 5500为84GB GDDR7工作站卡。本轮状态：{note}。',
                 '关注官方售价和正式发货节点，交付兑现后重新评估首批溢价。','核对官方价格与可购买状态'))
    if channel:
        p=channel['latest'];st=channel['stats'];delivery=channel.get('delivery') or '未标明交期'
        template=channel.get('template') or {}
        if template.get('synthetic'):
            curve='平台14日曲线'+'，'.join(template['reasons'])+'，不作行情。'
        else:
            curve=f"平台卖均{p['ask']:,}元、买均{p['bid']:,}元，价差{st['spread']:,}元。"
        rows.insert(0,('qudao','渠道最低挂价与交期',channel.get('quote_date') or p['date'],'平台参考',
                      f"平台最低挂价{channel['min_ask']:,}元，交期{delivery}，原报价日期{channel.get('quote_date') or '未标明'}。{curve}",
                      f"最低挂价按{delivery}交付，短交期报盘需单独确认。",'核实低价有效性与报价算法'))
    return [{'source_id':key,'source':SOURCE_LABELS[key],'title':title,'date':date,'kind':kind,'url':by_id[key]['url'],
             'summary':summary,'impact':impact,'watch':watch} for key,title,date,kind,summary,impact,watch in rows]


def numeric_values(text):
    values=set()
    for number,unit in re.findall(r'(\d[\d,]*(?:\.\d+)?)\s*(万|亿)?',text):
        value=float(number.replace(',',''))*({'万':10000,'亿':100000000}.get(unit,1))
        values.add(round(value,4))
    return values


def validate_ai(payload,facts):
    rows=payload.get('items') if isinstance(payload,dict) else None
    expected={x['source_id']:x for x in facts}
    if not isinstance(rows,list) or len(rows)!=len(facts):raise ValueError('模型摘要条数异常')
    seen=set();out=[]
    for item in rows:
        key=item.get('source_id')
        if key not in expected or key in seen:raise ValueError('模型来源映射异常')
        seen.add(key);fact=expected[key]
        for field in ['summary','impact','watch']:
            value=item.get(field)
            if not isinstance(value,str) or not value.strip() or len(value)>220:raise ValueError('模型摘要字段异常')
        allowed=numeric_values(json.dumps(fact,ensure_ascii=False))
        actual=numeric_values(' '.join(item[f] for f in ['summary','impact','watch']))
        if not actual.issubset(allowed):raise ValueError('模型引入了输入中没有的数字')
        if '可能不超过' in fact['summary'] and '可能' not in item['summary']:
            raise ValueError('模型提高了产量预期的确定性')
        out.append(dict(fact,**{field:item[field] for field in ['summary','impact','watch']}))
    return sorted(out,key=lambda x:list(expected).index(x['source_id']))


def enrich(e,state):
    facts=fact_briefs(e,state)
    result={'status':'curated','items':facts,'model':None,'generated_at':state['checked_at']}
    endpoint=os.getenv('GPU_AI_ENDPOINT');token=os.getenv('GPU_AI_TOKEN')
    if not endpoint or not token:return result
    try:
        prompt=(ROOT/'prompts/intelligence.md').read_text(encoding='utf8')
        response=requests.post(endpoint,headers={'Authorization':'Bearer '+token},json={'prompt':prompt,'sources':facts},timeout=(10,55))
        response.raise_for_status();body=response.json();text=body['text'].strip()
        if text.startswith('```'):text=re.sub(r'^```(?:json)?\s*|\s*```$','',text).strip()
        generated=json.loads(text)
        result.update(status='workers_ai',items=validate_ai(generated,facts),model=body.get('model'),generated_at=body.get('generated_at'))
    except Exception as error:
        result.update(status='fallback',error=str(error)[:180])
    return result
