const $=id=>document.getElementById(id);
const fmt=(v,d=4)=>v==null||Number.isNaN(Number(v))?"-":Number(v).toFixed(d);
const pct=v=>`${(Number(v||0)*100).toFixed(1)}%`;
const esc=v=>String(v??"").replace(/[&<>\"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[c]));

async function api(path){
  const response=await fetch(path);
  const body=await response.json().catch(()=>({}));
  if(!response.ok) throw Error(body.detail||"Request failed");
  return body;
}

function renderSummary(stats){
  const cards=[
    ["Equity",`${fmt(stats.equity,2)} USDT`,stats.equity>=stats.initial_balance?"positive":"negative",`initial ${fmt(stats.initial_balance,2)}`],
    ["Realized PnL",`${fmt(stats.realized_pnl,4)} USDT`,stats.realized_pnl>=0?"positive":"negative","closed trades"],
    ["Unrealized PnL",`${fmt(stats.unrealized_pnl,4)} USDT`,stats.unrealized_pnl>=0?"positive":"negative","open positions"],
    ["Win rate",pct(stats.win_rate),stats.win_rate>=.5?"positive":"negative",`${stats.winning_trades} wins / ${stats.losing_trades} losses`],
    ["Profit factor",fmt(stats.profit_factor,2),stats.profit_factor>=1?"positive":"negative",`max DD ${fmt(stats.max_drawdown,2)} USDT`],
  ];
  $("pnl-summary").innerHTML=cards.map(card=>`<div class="metric-card"><span>${card[0]}</span><strong class="${card[2]}">${card[1]}</strong><small>${card[3]}</small></div>`).join("");
}

function renderCurve(points){
  const svg=$("equity-chart");
  if(!points||points.length<2){svg.innerHTML='<text x="500" y="150" text-anchor="middle" fill="#8593a3" font-size="13">Close paper trades to build the equity curve.</text>';return;}
  const values=points.map(point=>point.equity);
  const min=Math.min(...values), max=Math.max(...values), range=max-min||1;
  const coordinates=points.map((point,index)=>`${(index/(points.length-1))*980+10},${280-((point.equity-min)/range)*250}`).join(" ");
  svg.innerHTML=`<polygon points="10,280 ${coordinates} 990,280"/><polyline points="${coordinates}"/><line x1="10" y1="280" x2="990" y2="280" stroke="#263442"/><text x="12" y="18" fill="#8593a3" font-size="11">${fmt(max,2)} USDT</text><text x="12" y="295" fill="#8593a3" font-size="11">${fmt(min,2)} USDT</text>`;
}

function renderTrades(trades){
  $("trades").innerHTML=trades.length?`<table><thead><tr><th>Opened</th><th>Symbol</th><th>Side</th><th>Entry</th><th>Exit / mark</th><th>Stop</th><th>Target</th><th>PnL</th><th>Status</th><th>Reason</th></tr></thead><tbody>${trades.map(trade=>`<tr><td>${new Date(trade.opened_at).toLocaleString()}</td><td>${esc(trade.symbol)}</td><td class="${trade.direction==="LONG"?"positive":"negative"}">${trade.direction}</td><td>${fmt(trade.entry_price,2)}</td><td>${fmt(trade.exit_price??trade.current_price,2)}</td><td>${fmt(trade.stop_loss,2)}</td><td>${fmt(trade.take_profit,2)}</td><td class="${(trade.pnl??trade.unrealized_pnl??0)>=0?"positive":"negative"}">${fmt(trade.pnl??trade.unrealized_pnl)} USDT</td><td>${trade.status}</td><td>${esc(trade.exit_reason||"open")}</td></tr>`).join("")}</tbody></table>`:`<div class="empty">No paper trades yet.</div>`;
}

async function refresh(){
  try{
    const [stats,trades,health]=await Promise.all([api("/api/stats/pnl"),api("/api/paper-trades?limit=300"),api("/api/health")]);
    $("exchange-badge").textContent=health.exchange.toUpperCase();
    $("pnl-updated").textContent=new Date().toLocaleTimeString();
    renderSummary(stats);renderCurve(stats.curve);renderTrades(trades);
  }catch(error){$("pnl-updated").textContent=error.message;}
}
refresh();
setInterval(refresh,8000);
