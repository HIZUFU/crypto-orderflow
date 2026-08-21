const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#039;"}[c]));
const fmt = (value, digits = 4) => value == null ? "-" : Number(value).toFixed(digits);

let equityChart = null;
let currentFilter = "all";

async function get(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function renderStats(stats) {
  const winRate = (stats.win_rate * 100).toFixed(1);
  const profitFactor = stats.profit_factor.toFixed(2);
  const totalPnl = stats.total_pnl;
  const pnlClass = totalPnl >= 0 ? "positive" : "negative";
  
  $("stats-grid").innerHTML = [
    ["Total Trades", stats.total_trades],
    ["Win Rate", `${winRate}%`],
    ["Profit Factor", profitFactor],
    ["Total PnL", `<span class="${pnlClass}">${fmt(totalPnl, 2)} USDT</span>`],
    ["Avg Win", `<span class="positive">${fmt(stats.avg_win, 4)} USDT</span>`],
    ["Avg Loss", `<span class="negative">${fmt(stats.avg_loss, 4)} USDT</span>`],
    ["Largest Win", `<span class="positive">${fmt(stats.largest_win, 4)} USDT</span>`],
    ["Largest Loss", `<span class="negative">${fmt(stats.largest_loss, 4)} USDT</span>`],
  ].map(([label, value]) => 
    `<div class="stat"><div class="stat-label">${label}</div><div class="stat-value">${value}</div></div>`
  ).join("");
}

function initEquityChart(trades) {
  const ctx = $("equity-chart").getContext("2d");
  
  // Calculate cumulative PnL
  let cumulative = 0;
  const data = trades.map((trade, index) => {
    cumulative += trade.pnl || 0;
    return {
      x: new Date(trade.closed_at),
      y: cumulative,
    };
  });
  
  // Add starting point at 0
  if (data.length > 0) {
    data.unshift({
      x: new Date(trades[trades.length - 1].opened_at),
      y: 0,
    });
  }
  
  if (equityChart) {
    equityChart.destroy();
  }
  
  equityChart = new Chart(ctx, {
    type: "line",
    data: {
      datasets: [{
        label: "Cumulative PnL (USDT)",
        data: data,
        borderColor: "#64b5ff",
        backgroundColor: "rgba(100, 181, 255, 0.1)",
        borderWidth: 2,
        fill: true,
        tension: 0.1,
        pointRadius: 3,
        pointHoverRadius: 5,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          type: "time",
          time: {
            unit: "hour",
            displayFormats: {
              hour: "MMM d, HH:mm"
            }
          },
          grid: {
            color: "#293239",
          },
          ticks: {
            color: "#8c9aa5",
          }
        },
        y: {
          grid: {
            color: "#293239",
          },
          ticks: {
            color: "#8c9aa5",
            callback: function(value) {
              return value.toFixed(2) + " USDT";
            }
          }
        }
      },
      plugins: {
        legend: {
          display: false,
        },
        tooltip: {
          backgroundColor: "#171d21",
          titleColor: "#e8edf2",
          bodyColor: "#e8edf2",
          borderColor: "#293239",
          borderWidth: 1,
          callbacks: {
            label: function(context) {
              return "PnL: " + context.parsed.y.toFixed(4) + " USDT";
            }
          }
        }
      }
    }
  });
}

function renderClosedTrades(trades) {
  let filtered = trades;
  
  if (currentFilter === "wins") {
    filtered = trades.filter(t => t.pnl > 0);
  } else if (currentFilter === "losses") {
    filtered = trades.filter(t => t.pnl <= 0);
  }
  
  const container = $("closed-trades");
  
  if (filtered.length === 0) {
    container.innerHTML = '<div class="empty">No closed trades</div>';
    return;
  }
  
  container.innerHTML = `<table>
    <thead>
      <tr>
        <th>Opened</th>
        <th>Closed</th>
        <th>Symbol</th>
        <th>Direction</th>
        <th>Entry</th>
        <th>Exit</th>
        <th>PnL</th>
        <th>Reason</th>
      </tr>
    </thead>
    <tbody>${filtered.map(trade => {
      const pnlClass = trade.pnl >= 0 ? "positive" : "negative";
      return `<tr>
        <td>${new Date(trade.opened_at).toLocaleString()}</td>
        <td>${new Date(trade.closed_at).toLocaleString()}</td>
        <td>${esc(trade.symbol)}</td>
        <td class="${trade.direction === "LONG" ? "positive" : "negative"}">${trade.direction}</td>
        <td>${fmt(trade.entry_price, 2)}</td>
        <td>${fmt(trade.exit_price, 2)}</td>
        <td class="${pnlClass}">${fmt(trade.pnl, 4)} USDT</td>
        <td>${esc(trade.exit_reason)}</td>
      </tr>`;
    }).join("")}</tbody>
  </table>`;
}

async function refresh() {
  try {
    const [stats, trades] = await Promise.all([
      get("/api/stats/pnl"),
      get("/api/paper-trades?status=closed&limit=200")
    ]);
    
    renderStats(stats);
    
    if (trades.length > 0) {
      // Reverse to show oldest first for equity curve
      const sorted = [...trades].reverse();
      initEquityChart(sorted);
      renderClosedTrades(trades); // Show newest first in table
    } else {
      $("closed-trades").innerHTML = '<div class="empty">No closed trades yet</div>';
    }
  } catch (error) {
    console.error("Failed to load PnL data:", error);
  }
}

// Filter event listeners
document.querySelectorAll('input[name="filter"]').forEach(radio => {
  radio.addEventListener("change", (e) => {
    currentFilter = e.target.value;
    refresh();
  });
});

// Initialize
refresh();

// Auto-refresh every 10 seconds
setInterval(refresh, 10000);
