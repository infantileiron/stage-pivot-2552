import {state} from '../stores/session.js';
import {esc} from '../utils/html.js';
import {badge} from '../components/common/status.js';
import {table} from '../components/common/table.js';
import {money,pct} from '../utils/format.js';

const label={queued:'待计算',running:'计算中',done:'已发布',failed:'计算失败',cancelled:'已取消'};

function lifecycle(e){
 const rows=[
  ['状态',`${esc(label[e.state]||e.state)}${e.state==='done'?' · 已发布':''}`],
  ['尝试 / 重试',`${e.attempt} / ${e.retry_count}`],
  ['冻结明细',`${e.snapshot_checksum?esc(e.snapshot_checksum.slice(0,12))+'…':'—'}（提交时冻结，重试不改变）`],
  ['排队',esc(e.queued_at||'—')],['开始',esc(e.started_at||'—')],['发布',esc(e.published_at||'—')],
  ['执行者',esc(e.worker_id||'—')]
 ];
 return `<div class="lifecycle"><table class="kv"><tbody>${rows.map(([k,v])=>`<tr><th>${k}</th><td>${v}</td></tr>`).join('')}</tbody></table>
 ${e.error?`<p class="notice error-notice">${esc(e.error)}</p>`:''}
 <div class="actions">${e.state==='failed'?`<button class="primary" id="retry">按原编号重试</button>`:''}${e.state==='queued'||e.state==='running'||e.state==='failed'?`<button id="cancel">取消未发布透视</button>`:''}</div>
 <p class="hint">失败后重试沿用同一编号与冻结明细，不新增任务；取消后不保留可下载文件。仅当前执行者可以发布结果。</p></div>`;
}

function timeline(events){
 if(!events.length)return '<p class="hint">暂无生命周期记录。</p>';
 return `<ol class="timeline">${events.map(e=>`<li><span class="tag">${esc(e.from_state||'新建')} → ${esc(e.to_state)}</span><time>${esc(e.created)}</time><p>${esc(e.detail||'')}${e.actor?' · '+esc(e.actor):''}${e.attempt?` · 第 ${e.attempt} 次执行`:''}</p></li>`).join('')}</ol>`;
}

function result(e){
 const r=e.result;
 return `<div class="metrics"><div><strong>${money(r.total.net_cents)}</strong>净结算 / 元</div><div><strong>${pct(r.total.occupancy)}</strong>加权上座率</div><div><strong>${r.total.count}</strong>冻结场次</div><div><strong>${r.conserved?'一致':'异常'}</strong>行列总计守恒</div></div>
 <p>单元格展示净结算 / 元；点击有记录的单元格下钻冻结明细。</p>
 <div class="scroll"><table class="pivot"><thead><tr><th>${esc(e.row_dim)} / ${esc(e.col_dim)}</th>${r.col_keys.map(b=>`<th>${esc(b)}</th>`).join('')}<th>行合计</th></tr></thead><tbody>${r.row_keys.map(a=>`<tr><th>${esc(a)}</th>${r.col_keys.map(b=>{const c=r.cells.find(c=>c.row_key===a&&c.col_key===b);return `<td>${c.count?`<button data-drill-row="${esc(a)}" data-drill-col="${esc(b)}">${money(c.net_cents)}</button><small>${c.count}场 · ${pct(c.occupancy)}</small>`:'—'}</td>`}).join('')}<td>${money(r.row_totals.find(c=>c.key===a).net_cents)}</td></tr>`).join('')}<tr class="total"><th>列合计</th>${r.col_totals.map(c=>`<td>${money(c.net_cents)}</td>`).join('')}<td>${money(r.total.net_cents)}</td></tr></tbody></table></div>
 <p class="notice">${esc(r.method)}</p>
 <div class="actions"><button id="download">下载透视与明细 JSON</button>${e.has_artifact?'':'<span class="hint">结果文件将由服务端按冻结结果校验后重建</span>'}</div>
 ${state.drill?`<h3>冻结下钻：${esc(state.drill.cell.row_key)} × ${esc(state.drill.cell.col_key)}</h3><p>净结算 ${money(state.drill.cell.net_cents)} 元；加权上座率 ${pct(state.drill.cell.occupancy)}</p>${table(['场次','日期','票款 ¥','退款 ¥','渠道费 ¥','净结算 ¥','核验/座位'],state.drill.rows.map(x=>[x.code,x.day,money(x.gross_cents),money(x.refund_cents),money(x.fee_cents),money(x.gross_cents-x.refund_cents-x.fee_cents),x.checked+'/'+x.seats]))}<button id="draft-review">为该单元起草差异复核</button>`:''}`;
}

export function render(){
 const e=state.selected;
 return `<section class="panel"><div class="result-head"><h2>${e?esc(e.name):'选择一份透视方案'} ${e?badge(label[e.state]||e.state):''}</h2><button id="refresh">刷新状态</button></div>
 ${e?lifecycle(e):''}
 ${e&&e.state==='done'&&e.result&&e.result.total?result(e):e?`<p class="notice">${e.state==='cancelled'?'透视已取消，没有可下载结果。':e.state==='failed'?'计算失败：可查上方原因并按原编号重试，不会新增任务。':'后台计算中，请稍后刷新。'}</p>`:'<p class="notice">到透视布局页创建方案，或选择下方历史记录。</p>'}
 ${e?`<h3>状态轨迹</h3>${timeline(state.events||[])}`:''}
 <h3>历史透视</h3>${state.pivots.map(p=>`<button class="study" data-pivot="${p.id}">#${p.id} ${esc(p.name)} · ${esc(label[p.state]||p.state)}${p.retry_count?` · 重试${p.retry_count}次`:''}</button>`).join('')}</section>`;
}
