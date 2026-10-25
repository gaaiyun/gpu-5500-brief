const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const url = value => {try{const u=new URL(value);return u.protocol==='https:'?esc(u.href):'#';}catch{return '#';}};
const number = value => Number(value).toLocaleString('zh-CN',{maximumFractionDigits:0});
const yuan = value => `¥${number(value)}`;
const pct = value => `${value>=0?'+':''}${Number(value).toFixed(2)}%`;
const time = value => value ? new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}) : '未取得';
const changeClass = value => value>=0?'up':'down';
let state,evidence,market,range=14,selected=0,newsFilter='all';

function chartRows(){return market.series.slice(-range);}
function renderChart(){
  const rows=chartRows(),svg=$('price-chart');selected=Math.min(Math.max(selected,0),rows.length-1);
  const bounds={left:85,right:780,top:17,bottom:225};
  const low=Math.min(...rows.map(p=>p.bid)),high=Math.max(...rows.map(p=>p.ask));
  const pad=Math.max((high-low)*.17,500),min=low-pad,max=high+pad;
  const x=i=>bounds.left+i/(rows.length-1||1)*(bounds.right-bounds.left);
  const y=p=>bounds.bottom-(p-min)/(max-min)*(bounds.bottom-bounds.top);
  const path=field=>rows.map((p,i)=>`${i?'L':'M'} ${x(i).toFixed(2)} ${y(p[field]).toFixed(2)}`).join(' ');
  let grid='';
  for(let i=0;i<5;i++){
    const v=min+(max-min)*i/4,yy=y(v);
    grid+=`<line x1="${bounds.left}" y1="${yy}" x2="${bounds.right}" y2="${yy}" stroke="var(--border)" stroke-dasharray="2 4" stroke-width=".8"/><text x="72" y="${yy+3}" text-anchor="end" fill="var(--muted)" font-size="10" font-family="Consolas,monospace">${(v/10000).toFixed(2)}万</text>`;
  }
  const labels=rows.map((p,i)=>(i===0||i===rows.length-1||(i%Math.ceil(rows.length/5)===0&&i<rows.length-2))?`<text x="${x(i)}" y="260" text-anchor="middle" fill="var(--muted)" font-size="10" font-family="Consolas,monospace">${p.date.slice(5).replace('-','/')}</text>`:'').join('');
  const maxActivity=Math.max(...rows.map(p=>p.activity),1);
  const bars=rows.map((p,i)=>`<rect x="${x(i)-3}" y="${241-p.activity/maxActivity*16}" width="6" height="${p.activity/maxActivity*16}" rx="1" fill="${i===selected?'var(--amber)':'var(--border)'}" opacity=".55"/>`).join('');
  const p=rows[selected];
  svg.innerHTML=`${grid}${bars}<path class="ask-line" d="${path('ask')}" fill="none" stroke="var(--blue)" stroke-width="2.3" stroke-linejoin="round"/><path class="bid-line" d="${path('bid')}" fill="none" stroke="var(--red)" stroke-width="2.3" stroke-linejoin="round"/>${labels}<line class="crosshair" x1="${x(selected)}" y1="${bounds.top}" x2="${x(selected)}" y2="243" stroke="var(--muted)" stroke-dasharray="3 4" stroke-width=".8"/><circle cx="${x(selected)}" cy="${y(p.ask)}" r="3.8" fill="var(--blue)" stroke="var(--text)" stroke-width="1.2"/><circle cx="${x(selected)}" cy="${y(p.bid)}" r="3.8" fill="var(--red)" stroke="var(--text)" stroke-width="1.2"/>`;
  $('chart-date').textContent=p.date;
  $('price-chart').dataset.points=rows.length;
  const tip=$('chart-tooltip');
  tip.innerHTML=`<strong>${esc(p.date)}</strong><span style="color:var(--blue)">卖方均价 ${yuan(p.ask)}</span><span style="color:var(--red)">买方均价 ${yuan(p.bid)}</span><span>平台活跃度 ${number(p.activity)} 张</span>`;
  const matrix=svg.getScreenCTM();
  if(matrix){const point=new DOMPoint(x(selected),0).matrixTransform(matrix),box=$('chart-container').getBoundingClientRect();tip.style.left=`${Math.max(4,Math.min(point.x-box.left+12,box.width-172))}px`;}
}
function setupChart(){
  selected=chartRows().length-1;renderChart();
  const box=$('chart-container');
  box.addEventListener('pointermove',event=>{
    const matrix=$('price-chart').getScreenCTM();if(!matrix)return;
    const point=new DOMPoint(event.clientX,event.clientY).matrixTransform(matrix.inverse());
    selected=Math.round(Math.max(0,Math.min(1,(point.x-85)/(780-85)))*(chartRows().length-1));
    $('chart-tooltip').hidden=false;renderChart();
  });
  box.addEventListener('pointerleave',()=>{$('chart-tooltip').hidden=true;});
  box.addEventListener('keydown',event=>{if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();selected+=event.key==='ArrowLeft'?-1:1;$('chart-tooltip').hidden=false;renderChart();}});
  document.querySelectorAll('[data-range]').forEach(button=>button.addEventListener('click',()=>{
    range=Number(button.dataset.range);selected=chartRows().length-1;
    document.querySelectorAll('[data-range]').forEach(b=>{b.classList.toggle('selected',b===button);b.setAttribute('aria-pressed',String(b===button));});
    renderChart();
  }));
}
function renderEvidence(){
  const source=Object.fromEntries(evidence.sources.map(s=>[s.id,s]));
  const p=market.latest;
  const channelRows=[
    {label:'宽泛采销 · 卖均',amount:yuan(p.ask),date:p.date,type:'平台参考',note:'公开接口日点；短交期另询'},
    {label:'宽泛采销 · 买均',amount:yuan(p.bid),date:p.date,type:'平台参考',note:'平台求购均价'},
    {label:'宽泛采销 · 最低挂价',amount:yuan(market.min_ask),date:market.quote_date||'未标明',type:market.condition||'未标明',note:`交期 ${market.delivery||'未标明'}；需确认能否继续锁定`}
  ];
  const rows=channelRows.map(p=>`<tr><td><a class="link" href="${url(market.source_url)}" target="_blank" rel="noopener">${esc(p.label)} ↗</a><small class="evidence-date">${esc(p.date)}</small></td><td>${p.amount}</td><td>${esc(p.type)}</td><td>${esc(p.note)}</td></tr>`);
  const names={smm:'SMM',cls:'财联社',reuters:'Reuters',trendforce:'TrendForce'};
  evidence.prices.forEach(p=>{
    const amount=p.value_usd?`$${number(p.value_usd)}`:p.value_cny?yuan(p.value_cny):p.high_cny?`${number(p.low_cny)}—${number(p.high_cny)}`:`> ${number(p.low_cny)}`;
    rows.push(`<tr><td><a class="link" href="${url(source[p.source_id].url)}" target="_blank" rel="noopener">${esc(names[p.source_id])} ↗</a><small class="evidence-date">${esc(p.observed_at)}</small></td><td>${amount}</td><td>${esc(p.type.replace('（媒体转述）',''))}</td><td>${esc(p.use)}</td></tr>`);
  });
  $('evidence-rows').innerHTML=rows.join('');
  $('watch-rows').innerHTML=market.watchlist.map(p=>`<tr><td>${esc(p.model)}<small>${esc(p.latest.date)}</small></td><td>${yuan(p.latest.ask)}</td><td class="${changeClass(p.stats.day_pct)}">${pct(p.stats.day_pct)}</td></tr>`).join('');
}
function renderIntelligence(){
  const intel=state.intelligence;
  $('intelligence-status').textContent=intel?.status==='workers_ai'?`核心事实与报价含义 · AI摘要已校验 · ${time(intel.generated_at)}`:'核心事实与报价含义 · 来源逐条对应';
  $('intelligence-items').innerHTML=(intel?.items||[]).map(item=>`<article class="intel-item"><div class="intel-meta"><b>${esc(item.source||item.source_id.toUpperCase())}</b><span>${esc(item.date)}</span><small>${esc(item.kind)}</small></div><div class="intel-content"><h3><a href="${url(item.url)}" target="_blank" rel="noopener">${esc(item.title)}</a></h3><p>${esc(item.summary)}</p></div><div class="intel-impact"><span>报价含义</span>${esc(item.impact)}<small>跟踪：${esc(item.watch)}</small></div></article>`).join('');
  $('headline-count').textContent=`${state.headlines.length} 条`;
  document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{
    newsFilter=button.dataset.filter;document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('selected',b===button));renderNews();
  }));renderNews();
}
function category(title){if(/价格|报价|涨价|price/i.test(title))return 'price';if(/限制|批准|出口|管制|export|policy/i.test(title))return 'policy';return 'supply';}
function renderNews(){
  const rows=state.headlines.filter(x=>newsFilter==='all'||category(x.title)===newsFilter);
  $('news-items').innerHTML=rows.length?rows.slice(0,12).map(x=>`<li><a href="${url(x.url)}" target="_blank" rel="noopener">${esc(x.title)} ↗</a><small>${esc(x.publisher)}${x.reprints?.length?` 等${x.reprints.length+1}家`:''} · ${esc(x.published_at.slice(0,10))}</small></li>`).join(''):'<li>当前筛选下没有新增线索。</li>';
}
function renderSources(){
  const checks=Object.fromEntries(state.checks.map(c=>[c.source_id,c]));
  const healthy=state.checks.filter(x=>x.status==='ok').length;
  $('source-status').textContent=`${healthy}/${state.checks.length} 可访问 · 原始日期与采集时间分别记录`;
  const names={nvidia:'NVIDIA 官方产品页',smm:'SMM 预售采访',cls:'财联社估价采访',reuters:'Reuters 订单与供货独家',trendforce:'TrendForce 价格与配额',tansun:'天阳科技合同公告',qudao:'宽泛采销公开行情'};
  $('source-list').innerHTML=evidence.sources.map(s=>{const c=checks[s.id]||{};return `<details class="source-row"><summary><span>${esc(names[s.id])}</span><small>${esc(s.published_at||'动态来源')}</small><small style="color:${c.status==='ok'?'var(--green)':'var(--red)'}">${c.status==='ok'?'可访问':'采集失败'}</small></summary><p>${esc(s.summary)}<br>${esc(s.limitations)}<br>本轮检查 ${time(c.checked_at)} · 上次成功 ${time(c.last_success_at)}${c.error?`<br>${esc(c.error)}`:''}<br><a href="${url(s.url)}" target="_blank" rel="noopener">查看原始来源 ↗</a></p></details>`;}).join('');
  $('audit-items').innerHTML=market.audit.map(a=>`<div class="audit-item"><h3>${esc(a.title)}</h3><p>${esc(a.detail)}</p></div>`).join('');
}
async function load(){
  [evidence,state]=await Promise.all(['evidence.json','state.json'].map(async name=>{const r=await fetch(name,{cache:'no-store'});if(!r.ok)throw new Error(`读取数据失败 ${r.status}`);return r.json();}));
  market=state.channel;if(!market)throw new Error('未取得渠道数据，请阅读报告或查看运行记录。');
  const p=market.latest,stats=market.stats;
  $('update-time').textContent=`本轮更新 ${time(state.checked_at)}`;
  const stale=(Date.now()-new Date(state.checked_at))/3600000>36;
  $('run-state').textContent=stale?'更新超过36小时，请检查运行记录':`下次计划 00:35 · 渠道 ${state.channel_status==='ok'?'采集成功':'沿用上次记录'}`;
  $('ask-price').textContent=yuan(p.ask);$('bid-price').textContent=yuan(p.bid);
  $('ask-change').textContent=`中间值日变动 ${pct(stats.day_pct)}`;$('ask-change').className=changeClass(stats.day_pct);
  $('spread-price').textContent=yuan(stats.spread);$('spread-percent').textContent=`${stats.spread_pct.toFixed(2)}% · 非利润率`;
  $('min-ask').textContent=yuan(market.min_ask);$('max-bid').textContent=yuan(market.max_bid);$('activity').textContent=`${number(p.activity)} 张`;
  $('range-prices').textContent=`${(stats.period_high/10000).toFixed(2)} / ${(stats.period_low/10000).toFixed(2)} 万`;
  $('min-ask-terms').textContent=market.delivery||'交期未标明';
  $('delivery-note').textContent=`${yuan(market.min_ask)} 为${market.condition||'未标明货况'}，交期 ${market.delivery||'未标明'}；原报价 ${market.quote_date||'未标明'}。图中柱形为平台挂牌活跃度。数据采集 ${time(market.collected_at)}。`;
  const official=state.checks.find(c=>c.source_id==='nvidia');
  $('official-status').textContent=official?.status==='ok'&&official.signals.coming_soon?'Coming Soon':'官方状态待复核';
  $('daily-brief').innerHTML=state.daily_brief.items.map(b=>`<div class="brief-item"><h3>${esc(b.title)}</h3><p>${esc(b.text)}</p></div>`).join('');
  const f=evidence.forecast,r=state.forecast_review,base=f.scenarios.find(x=>x.id==='base');
  const anchorSource=evidence.sources.find(s=>s.id===f.anchor_source_id);
  $('anchor-price').textContent=yuan(f.anchor_cny);$('anchor-date').textContent=`${anchorSource?.id==='smm'?'SMM':(anchorSource?.name||'')} · ${f.anchor_observed_at.slice(5)}`;
  $('base-range').textContent=`${(base.low/10000).toFixed(1)}—${(base.high/10000).toFixed(1)} 万 / 张`;
  $('forecast-date').textContent=`首次判断 ${f.issued_at} · 本轮复核 ${r.reviewed_at}`;
  $('forecast-state').textContent={low_confidence:'条件情景',review_required:'待复核',expired:'历史情景'}[r.status];
  if(!r.numeric_forecast_active){document.querySelector('.brief-bottom b').textContent='原预测已到期';}
  if(r.reasons.length){$('forecast-warning').hidden=false;$('forecast-warning').textContent=r.reasons.join('；');}
  $('scenario-rows').innerHTML=[...f.scenarios].sort((a,b)=>(a.id==='base'?-1:b.id==='base'?1:0)).map(x=>`<div class="scenario-row ${esc(x.id)}"><span>${esc(x.name.replace(' / ',' · '))}</span><strong>${x.low/10000}—${x.high/10000} 万</strong><p>${esc(x.trigger)}</p></div>`).join('');
  const gap=f.anchor_cny-p.ask;
  $('forecast-basis').textContent=`平台卖均${yuan(p.ask)}与SMM预售锚点${yuan(f.anchor_cny)}相差${gap<0?'-':''}${yuan(Math.abs(gap))}。区间为价格敏感性情景，未赋概率。新的独立报盘、官方定价或实际发货触发重估。`;
  setupChart();renderEvidence();renderIntelligence();renderSources();
}
load().catch(error=>{$('load-error').hidden=false;$('load-error').textContent=error.message;$('run-state').textContent='数据加载失败 · 可打开研究报告';});
