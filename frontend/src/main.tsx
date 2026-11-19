import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Account = {id:string;product:string;source:string;quote_asset:string};
type Market = {symbol:string;base:string};
type ManualRecord = {qty:string;average:string;close_price:string|null;fee:string;confirm_closed:boolean;time:number;previous_qty:string;previous_average:string};
type Leg = {id:number;account:string;product:string;symbol:string;direction:string;source:string;quote_asset:string;revision:number;qty:string;average:string;net:string;fees:string;funding:string;estimated_funding?:string;funding_complete?:boolean;manual_entered?:boolean;manual_updated_at?:number|null;last_manual?:ManualRecord|null;opened:string;unrealized:string|null;first:number|null;fills:number;synced_at:number|null;error:string|null;snapshot:Record<string,string|number|null>};
type Card = {id:string;base:string;status:string;started_at:number;closed_at:number|null;revised_at:number;legs:Leg[];net:string;total:string|null;annual:string|null;imbalance:string|null;complete:boolean;estimated:boolean;estimated_net:string|null;estimated_total:string|null;estimated_annual:string|null;alerts:string[]};
type Entry = {id:number;account:string;kind:string;source:string;time:number;external_id:string;data:Record<string,string|number|boolean|null>};
type Audit = {time:number;message:string};
const fmt=(v:unknown,d=4)=>v===null||v===undefined?'—':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:d});
const pct=(v:unknown)=>v===null||v===undefined?'—':`${fmt(Number(v)*100,3)}%`;
const date=(v:unknown)=>v?new Date(Number(v)).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'—';
const label=(a:string,p:string)=>`${({binance:'Binance',aster:'Aster',omni:'Omni'} as Record<string,string>)[a]||a} · ${p==='spot'?'现货':'永续'}`;
const states:Record<string,string>={active:'记账中',reconciling:'待核对',archived:'已归档',cancelled:'已取消'};

