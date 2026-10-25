const $ = id => document.getElementById(id);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeURL = value => { try { const url = new URL(value); return url.protocol === 'https:' ? escapeHTML(url.href) : '#'; } catch { return '#'; } };
const money = n => Number(n).toLocaleString('zh-CN', {maximumFractionDigits:0});
const time = value => value ? new Date(value).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai',hour12:false}) : '无成功记录';

async function load() {
  const [e, s] = await Promise.all(['evidence.json','state.json'].map(async url => { const response = await fetch(url, {cache:'no-store'}); if (!response.ok) throw new Error(`数据读取失败 ${response.status}`); return response.json(); }));
  const sources = Object.fromEntries(e.sources.map(x => [x.id,x]));
  const checks = Object.fromEntries(s.checks.map(x => [x.source_id,x]));
  $('edition-date').textContent = `本轮采集 ${time(s.checked_at)} 北京时间`;
  const official = checks.nvidia;
  $('official-status').textContent = official?.status === 'ok' ? (official.signals.needs_review ? '官方页面标记或价格信息变化 / 待复核' : '官方页面：Coming Soon / 定价请核对原文') : '官方页面采集失败 / 请查看来源状态';
  const healthy = s.checks.filter(x => x.status === 'ok').length;
  const age = (Date.now() - new Date(s.checked_at)) / 3600000;
  const status = $('run-status');
  status.textContent = `来源可访问 ${healthy}/${s.checks.length} · 新闻检索 ${s.feeds.filter(x=>x.status==='ok').length}/${s.feeds.length} · 本轮新增已核验价格 ${s.new_verified_price_count} 条 · ${age > 36 ? '更新已超过 36 小时，请检查运行记录' : '没有新证据时沿用原预测，报价日期保持不变'}`;
  if (healthy < s.checks.length || age > 36) status.classList.add('warn');
  $('price-rows').innerHTML = e.prices.map(p => {
    const label = p.value_usd ? `$${money(p.value_usd)}` : p.value_cny ? `¥${money(p.value_cny)}` : p.high_cny ? `¥${money(p.low_cny)}-${money(p.high_cny)}` : `> ¥${money(p.low_cny)}`;
    return `<tr><td>${label}<a href="${safeURL(sources[p.source_id].url)}" target="_blank" rel="noopener">${escapeHTML(p.source_id.toUpperCase())} 原文 ↗</a></td><td>${escapeHTML(p.type)}</td><td>${escapeHTML(p.observed_at)}</td><td>${escapeHTML(p.use)}</td></tr>`;
  }).join('');
  const forecast = e.forecast, review = s.forecast_review;
  $('forecast-date').textContent = `首次发布 ${forecast.issued_at} · 观察期限至 ${forecast.horizon_end} · 本轮复核 ${review.reviewed_at}`;
  $('forecast-state').textContent = {low_confidence:'低置信度 · 条件预测',review_required:'证据陈旧或变化 · 待复核',expired:'数值预测已失效'}[review.status];
  $('forecast-summary').textContent = review.numeric_forecast_active ? forecast.thesis : '价格锚点或预测期限已失效。下方保留历史情景，不作为当前有效预测。';
  if (review.reasons.length) { $('forecast-warning').hidden = false; $('forecast-warning').textContent = review.reasons.join('；'); }
  $('scenario-list').innerHTML = forecast.scenarios.map(x => `<div class="scenario ${escapeHTML(x.id)}"><div class="scenario-label">${escapeHTML(x.name)}${review.numeric_forecast_active ? '' : '（历史）'}</div><div class="scenario-track" aria-hidden="true"><div class="scenario-bar" style="left:${(x.low-75000)/45000*100}%;width:${(x.high-x.low)/45000*100}%"></div></div><div class="scenario-price">${money(x.low/10000*10)/10}-${money(x.high/10000*10)/10} 万</div><p class="scenario-trigger">条件：${escapeHTML(x.trigger)}</p></div>`).join('');
  $('news-date').textContent = `${s.headlines_carried_forward ? '本轮检索失败，保留上次线索。' : '标题线索，尚未核验正文。'} 线索采集：${time(s.headline_collection_at)}`;
  $('news-items').innerHTML = s.headlines.length ? s.headlines.slice(0,9).map(x => `<li><a href="${safeURL(x.url)}" target="_blank" rel="noopener">${escapeHTML(x.title)} ↗</a><small>${escapeHTML(x.publisher)} · 原发布 ${time(x.published_at)} · 待核实</small></li>`).join('') : '<li><p>本轮没有取得可展示的新标题线索。原有已核查资料保留在左侧及来源清单。</p></li>';
  $('source-list').innerHTML = e.sources.map(x => { const c = checks[x.id] || {}; return `<article class="source-item"><div><a href="${safeURL(x.url)}" target="_blank" rel="noopener">${escapeHTML(x.name)} ↗</a><br><small>原始日期 ${escapeHTML(x.published_at || '动态页面 / 无固定发布日期')}</small></div><div class="source-detail"><p>${escapeHTML(x.summary)}</p><p>${escapeHTML(x.limitations)}</p><small>本轮检查 ${time(c.checked_at)} · 最近成功 ${time(c.last_success_at)}${c.error ? ` · 错误：${escapeHTML(c.error)}` : ''}${c.changed_since_last ? ' · 状态发生变化，需复核' : ''}</small></div><div class="source-state ${c.status === 'ok' ? 'ok' : 'failed'}">${x.kind === 'excluded_aggregate' ? '排除出基准' : c.status === 'ok' ? '原来源可访问' : '采集失败'}</div></article>`; }).join('');
}

function calculate() {
  const values = ['cost','fees','revenue','quantity'].map(id => Number($(id).value));
  const [cost,fees,revenue,quantity] = values;
  if (values.some(n=>!Number.isFinite(n)) || ['cost','fees','revenue','quantity'].some(id=>$(id).value==='') || cost<0 || fees<0 || revenue<=0 || quantity<1 || !Number.isInteger(quantity)) {
    $('contribution').textContent = '请输入有效金额和整数数量'; $('margin').textContent = ''; return;
  }
  const per = revenue - cost - fees;
  $('contribution').textContent = `${per < 0 ? '-' : ''}¥${money(Math.abs(per * quantity))}`;
  $('contribution').classList.toggle('negative', per < 0);
  $('margin').textContent = `经营贡献率 ${(per/revenue*100).toFixed(2)}% · 单张贡献 ${per<0?'-':''}¥${money(Math.abs(per))}`;
}
['cost','fees','revenue','quantity'].forEach(id=>$(id).addEventListener('input', calculate));
calculate();
load().catch(error => { $('run-status').textContent = `数据加载失败：${error.message}。请阅读完整 PDF 或查看更新记录。`; $('run-status').classList.add('warn'); });
