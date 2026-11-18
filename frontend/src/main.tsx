import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

type Account = {id:string;product:string};
type Market = {symbol:string;base:string};
type Leg = {id:number;account:string;product:string;symbol:string;direction:string;qty:string;average:string;net:string;fees:string;funding:string;opened:string;unrealized:string|null;first:number|null;fills:number;synced_at:number|null;error:string|null;snapshot:Record<string,string|number|null>};
type Card = {id:string;base:string;status:string;started_at:number;closed_at:number|null;revised_at:number;legs:Leg[];net:string;total:string|null;annual:string|null;imbalance:string;complete:boolean;alerts:string[]};
type Entry = {id:number;account:string;kind:string;time:number;external_id:string;data:Record<string,string>};
type Audit = {time:number;message:string};
const fmt=(v:unknown,d=4)=>v===null||v===undefined?'—':Number(v).toLocaleString('zh-CN',{maximumFractionDigits:d});
const pct=(v:unknown)=>v===null||v===undefined?'—':`${fmt(Number(v)*100,3)}%`;
const date=(v:unknown)=>v?new Date(Number(v)).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'—';
const label=(a:string,p:string)=>`${a==='binance'?'Binance':'Aster'} · ${p==='spot'?'现货':'永续'}`;
const states:Record<string,string>={active:'记账中',reconciling:'待核对',archived:'已归档',cancelled:'已取消'};

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
  async function api(path:string,init:RequestInit={},auth=token){
    const response=await fetch('/api/v1'+path,{...init,headers:{Authorization:'Basic '+auth,'Content-Type':'application/json'}});
    const data=await response.json();
    if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'请求失败，请检查输入');
    return data;
  }
  async function refresh(auth=token){
    const [a,c]=await Promise.all([api('/accounts',{},auth),api('/cards',{},auth)]);
    setAccounts(a.accounts);setCards(c);setUpdated(Date.now());
  }
  useEffect(()=>{if(!token)return;let alive=true;const timer=setInterval(()=>{refresh().catch(e=>{if(alive)setError(e.message)})},10000);return()=>{alive=false;clearInterval(timer)}},[token]);
  useEffect(()=>{if(!creating)return;let alive=true;setMarkets([[],[]]);setSymbol('');Promise.all(choices.map(c=>{const [account,product]=c.split(':');return api(`/markets?account=${account}&product=${product}`)})).then(m=>{if(alive){setMarkets(m);const shared=m[0].filter((x:Market)=>m[1].some((y:Market)=>y.base===x.base));setSymbol(shared[0]?.base||'')}}).catch(e=>{if(alive)setError(e.message)});return()=>{alive=false}},[creating,choices.join(',')]);
  async function login(e:React.FormEvent){e.preventDefault();setBusy(true);setError('');try{const auth=btoa(String.fromCharCode(...new TextEncoder().encode(user+':'+password)));await refresh(auth);setToken(auth);setPassword('')}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  async function create(e:React.FormEvent){e.preventDefault();setBusy(true);setError('');try{const legs=choices.map((c,i)=>{const [account,product]=c.split(':');return{account,product,symbol:markets[i].find(m=>m.base===symbol)?.symbol,direction:i===0?direction:direction==='LONG'?'SHORT':'LONG'}});await api('/cards',{method:'POST',body:JSON.stringify({legs})});setCreating(false);await refresh()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  async function details(c:Card){setSelected(c);setEntries([]);setAudit([]);setError('');try{const [rows,history]=await Promise.all([api(`/cards/${c.id}/events`),api(`/cards/${c.id}/audit`)]);setEntries(rows);setMore(rows.length===200);setAudit(history)}catch(e){setError((e as Error).message)}}
  async function loadMore(){if(!selected)return;setBusy(true);try{const rows=await api(`/cards/${selected.id}/events?offset=${entries.length}`);setEntries([...entries,...rows]);setMore(rows.length===200)}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  async function cancel(c:Card){setBusy(true);setError('');try{await api(`/cards/${c.id}/cancel`,{method:'POST'});await refresh()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  const active=cards.filter(c=>['active','reconciling'].includes(c.status));
  const visible=cards.filter(c=>tab==='active'?['active','reconciling'].includes(c.status):['archived','cancelled'].includes(c.status));
  const shared=markets[0].filter(m=>markets[1].some(n=>n.base===m.base));
  return <><header><a className="brand" href="/">◈ <span>myArbi<small>跨平台套利记账</small></span></a><span className="readonly">只读连接 · REST</span>{token&&<button className="quiet" onClick={()=>{setToken('');setCards([]);setSelected(null);setCreating(false)}}>退出</button>}</header>
    {!token?<main className="login"><div className="eyebrow">YOUR POSITIONS, IN ONE PLACE</div><h1>让每一笔收益<br/>都有据可查。</h1><p>成交、资金费与风险，统一记录。<br/>使用服务器配置的账户登录。</p><form onSubmit={login}><label>用户名<input autoComplete="username" value={user} onChange={e=>setUser(e.target.value)} required/></label><label>密码<input type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} required/></label><button disabled={busy}>{busy?'正在连接…':'进入记账面板 →'}</button></form>{error&&<p className="error" role="alert">{error}</p>}</main>:<main>
    <section className="page-heading"><div><div className="eyebrow">FUNDING ARBITRAGE / OVERVIEW</div><h1>策略账本</h1><p>跟踪双腿仓位，核对每一笔实际收益。</p></div><button onClick={()=>{setCreating(true);setError('')}} disabled={accounts.length<2}>＋ 创建卡片</button></section>
    {error&&<div className="error" role="alert">{error}<button className="quiet" onClick={()=>setError('')}>关闭</button></div>}
    <section className="stats"><div><span>活跃策略</span><strong>{active.length}<small> 张卡片</small></strong></div><div><span>已实现净利 · 全部卡片</span><strong className="profit">{fmt(cards.reduce((n,c)=>n+Number(c.net),0),2)}<small> USDT</small></strong></div><div><span>待核对 / 风险提示</span><strong>{active.filter(c=>c.alerts.length).length}<small> 张卡片</small></strong></div><div><span>数据同步</span><strong className="sync-value">每 60 秒</strong><small>页面更新 {updated?new Date(updated).toLocaleTimeString('zh-CN'): '—'}</small></div></section>
    <nav><div><button className={tab==='active'?'current':'quiet'} onClick={()=>setTab('active')}>活跃卡片 <b>{active.length}</b></button><button className={tab==='history'?'current':'quiet'} onClick={()=>setTab('history')}>历史记录</button></div><span>金额以 USDT 计 · 北京时间</span></nav>
    {!accounts.length&&<div className="notice">尚未配置平台账户。在服务器 .env 中填写 Binance 与 Aster 凭据并重启后，即可创建卡片。</div>}
    {!visible.length?<section className="empty"><div>◇</div><h2>{tab==='active'?'从一张策略卡片开始':'还没有已结束的策略'}</h2><p>{tab==='active'?'选择同一币种的两个平台，启用后自动归集新成交。':'双腿归零并完成两次核对后，卡片会出现在这里。'}</p></section>:<section className="grid">{visible.map(c=><article key={c.id} className="card"><div className="card-top"><div className="coin">{c.base.slice(0,2)}</div><div><h2>{c.base}<span>/ USDT</span></h2><small>{date(c.started_at)}</small></div><span className={'status '+c.status}>{states[c.status]}</span></div>
      <div className="legs">{c.legs.map(l=><div className="leg" key={l.id}><div className="leg-title"><b>{label(l.account,l.product)}</b><span className={l.direction==='LONG'?'long':'short'}>{l.direction==='LONG'?'多':'空'}</span></div><strong>{fmt(l.qty,8)} <small>{c.base}</small></strong><dl><dt>开仓均价</dt><dd>{fmt(l.average)}</dd><dt>资金费率</dt><dd>{pct(l.snapshot.rate)} {l.snapshot.interval_hours?`/ ${fmt(l.snapshot.interval_hours)}h`:''}</dd><dt>日化费率</dt><dd>{pct(l.snapshot.daily_rate)}</dd><dt>下次结算</dt><dd>{date(l.snapshot.next_funding)}</dd><dt>累计资金费</dt><dd>{fmt(l.funding)}</dd><dt>累计手续费</dt><dd>{fmt(l.fees)}</dd><dt>账户杠杆</dt><dd>{l.snapshot.leverage?fmt(l.snapshot.leverage,2)+'×':'—'}</dd><dt>保证金占用率</dt><dd>{pct(l.snapshot.margin_usage)}</dd><dt>强平距离 / ADL</dt><dd>{pct(l.snapshot.liquidation_distance)} / {l.snapshot.adl??'—'}</dd></dl></div>)}</div>
      <div className="pnl"><div><span>已实现净利{!c.complete?' · 待核对':''}</span><strong className={Number(c.net)>=0?'profit':'loss'}>{fmt(c.net,4)} <small>USDT</small></strong></div><div><span>名义资金年化</span><strong>{pct(c.annual)}</strong></div></div><div className="subline"><span>含浮盈总计 {fmt(c.total)}</span><span>数量偏差 {pct(c.imbalance)}</span></div>
      {c.alerts.length>0&&<ul className="alerts">{c.alerts.map(a=><li key={a}>{a}</li>)}</ul>}<div className="card-actions"><button className="secondary" onClick={()=>details(c)}>查看流水 ↗</button><button disabled title="首期仅记账，执行接口暂未启用">自动下单 · 未启用</button>{c.legs.every(l=>l.fills===0)&&['active','reconciling'].includes(c.status)&&<button disabled={busy} className="quiet" onClick={()=>cancel(c)}>取消</button>}</div><small className="last-sync">最近同步 {date(Math.min(...c.legs.map(l=>l.synced_at||0)))} · 修订 {date(c.revised_at)}</small>
    </article>)}</section>}
    <footer>myArbi v1.0 <span>实际资金费按账户流水入账 · 年化以累计开仓名义价值计算</span></footer>
    {creating&&<div className="overlay"><section className="modal" role="dialog" aria-modal="true" aria-labelledby="create-title"><button className="close quiet" onClick={()=>setCreating(false)}>关闭 ×</button><h2 id="create-title">创建策略卡片</h2><p>启用前请保持对应永续方向空仓。</p><form onSubmit={create}>{[0,1].map(i=><label key={i}>第 {i+1} 条腿<select value={choices[i]} onChange={e=>{const next=[...choices];next[i]=e.target.value;setChoices(next)}}>{accounts.map(a=><option key={a.id+a.product} value={a.id+':'+a.product}>{label(a.id,a.product)}</option>)}</select></label>)}<label>共同币种<select value={symbol} onChange={e=>setSymbol(e.target.value)} required><option value="">请选择</option>{shared.map(m=><option key={m.symbol} value={m.base}>{m.base}</option>)}</select></label><label>第一条腿方向<select value={direction} onChange={e=>setDirection(e.target.value)}><option value="LONG">做多（第二条腿做空）</option><option value="SHORT">做空（第二条腿做多）</option></select></label><p className="hint">同一合约方向的新成交会持续归入这张卡片；双腿归零后自动核对并归档。此操作不会下单。</p>{error&&<p className="error" role="alert">{error}</p>}<button disabled={busy||!symbol}>{busy?'检查账户与基线…':'启用记账'}</button></form></section></div>}
    {selected&&<div className="overlay"><section className="modal wide" role="dialog" aria-modal="true" aria-labelledby="detail-title"><button className="close quiet" onClick={()=>setSelected(null)}>关闭 ×</button><h2 id="detail-title">{selected.base} · 策略流水</h2><p>按成交与资金结算时间排列，原始 ID 用于核对。</p><div className="table-wrap"><table><thead><tr><th>时间</th><th>平台</th><th>类型</th><th>数量 / 金额</th><th>价格 / 币种</th><th>手续费</th><th>原始 ID</th></tr></thead><tbody>{entries.map(e=><tr key={e.id}><td>{date(e.time)}</td><td>{e.account}</td><td>{e.kind==='fill'?e.data.side:e.data.type}</td><td>{fmt(e.data.qty??e.data.amount,8)}</td><td>{e.data.price??e.data.asset}</td><td>{e.kind==='fill'?`${e.data.fee} ${e.data.fee_asset}`:'—'}</td><td>{e.external_id}</td></tr>)}</tbody></table></div>{entries.length===0&&<p className="hint">暂无流水。</p>}{more&&<button disabled={busy} onClick={loadMore}>加载更多</button>}<h3>核对记录</h3>{audit.map((a,i)=><p className="hint" key={i}>{date(a.time)} · {a.message}</p>)}{error&&<p className="error">{error}</p>}</section></div>}
    </main>}</>;
}
createRoot(document.getElementById('root')!).render(<App/>);
