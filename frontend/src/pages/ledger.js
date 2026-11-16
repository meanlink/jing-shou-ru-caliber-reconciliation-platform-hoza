import {ledger} from '../api/entities.js';
import {workspace} from '../stores/workspace.js';
import {session} from '../stores/session.js';
import {heading} from '../components/common/shell.js';
import {esc,fmt,date,notify} from '../utils/dom.js';
import {submit} from '../hooks/forms.js';
import {parseCSV} from '../utils/csv.js';
import {DailyStatus,IngestStatus,PublishStatus} from '../constants/enums.js';
const METRICS=[['gross','含折扣前收入'],['refunds','退款'],['discount','折扣'],['recognized_net','认可净额'],['visits','有效访问']];
const canWrite=()=>session.user.role!=='viewer';
function traceText(r){
 const t=r.trace||{};
 if(t.kind==='diff')return '由 '+(t.prev_record_id?esc(t.prev_day):'月初零值')+' → '+esc(r.day)+' 累计相减';
 if(t.kind==='gap')return '缺 '+esc(t.gap_from||'')+' 之后至 '+esc(t.gap_to||'')+' 的报数，跨日差额未摊到单日';
 return '—';
}
function dailyTable(rows){
 if(!rows.length)return '<div class="empty">该账期还没有日账。先在左侧接入渠道累计来账。</div>';
 return '<div class="table-wrap"><table><thead><tr><th>日期</th><th>渠道</th><th>状态</th>'+METRICS.map(m=>'<th>'+m[1]+'</th>').join('')+'<th>差分来源</th></tr></thead><tbody>'+rows.map(r=>'<tr class="'+(r.status==='pending'?'row-pending':'')+'"><td>'+esc(r.day)+'</td><td>'+esc(r.channel)+'</td><td><span class="status '+esc(r.status)+'">'+esc(DailyStatus[r.status]||r.status)+'</span></td>'+METRICS.map(m=>'<td>'+(r[m[0]]===null||r[m[0]]===undefined?'—':esc(fmt(r[m[0]])))+'</td>').join('')+'<td class="trace">'+traceText(r)+'</td></tr>').join('')+'</tbody></table></div>';
}
function gapsHtml(gaps){
 if(!gaps.length)return '<p class="hint">没有缺日：所有已报日期都与前一日报数连续。</p>';
 return gaps.map(g=>'<article class="gap-item"><strong>'+esc(g.channel)+'</strong><p>缺 '+esc((g.gap_from||'')+' 之后至 '+(g.gap_to||''))+' 的报数，待补 '+g.days.length+' 天：'+g.days.map(esc).join('、')+'</p><small>未摊差额（不记入任何单日）：'+METRICS.map(m=>m[1]+' '+fmt(g.unallocated?.[m[0]])).join(' · ')+'</small></article>').join('');
}
function checksHtml(checks){
 if(!checks.channels?.length)return '<p class="hint">账期内尚无累计来账，无法核对。</p>';
 return checks.channels.map(c=>'<div class="check-row"><span class="status '+(c.ok?'derived':'failed')+'">'+(c.ok?'核对通过':'未通过')+'</span><strong>'+esc(c.channel)+'</strong><span>报数至 '+esc(c.latest_day)+' · 已生成 '+c.derived_days+' 天'+(c.pending_days.length?' · 待补 '+c.pending_days.length+' 天':'')+'</span>'+(c.problems||[]).map(p=>'<p class="warning">'+esc(p)+'</p>').join('')+'</div>').join('');
}
function effectText(e){
 const fields=Object.entries(e.fields||{}).map(([k,v])=>k+' '+fmt(v[0])+'→'+fmt(v[1])).join('，');
 const st=(e.status&&e.status[0]!==e.status[1])?'状态 '+(DailyStatus[e.status[0]]||'无')+'→'+(DailyStatus[e.status[1]]||'无'):'';
 return esc(e.channel+' '+e.day+'：'+[st,fields,e.note].filter(Boolean).join('；'));
}
function ingestsHtml(list){
 if(!list.length)return '<p class="hint">还没有接账记录。</p>';
 return list.map(b=>'<article class="ingest-item"><div><span class="status '+esc(b.status)+'">'+esc(IngestStatus[b.status]||b.status)+'</span><strong>'+esc(b.source)+'</strong><span>'+b.rows+' 条 · '+date(b.created_at)+'</span></div>'+(b.errors||[]).slice(0,3).map(e=>'<p class="warning">'+esc(e.detail||e.reason||JSON.stringify(e))+'</p>').join('')+((b.effects||[]).length?'<small>影响 '+b.effects.length+' 个日账：'+b.effects.slice(0,3).map(effectText).join('；')+(b.effects.length>3?' …':'')+'</small>':'')+'</article>').join('');
}
function ordersHtml(d){
 if(!d.publish_orders.length)return '<p class="hint">还没有发布单。核对通过后创建发布单，批次号在重试间保持不变。</p>';
 return d.publish_orders.map(o=>'<article class="order-item"><div><span class="status '+esc(o.status)+'">'+esc(PublishStatus[o.status]||o.status)+'</span><strong>第 '+o.batch_no+' 批次</strong><span>'+date(o.created_at)+(o.dataset_id?' · 数据批次 #'+o.dataset_id:'')+(d.current_dataset&&d.current_dataset.id===o.dataset_id?' · 当前可分析':'')+'</span></div>'+(o.error?'<p class="warning">'+esc(o.error)+'</p>':'')+(o.status!=='published'?'<button class="button small" data-publish="'+o.id+'" '+(canWrite()?'':'disabled')+'>'+(o.status==='failed'?'重试发布（沿用批次号）':'执行发布')+'</button>':'')+'</article>').join('');
}
export async function ledgerPage(month){
 const months=await ledger.months();
 const current=month||months[0]?.month||'';
 workspace.ledgerMonth=current;
 const d=current?await ledger.month(current):null;
 const tabs=months.map(m=>'<a class="'+(m.month===current?'active':'')+'" href="#/ledger/'+m.month+'">'+esc(m.month)+(m.pending?' · 待补'+m.pending:'')+'</a>').join('');
 const head=heading('03 / CUMULATIVE LEDGER','累计接账与日账发布','渠道报来的是月内累计数：月初以零为起点，相邻两日累计相减生成日账。缺日保留待补，跨日差额不摊到单日；发布前核对日账合计等于月末累计。');
 if(!d)return head+'<div class="empty">还没有任何账期。通过 API 接入第一批累计来账后开始。</div>';
 const ingestForm='<section class="panel"><div class="section-title"><h2>接账 / 补账</h2><span>迟到记录与更正走同一入口</span></div><form id="ingest-form"><label>来源标识<input name="source" value="manual.json" required></label><label>上传 CSV 或 JSON<input type="file" id="ledger-file" accept=".json,.csv"></label><label>累计来账 JSON<textarea name="records" rows="7" placeholder=\'[{"day":"'+current+'-09","channel":"合作渠道","gross":0,"refunds":0,"discount":0,"recognized_net":0,"visits":0}]\' required></textarea></label><button type="submit" class="primary" '+(canWrite()?'':'disabled')+'>校验并接入 '+esc(current)+'</button><p class="hint">字段：day / channel / gross / refunds / discount / recognized_net / visits，均为月初至今累计值。同一渠道同一日的再次报数视为更正；累计回退或同批重复会整批拒收。补账只需补上缺失日期的累计数。</p></form><div class="section-title"><h2>接账批次</h2><span>'+d.ingests.length+' 批</span></div><div class="ingest-list">'+ingestsHtml(d.ingests)+'</div></section>';
 const publishPanel='<section class="panel"><div class="section-title"><h2>发布前核对</h2><span>日账合计 = 月末累计</span></div>'+checksHtml(d.checks)+'<div class="section-title"><h2>发布单</h2><span>一次性切换可分析批次</span></div><button class="primary" id="create-order" '+(canWrite()?'':'disabled')+'>创建发布单（下一批次号）</button><div class="order-list">'+ordersHtml(d)+'</div>'+(d.current_dataset?'<p class="hint">当前可分析批次：#'+d.current_dataset.id+' · '+esc(d.current_dataset.name)+'。发布新批次后，基于旧批次的试算将失效并拒绝批准；已批准资料保留原值。</p>':'<p class="hint">该账期还没有可分析批次。</p>')+'</section>';
 const daily='<section class="panel"><div class="section-title"><h2>日账</h2><span>'+d.daily.length+' 行 · 待补 '+d.daily.filter(r=>r.status==='pending').length+' 天</span></div>'+dailyTable(d.daily)+'</section>';
 const gaps='<section class="panel"><div class="section-title"><h2>缺日待补</h2><span>'+d.gaps.length+' 段缺口</span></div>'+gapsHtml(d.gaps)+'</section>';
 return head+'<div class="month-tabs">'+tabs+'</div><div class="ledger-grid">'+ingestForm+publishPanel+'</div>'+gaps+daily;
}
export function bindLedger(refresh){
 const month=workspace.ledgerMonth,form=document.querySelector('#ingest-form');
 document.querySelector('#ledger-file')?.addEventListener('change',async e=>{try{const file=e.target.files[0];if(!file)return;const text=await file.text(),records=file.name.endsWith('.csv')?parseCSV(text):JSON.parse(text);document.querySelector('[name=records]').value=JSON.stringify(records,null,2);document.querySelector('[name=source]').value=file.name;}catch(error){notify(error.message,true);}});
 if(form)submit(form,async f=>{const b=await ledger.ingest(month,{source:f.get('source'),records:JSON.parse(f.get('records'))});if(b.status==='accepted')notify('已接收 '+b.rows+' 条，影响 '+(b.effects||[]).length+' 个日账');else notify('整批拒收：'+((b.errors||[])[0]?.detail||'累计回退或自然键重复'),true);await refresh();});
 document.querySelector('#create-order')?.addEventListener('click',async()=>{try{const o=await ledger.createOrder(month);notify('发布单已创建：第 '+o.batch_no+' 批次');await refresh();}catch(e){notify(e.message,true);}});
 document.querySelectorAll('[data-publish]').forEach(b=>b.onclick=async()=>{try{const o=await ledger.publish(b.dataset.publish);if(o.status==='published')notify('第 '+o.batch_no+' 批次已发布，可分析批次已一次性切换');else notify('核对未过：'+(o.error||'存在缺日待补'),true);await refresh();}catch(e){notify(e.message,true);}});
}