function ManualEditor({cardId,leg,save,onClose}:{cardId:string;leg:Leg;save:(path:string,body:unknown)=>Promise<void>;onClose:()=>void}){
  const [qty,setQty]=useState(leg.manual_entered?leg.qty:'');
  const [average,setAverage]=useState(leg.manual_entered&&Number(leg.qty)>0?leg.average:'');
  const [closePrice,setClosePrice]=useState('');
  const [fee,setFee]=useState('0');
  const [confirmed,setConfirmed]=useState(false);
  const [replace,setReplace]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const request=useRef({signature:'',id:''});
  const previousQty=replace?leg.last_manual?.previous_qty||'0':leg.qty;
  const previousAverage=replace?leg.last_manual?.previous_average||'0':leg.average;
  const reducing=qty!==''&&Number(qty)<Number(previousQty);
  function correction(value:boolean){
    setReplace(value);setConfirmed(false);setError('');
    setQty(value?leg.last_manual?.qty||'':leg.manual_entered?leg.qty:'');
    setAverage(value?leg.last_manual?.average||'':Number(leg.qty)>0?leg.average:'');
    setClosePrice(value?leg.last_manual?.close_price||'':'');
    setFee(value?leg.last_manual?.fee||'0':'0');
  }
  async function submit(event:React.FormEvent){
    event.preventDefault();setBusy(true);setError('');
    const body={expected_revision:leg.revision,qty,average:Number(qty)>0?(reducing?previousAverage:average):null,
      close_price:reducing?closePrice:null,fee,confirm_closed:Number(qty)===0&&confirmed,replace_last:replace};
    const signature=JSON.stringify(body);
    if(signature!==request.current.signature)request.current={signature,id:crypto.randomUUID()};
    try{await save(`/cards/${cardId}/legs/${leg.id}/manual-position`,{...body,request_id:request.current.id});onClose()}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  return <div className="overlay"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="manual-title">
    <button className="close quiet" disabled={busy} onClick={onClose}>关闭 ×</button><h2 id="manual-title">更新 Omni 仓位</h2>
    <p>{leg.symbol} · {leg.direction==='LONG'?'多头':'空头'} · 价格与费用以 USDC 计</p>
    <form onSubmit={submit}>
      {leg.last_manual&&<label className="check"><input type="checkbox" checked={replace} onChange={e=>correction(e.target.checked)}/>修订最近一次录入（保留原始记录）</label>}
      <label>当前持仓数量<input type="number" min="0" step="any" required value={qty} onChange={e=>{setQty(e.target.value);setConfirmed(false)}}/></label>
      {Number(qty)>0&&<label>开仓均价<input type="number" min="0" step="any" required readOnly={reducing} value={reducing?previousAverage:average} onChange={e=>setAverage(e.target.value)}/></label>}
      {reducing&&<label>本次减仓 / 清仓的实际平仓价<input type="number" min="0" step="any" required value={closePrice} onChange={e=>setClosePrice(e.target.value)}/></label>}
      <label>本次费用（可选，默认 0）<input type="number" min="0" step="any" required value={fee} onChange={e=>setFee(e.target.value)}/></label>
      {qty!==''&&Number(qty)===0&&<label className="check"><input type="checkbox" required={reducing} checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>我已核实 Omni 实际仓位为零</label>}
      <p className="hint">{replace?`修订 ${date(leg.last_manual?.time)} 的录入，并重算受影响的收益。`:'保存后即生效，请在交易后及时更新。'} 数量减仓时保持原均价。资金费仅按公开数据估算，USDC 按 1:1 近似汇总。</p>
      {error&&<p className="error" role="alert">{error}</p>}<button disabled={busy}>{busy?'正在保存…':'保存手工仓位'}</button>
    </form></section></div>;
}

function App(){
  const [token,setToken]=useState('');
  const [user,setUser]=useState('admin');
  const [password,setPassword]=useState('');
  const [accounts,setAccounts]=useState<Account[]>([]);
  const [cards,setCards]=useState<Card[]>([]);
  const [tab,setTab]=useState('active');
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const [creating,setCreating]=useState(false);
  const [choices,setChoices]=useState(['binance:spot','aster:perp']);
  const [markets,setMarkets]=useState<Market[][]>([[],[]]);
  const [symbol,setSymbol]=useState('');
  const [direction,setDirection]=useState('LONG');
  const [selected,setSelected]=useState<Card|null>(null);
  const [entries,setEntries]=useState<Entry[]>([]);
  const [audit,setAudit]=useState<Audit[]>([]);
  const [more,setMore]=useState(false);
  const [updated,setUpdated]=useState<number|null>(null);
  const [pollSeconds,setPollSeconds]=useState(60);
  const [manual,setManual]=useState<{cardId:string;leg:Leg}|null>(null);
  async function api(path:string,init:RequestInit={},auth=token){
    const response=await fetch('/api/v1'+path,{...init,headers:{Authorization:'Basic '+auth,'Content-Type':'application/json'}});
    const data=await response.json();
    if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'请求失败，请检查输入');
    return data;
  }
  async function refresh(auth=token){
    const [a,c]=await Promise.all([api('/accounts',{},auth),api('/cards',{},auth)]);
    setAccounts(a.accounts);setCards(c);setUpdated(Date.now());setPollSeconds(a.poll_seconds||60);
  }
  useEffect(()=>{if(!token)return;let alive=true;const timer=setInterval(()=>{refresh().catch(e=>{if(alive)setError(e.message)})},10000);return()=>{alive=false;clearInterval(timer)}},[token]);
  useEffect(()=>{
    if(!accounts.length)return;
    const valid=choices.every(c=>accounts.some(a=>a.id+':'+a.product===c))&&choices[0].split(':')[0]!==choices[1].split(':')[0];
    if(!valid){const first=accounts[0];const second=accounts.find(a=>a.id!==first.id);if(second)setChoices([first.id+':'+first.product,second.id+':'+second.product])}
  },[accounts.map(a=>a.id+a.product).join(',')]);
  useEffect(()=>{if(choices[0].endsWith(':spot'))setDirection('LONG');else if(choices[1].endsWith(':spot'))setDirection('SHORT')},[choices.join(',')]);
  useEffect(()=>{if(!creating)return;let alive=true;setMarkets([[],[]]);setSymbol('');Promise.all(choices.map(c=>{const [account,product]=c.split(':');return api(`/markets?account=${account}&product=${product}`)})).then(m=>{if(alive){setMarkets(m);const shared=m[0].filter((x:Market)=>m[1].some((y:Market)=>y.base===x.base));setSymbol(shared[0]?.base||'')}}).catch(e=>{if(alive)setError(e.message)});return()=>{alive=false}},[creating,choices.join(',')]);
  async function login(e:React.FormEvent){e.preventDefault();setBusy(true);setError('');try{const auth=btoa(String.fromCharCode(...new TextEncoder().encode(user+':'+password)));await refresh(auth);setToken(auth);setPassword('')}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  async function create(e:React.FormEvent){e.preventDefault();setBusy(true);setError('');try{const legs=choices.map((c,i)=>{const [account,product]=c.split(':');return{account,product,symbol:markets[i].find(m=>m.base===symbol)?.symbol,direction:i===0?direction:direction==='LONG'?'SHORT':'LONG'}});await api('/cards',{method:'POST',body:JSON.stringify({legs})});setCreating(false);await refresh()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  async function details(c:Card){setSelected(c);setEntries([]);setAudit([]);setError('');try{const [rows,history]=await Promise.all([api(`/cards/${c.id}/events`),api(`/cards/${c.id}/audit`)]);setEntries(rows);setMore(rows.length===200);setAudit(history)}catch(e){setError((e as Error).message)}}
  async function loadMore(){if(!selected)return;setBusy(true);try{const rows=await api(`/cards/${selected.id}/events?offset=${entries.length}`);setEntries([...entries,...rows]);setMore(rows.length===200)}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  async function cancel(c:Card){setBusy(true);setError('');try{await api(`/cards/${c.id}/cancel`,{method:'POST'});await refresh()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  const active=cards.filter(c=>['active','reconciling'].includes(c.status));
  const visible=cards.filter(c=>tab==='active'?['active','reconciling'].includes(c.status):['archived','cancelled'].includes(c.status));
  const shared=markets[0].filter(m=>markets[1].some(n=>n.base===m.base));
  const canCreate=new Set(accounts.map(a=>a.id)).size>=2;
  const estimatedCards=cards.filter(c=>c.estimated);
  const recordedTotal=cards.filter(c=>!c.estimated).reduce((n,c)=>n+Number(c.net),0);
  const projectedTotal=estimatedCards.every(c=>c.estimated_net!==null)?recordedTotal+estimatedCards.reduce((n,c)=>n+Number(c.estimated_net),0):null;
  return <><header><a className="brand" href="/">◈ <span>myArbi<small>跨平台套利记账</small></span></a><span className="readonly">只读连接 · REST</span>{token&&<button className="quiet" onClick={()=>{setToken('');setCards([]);setSelected(null);setCreating(false);setManual(null)}}>退出</button>}</header>
    {!token?<main className="login"><div className="eyebrow">YOUR POSITIONS, IN ONE PLACE</div><h1>让每一笔收益<br/>都有据可查。</h1><p>成交、资金费与风险，统一记录。<br/>使用服务器配置的账户登录。</p><form onSubmit={login}><label>用户名<input autoComplete="username" value={user} onChange={e=>setUser(e.target.value)} required/></label><label>密码<input type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} required/></label><button disabled={busy}>{busy?'正在连接…':'进入记账面板 →'}</button></form>{error&&<p className="error" role="alert">{error}</p>}</main>:<main>
    <section className="page-heading"><div><div className="eyebrow">FUNDING ARBITRAGE / OVERVIEW</div><h1>策略账本</h1><p>跟踪双腿仓位，核对每一笔实际收益。</p></div><button onClick={()=>{setCreating(true);setError('')}} disabled={!canCreate}>＋ 创建卡片</button></section>
    {error&&<div className="error" role="alert">{error}<button className="quiet" onClick={()=>setError('')}>关闭</button></div>}
    <section className="stats"><div><span>活跃策略</span><strong>{active.length}<small> 张卡片</small></strong></div><div><span>账本净利 · 自动卡片</span><strong className="profit">{fmt(recordedTotal,2)}<small> USDT</small></strong>{estimatedCards.length>0&&<small>含 Omni 估算总计 {fmt(projectedTotal,2)} ≈USDT</small>}</div><div><span>待核对 / 风险提示</span><strong>{active.filter(c=>c.alerts.length).length}<small> 张卡片</small></strong></div><div><span>数据同步</span><strong className="sync-value">每 {pollSeconds} 秒</strong><small>页面更新 {updated?new Date(updated).toLocaleTimeString('zh-CN'): '—'}</small></div></section>
    <nav><div><button className={tab==='active'?'current':'quiet'} onClick={()=>setTab('active')}>活跃卡片 <b>{active.length}</b></button><button className={tab==='history'?'current':'quiet'} onClick={()=>setTab('history')}>历史记录</button></div><span>自动腿 USDT · Omni USDC（1:1 近似）· 北京时间</span></nav>
    {!canCreate&&<div className="notice">在服务器 .env 中配置至少一个 Binance 或 Aster 账户，即可与 Omni 手工仓位配对。Omni 公共行情无需密钥。</div>}
    {!visible.length?<section className="empty"><div>◇</div><h2>{tab==='active'?'从一张策略卡片开始':'还没有已结束的策略'}</h2><p>{tab==='active'?'选择同一币种的两个平台，启用后自动归集新成交。':'双腿归零并完成两次核对后，卡片会出现在这里。'}</p></section>:<section className="grid">{visible.map(c=><article key={c.id} className="card"><div className="card-top"><div className="coin">{c.base.slice(0,2)}</div><div><h2>{c.base}<span>{c.estimated?"/ USDT ≈ USDC":"/ USDT"}</span></h2><small>{date(c.started_at)}</small></div><span className={'status '+c.status}>{states[c.status]}</span></div>
      <div className="legs">{c.legs.map(l=><div className="leg" key={l.id}><div className="leg-title"><b>{label(l.account,l.product)}{l.source==='manual'?' · 手工':''}</b><span className={l.direction==='LONG'?'long':'short'}>{l.direction==='LONG'?'多':'空'}</span></div><strong>{l.source==='manual'&&!l.manual_entered?'待录入':fmt(l.qty,8)} <small>{c.base}</small></strong><dl><dt>开仓均价</dt><dd>{l.source==='manual'&&!l.manual_entered?'—':fmt(l.average)} {l.quote_asset}</dd><dt>资金费率</dt><dd>{pct(l.snapshot.rate)} {l.snapshot.interval_hours?`/ ${fmt(l.snapshot.interval_hours)}h`:''}</dd><dt>日化费率</dt><dd>{pct(l.snapshot.daily_rate)}</dd><dt>下次结算</dt><dd>{date(l.snapshot.next_funding)}</dd><dt>{l.source==='manual'?'估算资金费':'累计资金费'}</dt><dd>{fmt(l.source==='manual'?l.estimated_funding:l.funding)}{l.funding_complete===false?' · 有缺口':''}</dd><dt>累计手续费</dt><dd>{fmt(l.fees)}</dd><dt>账户杠杆</dt><dd>{l.snapshot.leverage?fmt(l.snapshot.leverage,2)+'×':'—'}</dd><dt>保证金占用率</dt><dd>{pct(l.snapshot.margin_usage)}</dd><dt>强平距离 / ADL</dt><dd>{pct(l.snapshot.liquidation_distance)} / {l.snapshot.adl??'—'}</dd></dl>{l.source==='manual'&&<><small className="manual-time">手工更新 {date(l.manual_updated_at)}</small>{['active','reconciling'].includes(c.status)&&<button className="secondary manual-button" onClick={()=>setManual({cardId:c.id,leg:l})}>更新仓位 / 修订</button>}</>}</div>)}</div>
      <div className="pnl"><div><span>{c.estimated?'估算净利':'已实现净利'}{!c.complete?' · 待核对':''}</span><strong className={(c.estimated?c.estimated_net:c.net)===null?'':Number(c.estimated?c.estimated_net:c.net)>=0?'profit':'loss'}>{fmt(c.estimated?c.estimated_net:c.net,4)} <small>{c.estimated?'≈USDT':'USDT'}</small></strong></div><div><span>{c.estimated?'估算名义资金年化':'名义资金年化'}</span><strong>{pct(c.estimated?c.estimated_annual:c.annual)}</strong></div></div><div className="subline"><span>含浮盈{c.estimated?'估算':''}总计 {fmt(c.estimated?c.estimated_total:c.total)}</span><span>数量偏差 {pct(c.imbalance)}</span></div>
      {c.estimated&&<p className="estimate-note">手工仓位 · 资金费估算 · 1 USDC≈1 USDT<br/>Omni 账户风险不可获取；录入延迟会影响估算。</p>}{c.alerts.length>0&&<ul className="alerts">{c.alerts.map(a=><li key={a}>{a}</li>)}</ul>}<div className="card-actions"><button className="secondary" onClick={()=>details(c)}>查看流水 ↗</button><button disabled title="首期仅记账，执行接口暂未启用">自动下单 · 未启用</button>{c.legs.every(l=>l.fills===0)&&['active','reconciling'].includes(c.status)&&<button disabled={busy} className="quiet" onClick={()=>cancel(c)}>取消</button>}</div><small className="last-sync">最近同步 {date(Math.min(...c.legs.map(l=>l.synced_at||0)))} · 修订 {date(c.revised_at)}</small>
    </article>)}</section>}
    <footer>myArbi v1.0 <span>自动腿按实际流水记账 · Omni 手工录入与估算 · 年化按累计开仓名义价值计算</span></footer>
    {creating&&<div className="overlay"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="create-title"><button className="close quiet" onClick={()=>setCreating(false)}>关闭 ×</button><h2 id="create-title">创建策略卡片</h2><p>启用前请保持对应永续方向空仓。Omni 建仓后需及时手工录入数量和均价。</p><form onSubmit={create}>{[0,1].map(i=><label key={i}>第 {i+1} 条腿<select value={choices[i]} onChange={e=>{const next=[...choices];next[i]=e.target.value;if(i===0&&next[1].split(':')[0]===e.target.value.split(':')[0]){const other=accounts.find(a=>a.id!==e.target.value.split(':')[0]);if(other)next[1]=other.id+':'+other.product}setChoices(next)}}>{accounts.filter(a=>i===0||a.id!==choices[0].split(':')[0]).map(a=><option key={a.id+a.product} value={a.id+':'+a.product}>{label(a.id,a.product)}</option>)}</select></label>)}<label>共同币种<select value={symbol} onChange={e=>setSymbol(e.target.value)} required><option value="">请选择</option>{shared.map(m=><option key={m.symbol} value={m.base}>{m.base}</option>)}</select></label><label>第一条腿方向<select value={direction} onChange={e=>setDirection(e.target.value)}><option value="LONG" disabled={choices[1].endsWith(':spot')}>做多（第二条腿做空）</option><option value="SHORT" disabled={choices[0].endsWith(':spot')}>做空（第二条腿做多）</option></select></label><p className="hint">同一合约方向的新成交会持续归入这张卡片；双腿归零后自动核对并归档。此操作不会下单。</p>{error&&<p className="error" role="alert">{error}</p>}<button disabled={busy||!symbol}>{busy?'检查账户与基线…':'启用记账'}</button></form></section></div>}
    {selected&&<div className="overlay"><section className="modal wide" role="dialog" aria-modal="true" aria-labelledby="detail-title"><button className="close quiet" onClick={()=>setSelected(null)}>关闭 ×</button><h2 id="detail-title">{selected.base} · 策略流水</h2><p>按成交与资金结算时间排列，原始 ID 用于核对。</p><div className="table-wrap"><table><thead><tr><th>时间</th><th>平台</th><th>类型</th><th>数量 / 金额</th><th>价格 / 币种</th><th>手续费</th><th>原始 ID</th></tr></thead><tbody>{entries.map(e=><tr key={e.id}><td>{date(e.time)}</td><td>{e.account}</td><td>{e.kind==='manual_position'?(e.data.replaces?'手工修订':'手工仓位'):e.kind==='estimated_funding'?'估算资金费':e.kind==='estimated_funding_gap'?'估算漏采':e.kind==='fill'?String(e.data.side):String(e.data.type)}</td><td>{e.kind==='estimated_funding_gap'?'缺失':fmt(e.data.qty??e.data.amount,8)}</td><td>{e.kind==='manual_position'?`均价 ${e.data.average}${e.data.close_price?' / 平仓 '+e.data.close_price:''}`:e.data.price??e.data.asset}</td><td>{e.kind==='fill'?`${e.data.fee} ${e.data.fee_asset}`:e.kind==='manual_position'?`${e.data.fee} USDC`:'—'}</td><td>{e.external_id}</td></tr>)}</tbody></table></div>{entries.length===0&&<p className="hint">暂无流水。</p>}{more&&<button disabled={busy} onClick={loadMore}>加载更多</button>}<h3>核对记录</h3>{audit.map((a,i)=><p className="hint" key={i}>{date(a.time)} · {a.message}</p>)}{error&&<p className="error">{error}</p>}</section></div>}
    {manual&&<ManualEditor cardId={manual.cardId} leg={manual.leg} onClose={()=>setManual(null)} save={async(path,body)=>{await api(path,{method:'POST',body:JSON.stringify(body)});await refresh()}}/>}
    </main>}</>;
}
createRoot(document.getElementById('root')!).render(<App/>);
