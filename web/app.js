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
  const board=state.price_board,fx=board?.fx||{};
  if(!board){$('evidence-rows').innerHTML='<tr><td colspan="4">价格证据表在下一轮采集后生成。</td></tr>';return;}
  const changes=Object.fromEntries(board.changes.map(c=>[c.id,c]));
  const rows=board.rows.map(r=>{
    const c=changes[r.id],flag=c?` <span class="badge amber">${c.kind==='新报价'?'今日新报价':`汇率 ${c.delta>0?'+':''}${number(c.delta)}`}</span>`:'';
    const when=r.kind==='海外零售'?`${r.date} 起此价未变${r.check_status==='ok'&&r.checked?` · ${r.checked.slice(5)} 核对`:' · 本轮未读到页面'}`:`${r.date} · ${r.age_days} 天前`;
    const amount=r.low?esc(r.text):esc(r.native);
    const note=[r.converted?r.native:'',r.note].filter(Boolean).join('；');
    return `<tr><td><a class="link" href="${url(r.url)}" target="_blank" rel="noopener">${esc(r.label)} ↗</a>${flag}<small class="evidence-date">${esc(when)}</small></td><td>${amount}</td><td>${esc(r.kind)}</td><td>${esc(note)}</td></tr>`;
  });
  $('evidence-rows').innerHTML=rows.join('');
  $('fx-note').textContent=fx.rates?`每条报价按原始日期列出 · 海外价格按${fx.label} ${fx.date}${fx.status==='carried'?'（沿用）':''}折算，不是新报价`:'每条报价按原始日期列出 · 本轮未取得汇率，海外价格只列原币';
  const digest=state.digest;
  $('today-change').innerHTML=digest?`<b>今日新增：${esc(digest.headline)}</b>${digest.items.map(i=>`<br>[${esc(i.tag)}] ${i.url?`<a class="link" href="${url(i.url)}" target="_blank" rel="noopener">${esc(i.text)} ↗</a>`:esc(i.text)}`).join('')}`:`今日变化：${esc(board.summary)}`;
  const byId=Object.fromEntries(board.rows.map(r=>[r.id,r]));
  const dom=board.domestic,usd=byId.reuters_usd,retail=board.rows.find(r=>r.kind==='海外零售'&&r.cny_vat);
  if(dom){$('kpi-domestic').textContent=`${dom.low/10000}—${dom.high/10000} 万`;$('kpi-domestic-sub').textContent=`${dom.count} 条来源 · 最新 ${dom.latest_date.slice(5)} ${dom.latest_label}`;}
  if(usd?.cny_vat){$('kpi-usd').textContent=yuan(usd.cny_vat);const move=changes.reuters_usd?.delta;$('kpi-usd-sub').textContent=`${usd.native} × ${fx.rates.USD}${move?` · 日 ${move>0?'+':''}${number(move)}`:''}`;}
  if(retail){$('kpi-retail').textContent=yuan(retail.cny_vat);$('kpi-retail-sub').textContent=`${retail.native.split('（')[0]} · ${retail.label}`;}
  $('watch-rows').innerHTML=market.watchlist.map(p=>`<tr><td>${esc(p.model)}</td><td>${p.min_ask?yuan(p.min_ask):'—'}</td><td>${esc(p.quote_date||'未标明')}</td></tr>`).join('');
}
function renderIntelligence(){
  const intel=state.intelligence;
  $('intelligence-status').textContent=intel?.status==='workers_ai'?`核心事实与报价含义 · AI摘要已校验 · ${time(intel.generated_at)}`:'核心事实与报价含义 · 来源逐条对应';
  $('intelligence-items').innerHTML=(intel?.items||[]).map(item=>`<article class="intel-item"><div class="intel-meta"><b>${esc(item.source||item.source_id.toUpperCase())}</b><span>${esc(item.date)}</span><small>${esc(item.kind)}</small></div><div class="intel-content"><h3><a href="${url(item.url)}" target="_blank" rel="noopener">${esc(item.title)}</a></h3><p>${esc(item.summary)}</p></div><div class="intel-impact"><span>报价含义</span>${esc(item.impact)}<small>跟踪：${esc(item.watch)}</small></div></article>`).join('');
  const feed=state.feed?.items||[];
  $('feed-status').textContent=feed.length?`AI 读原文并交叉核对 · ${feed.length} 条 · 更新 ${time(state.feed.updated_at)}`:'暂无通过核对的新增情报';
  $('feed-items').innerHTML=feed.map(item=>`<article class="intel-item"><div class="intel-meta"><b>${esc(item.publisher)}</b><span>${esc(item.published_at)}</span><small class="badge ${item.grade==='C'?'':'amber'}">${esc(item.tier||'核实')} · ${esc(item.grade)} ${esc(item.grade_label)}</small></div><div class="intel-content"><h3><a href="${url(item.url)}" target="_blank" rel="noopener">${esc(item.title)}</a></h3><p>${esc(item.summary)}</p>${(item.claims||[]).length?`<ul class="claims">${item.claims.map(c=>`<li class="claim-${c.status==='有出处'?'ok':c.status==='推算'?'calc':'bad'}"><b>${esc(c.status)}</b>${esc(c.text)}${c.ref?` <a href="${url(c.ref)}" target="_blank" rel="noopener">出处 ↗</a>`:''}</li>`).join('')}</ul>`:''}</div><div class="intel-impact"><span>报价含义</span>${esc(item.impact)}<small>跟踪：${esc(item.watch)}${item.corroboration.length?` · 交叉印证 ${item.corroboration.length} 处`:''}</small></div></article>`).join('');
  const leads=state.feed?.leads||[];
  $('leads-count').textContent=`${leads.length} 条`;
  $('leads-items').innerHTML=leads.length?leads.map(x=>`<li><span><a href="${url(x.url)}" target="_blank" rel="noopener">${esc(x.title)} ↗</a>${x.snippet?`<br><small>${esc(x.snippet)}</small>`:''}</span><small>${esc(x.publisher)}${x.published_at?` · ${esc(x.published_at)}`:''}${x.found_via?` · ${esc(x.found_via)}`:''}</small></li>`).join(''):'<li>暂无未核实线索。</li>';
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
  const bad=state.quotes_rejected||[];
  $('source-status').textContent=`${healthy}/${state.checks.length} 可访问 · 原始日期与采集时间分别记录${bad.length?` · ${bad.length} 条登记报价未采用：${bad.map(x=>`${x.line}（${x.reason}）`).join('；')}`:''}`;
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
  const template=market.template||{};
  if(template.synthetic){$('template-badge').textContent='模板存档 · 不计涨跌';$('template-warning').hidden=false;$('template-warning').textContent=`这条曲线${template.reasons.join('，')}。它的日涨跌不代表行情，只保留作存档。`;}
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
  const dom=state.price_board?.domestic;
  $('forecast-basis').textContent=`${dom?`已披露的大陆报价在${yuan(dom.low)}至${yuan(dom.high)}之间，`:''}SMM预售锚点${yuan(f.anchor_cny)}。区间为价格敏感性情景，未赋概率。新的独立报盘、官方定价或实际发货触发重估。`;
  setupChart();renderEvidence();renderIntelligence();renderSources();
}
load().catch(error=>{$('load-error').hidden=false;$('load-error').textContent=error.message;$('run-state').textContent='数据加载失败 · 可打开研究报告';});
