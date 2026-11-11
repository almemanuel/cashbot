// CashBot Frontend Logic & PWA Controller

// Registra Service Worker se suportado pelo navegador
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js')
    .then(() => console.log('CashBot PWA Service Worker registrado com sucesso.'))
    .catch((err) => console.log('Falha ao registrar Service Worker:', err));
}

let activeTab = 'dashboard';
let overviewData = null;
let portfolioChartInstance = null;
let profitChartInstance = null;
const AUTH_STORAGE_KEY = 'cashbot_auth_token';

function getAuthToken() {
  return localStorage.getItem(AUTH_STORAGE_KEY) || '';
}

function authHeaders(extra = {}) {
  return Object.assign({ 'Authorization': `Bearer ${getAuthToken()}` }, extra);
}

function showLoginModal() {
  const modal = document.getElementById('loginOverlay');
  if (modal) modal.classList.remove('hidden');
}

function hideLoginModal() {
  const modal = document.getElementById('loginOverlay');
  if (modal) modal.classList.add('hidden');
}

async function submitLogin(event) {
  event.preventDefault();
  const input = document.getElementById('loginPasswordInput');
  const errEl = document.getElementById('loginErrorMsg');
  const password = input ? input.value : '';

  try {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password })
    });
    const data = await res.json();
    if (res.ok && data.token) {
      localStorage.setItem(AUTH_STORAGE_KEY, data.token);
      if (errEl) errEl.classList.add('hidden');
      if (input) input.value = '';
      hideLoginModal();
      showToast('Painel desbloqueado!');
      await refreshData();
      return;
    }
    if (errEl) errEl.classList.remove('hidden');
  } catch (e) {
    showToast('Erro de conexão ao validar senha.');
  }
}

function logoutApp() {
  localStorage.removeItem(AUTH_STORAGE_KEY);
  showLoginModal();
  showToast('Painel bloqueado.');
}

// Alterna abas
function switchTab(tabId) {
  activeTab = tabId;
  const tabs = ['dashboard', 'committee', 'trades', 'sim'];
  
  tabs.forEach(t => {
    const el = document.getElementById(`tab-${t}`);
    const topBtn = document.getElementById(`tabBtn-${t}`);
    const navBtn = document.getElementById(`navBtn-${t}`);

    if (t === tabId) {
      if (el) el.classList.remove('hidden');
      if (topBtn) {
        topBtn.className = 'flex-1 py-2 rounded-lg bg-emerald-500 text-slate-950 font-bold transition';
      }
      if (navBtn) {
        navBtn.className = 'flex-col items-center gap-1 text-emerald-400 transition flex';
      }
    } else {
      if (el) el.classList.add('hidden');
      if (topBtn) {
        topBtn.className = 'flex-1 py-2 rounded-lg text-slate-400 hover:text-white transition';
      }
      if (navBtn) {
        navBtn.className = 'flex-col items-center gap-1 text-slate-400 hover:text-white transition flex';
      }
    }
  });
}

// Notificações nativas do navegador
function requestNotificationPermission() {
  if (!('Notification' in window)) {
    showToast('Este navegador não suporta notificações de sistema.');
    return;
  }
  Notification.requestPermission().then(permission => {
    if (permission === 'granted') {
      showToast('Notificações ativadas no seu celular!');
      new Notification('CashBot Conectado', {
        body: 'Você receberá alertas sempre que uma ordem for executada ou fechada.',
        icon: '/manifest.json'
      });
    } else {
      showToast('Permissão de notificação negada.');
    }
  });
}

function sendLocalNotification(title, body) {
  if ('Notification' in window && Notification.permission === 'granted') {
    new Notification(title, { body, icon: '/manifest.json' });
  }
}

// Exibe Toast na tela
function showToast(message) {
  const toast = document.getElementById('toast');
  const msgEl = document.getElementById('toastMsg');
  if (!toast || !msgEl) return;
  msgEl.innerText = message;
  toast.classList.remove('opacity-0', 'pointer-events-none');
  setTimeout(() => {
    toast.classList.add('opacity-0', 'pointer-events-none');
  }, 3500);
}

// Atualização de dados da API (com retry automático caso o Render esteja reiniciando um deploy)
async function refreshData(retryCount = 0) {
  const icon = document.getElementById('refreshIcon');
  if (icon) icon.classList.add('fa-spin');

  try {
    const res = await fetch('/api/overview', { headers: authHeaders() });
    if (res.status === 401) {
      showLoginModal();
      return;
    }
    if ((res.status === 502 || res.status === 503 || res.status === 504) && retryCount < 2) {
      setTimeout(() => refreshData(retryCount + 1), 2500);
      return;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    hideLoginModal();
    const data = await res.json();
    overviewData = data;
    renderData(data);
  } catch (err) {
    if (retryCount < 1) {
      setTimeout(() => refreshData(retryCount + 1), 2500);
      return;
    }
    console.error('Erro ao buscar dados:', err);
    showToast('Sincronizando com o servidor... tente novamente em instantes.');
  } finally {
    if (icon) setTimeout(() => icon.classList.remove('fa-spin'), 600);
  }
}

function formatTimestampBr(rawDateStr) {
  if (!rawDateStr) return '';
  const normalized = String(rawDateStr).trim().replace(' ', 'T');
  const iso = /[Z+\-]\d{0,2}:?\d{0,2}$/.test(normalized) ? normalized : `${normalized}Z`;
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return String(rawDateStr).substring(0, 16);
  const datePart = dt.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  const timePart = dt.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  return `${datePart} às ${timePart}`;
}

function renderData(data) {
  const ledger = data.ledger || { trading_balance: 1000, withdrawable_pool: 0 };
  const ledgerHistory = data.ledger_history || [];
  const openTrade = data.open_trade;
  const trades = data.recent_trades || [];
  const logs = data.recent_consensus || [];

  const headerStatus = document.getElementById('headerStatus');
  if (headerStatus && data.db_mode) {
    headerStatus.innerText = `Binance Spot • ${data.db_mode}`;
  }

  const headerLastAnalysis = document.getElementById('headerLastAnalysis');
  if (headerLastAnalysis) {
    const latestTimestamp = logs.length > 0 ? formatTimestampBr(logs[0].created_at) : '';
    headerLastAnalysis.innerHTML = latestTimestamp
      ? `<i class="fa-regular fa-clock text-[9px]"></i> Última análise: <b>${latestTimestamp}</b>`
      : `<i class="fa-regular fa-clock text-[9px]"></i> Última análise: Aguardando 1º ciclo`;
  }

  // 1. Ledger, Valor Investido e Pool de Retirada
  const openTrades = (data.open_trades && data.open_trades.length > 0)
    ? data.open_trades
    : (openTrade && openTrade.status === 'OPEN_OCO' ? [openTrade] : []);

  const investedUsd = openTrades.reduce(
    (acc, t) => acc + (Number(t.entry_price || 0) * Number(t.quantity || 0)),
    0
  );
  const withdrawable = Number(ledger.withdrawable_pool || 0);
  const trading = Number(ledger.trading_balance || 0);
  const freeTrading = Math.max(0, trading - investedUsd);
  const total = withdrawable + trading;
  const brlRate = 5.80;

  document.getElementById('withdrawableUsd').innerText = `$${withdrawable.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  document.getElementById('withdrawableBrl').innerText = `≈ R$ ${(withdrawable * brlRate).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  document.getElementById('tradingBalanceUsd').innerText = `$${freeTrading.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const investedEl = document.getElementById('investedBalanceUsd');
  if (investedEl) {
    investedEl.innerText = `$${investedUsd.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  document.getElementById('totalPortfolioUsd').innerText = `$${total.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  renderPortfolioChart(ledgerHistory, trades, openTrades, trading, withdrawable, investedUsd);

  // 2. Posições Abertas (Multi-Posição / Diversificação)
  const openContent = document.getElementById('openTradeContent');
  const badgeStatus = document.getElementById('badgeTradeStatus');

  if (openTrades.length > 0) {
    badgeStatus.className = 'text-[10px] font-bold px-2.5 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 animate-pulse';
    badgeStatus.innerText = `${openTrades.length} POSIÇÃO(ÕES) ATIVA(S)`;

    openContent.innerHTML = `<div class="space-y-3">` + openTrades.map(ot => {
      const entry = Number(ot.entry_price);
      const sl = Number(ot.stop_loss);
      const tp = Number(ot.take_profit);
      const qty = Number(ot.quantity);
      const slPct = entry > 0 ? (((entry - sl) / entry) * 100).toFixed(1) : '0.0';
      const tpPct = entry > 0 ? (((tp - entry) / entry) * 100).toFixed(1) : '0.0';

      return `
        <div class="space-y-2.5 p-3 rounded-xl bg-slate-900/50 border border-slate-800/90">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="text-base font-extrabold text-white">${ot.symbol}</span>
              <span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400 font-bold">GIRO RÁPIDO</span>
            </div>
            <span class="text-xs font-mono text-slate-300">Alocado: $${(entry * qty).toFixed(2)}</span>
          </div>

          <div class="grid grid-cols-3 gap-2 text-center text-xs py-2 bg-slate-950/60 rounded-xl border border-slate-800">
            <div>
              <span class="text-[10px] text-cyan-400 font-semibold block uppercase">Proteção Spot</span>
              <span class="font-bold text-cyan-300">Hold 0% Perda</span>
            </div>
            <div>
              <span class="text-[10px] text-slate-400 font-semibold block uppercase">Entrada</span>
              <span class="font-bold text-white">$${entry.toLocaleString()}</span>
            </div>
            <div>
              <span class="text-[10px] text-emerald-400 font-semibold block uppercase">Alvo (+${tpPct}%)</span>
              <span class="font-bold text-emerald-300">$${tp.toLocaleString()}</span>
            </div>
          </div>

          <div class="text-[11px] text-slate-400 flex items-center justify-between">
            <span>Risco Controlado: -$${((entry - sl) * qty).toFixed(2)}</span>
            <span class="text-emerald-400 font-semibold">Lucro Esperado: +$${((tp - entry) * qty).toFixed(2)}</span>
          </div>
        </div>
      `;
    }).join('') + `</div>`;
  } else {
    badgeStatus.className = 'text-[10px] font-bold px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-slate-700';
    badgeStatus.innerText = 'IDLE (AGUARDANDO OPORTUNIDADE)';
    openContent.innerHTML = `
      <div class="text-center py-6 text-slate-400 space-y-2">
        <i class="fa-solid fa-satellite-dish text-2xl text-slate-600"></i>
        <p class="text-xs">Nenhum trade aberto no momento. O bot analisa os pares diariamente às 21:05 BRT.</p>
      </div>
    `;
  }

  // 3. Último Consenso
  const lastConsensusContainer = document.getElementById('lastConsensusCard');
  const lastSymbol = document.getElementById('lastConsensusSymbol');
  if (logs.length > 0) {
    const latest = logs[0];
    lastSymbol.innerText = `${latest.symbol} • ${formatTimestampBr(latest.created_at)}`;
    const finalScore = Number(latest.final_score);
    const techScore = Number(latest.technical_score);
    const sentScore = Number(latest.sentiment_score);
    const veto = Boolean(latest.veto_applied);

    const scoreColor = finalScore >= 65 && !veto ? 'text-emerald-400' : (veto ? 'text-rose-400' : 'text-amber-400');

    lastConsensusContainer.innerHTML = `
      <div class="flex items-center justify-between">
        <span class="text-xs text-slate-300 font-semibold">Consenso Final Ponderado:</span>
        <span class="text-base font-extrabold ${scoreColor}">
          ${finalScore.toFixed(1)}/100 ${veto ? '(VETO)' : (finalScore >= 65 ? '🎯 COMPRA' : 'AGUARDAR')}
        </span>
      </div>
      <div class="grid grid-cols-2 gap-2 text-xs pt-1">
        <div class="p-2 rounded-lg bg-slate-950/50 border border-slate-800/80">
          <span class="text-[10px] text-slate-400 block font-semibold">Groq (Técnico 60%)</span>
          <span class="font-bold text-white">${techScore.toFixed(1)}/100</span>
        </div>
        <div class="p-2 rounded-lg bg-slate-950/50 border border-slate-800/80">
          <span class="text-[10px] text-slate-400 block font-semibold">Gemini (Sentimento 40%)</span>
          <span class="font-bold text-white">${sentScore.toFixed(1)}/100</span>
        </div>
      </div>
      <p class="text-[11px] text-slate-400 italic pt-1">${latest.reasoning_summary || ''}</p>
    `;
  } else {
    lastConsensusContainer.innerHTML = `<p class="text-xs text-slate-400">Nenhuma deliberação registrada ainda. Execute a primeira varredura na aba Simulação.</p>`;
  }

  // 4. Logs do Comitê de IA
  const commContainer = document.getElementById('committeeLogsContainer');
  if (logs.length === 0) {
    commContainer.innerHTML = `<p class="text-xs text-slate-400 text-center py-4">Nenhum log encontrado.</p>`;
  } else {
    commContainer.innerHTML = logs.map(l => {
      const isApproved = Number(l.final_score) >= 65 && !l.veto_applied;
      const badge = isApproved 
        ? `<span class="px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 font-bold text-[10px]">APROVADO</span>`
        : (l.veto_applied 
            ? `<span class="px-2 py-0.5 rounded bg-rose-500/20 text-rose-400 font-bold text-[10px]">VETO</span>`
            : `<span class="px-2 py-0.5 rounded bg-slate-800 text-slate-400 font-bold text-[10px]">REPROVADO</span>`);

      return `
        <div class="p-3 rounded-xl bg-slate-950/60 border border-slate-800 space-y-1.5">
          <div class="flex items-center justify-between">
            <span class="text-xs font-bold text-white">${l.symbol}</span>
            <div class="flex items-center gap-2">
              <span class="text-xs font-mono font-bold text-slate-200">${Number(l.final_score).toFixed(1)} pts</span>
              ${badge}
            </div>
          </div>
          <div class="flex items-center gap-4 text-[11px] text-slate-400">
            <span>Groq: <b>${Number(l.technical_score).toFixed(1)}</b></span>
            <span>Gemini: <b>${Number(l.sentiment_score).toFixed(1)}</b></span>
            <span class="text-[10px] text-slate-500 ml-auto">${formatTimestampBr(l.created_at)}</span>
          </div>
          <p class="text-[11px] text-slate-300 leading-snug">${l.reasoning_summary || ''}</p>
        </div>
      `;
    }).join('');
  }

  // 5. Histórico de Trades
  const tradesContainer = document.getElementById('tradesHistoryContainer');
  if (trades.length === 0) {
    tradesContainer.innerHTML = `<p class="text-xs text-slate-400 text-center py-4">Nenhum trade encerrado ainda.</p>`;
  } else {
    tradesContainer.innerHTML = trades.map(t => {
      const isTP = t.status === 'CLOSED_TP';
      const pnl = Number(t.pnl_usd || 0);
      const color = isTP ? 'text-emerald-400' : 'text-rose-400';
      const badge = isTP 
        ? `<span class="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-bold text-[10px]">TAKE PROFIT</span>`
        : (t.status === 'OPEN_OCO'
            ? `<span class="px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-bold text-[10px]">ABERTO</span>`
            : `<span class="px-2 py-0.5 rounded bg-rose-500/10 text-rose-400 border border-rose-500/20 font-bold text-[10px]">STOP LOSS</span>`);

      return `
        <div class="p-3 rounded-xl bg-slate-950/60 border border-slate-800 flex items-center justify-between">
          <div>
            <div class="flex items-center gap-2">
              <span class="text-xs font-bold text-white">${t.symbol}</span>
              ${badge}
            </div>
            <div class="text-[10px] text-slate-400 mt-0.5">
              Entrada: $${Number(t.entry_price).toLocaleString()} • Saída: $${Number(t.exit_price || t.entry_price).toLocaleString()}
            </div>
          </div>
          <div class="text-right">
            <span class="text-sm font-extrabold ${color}">
              ${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}
            </span>
            <span class="block text-[10px] text-slate-500">${(t.closed_at || t.created_at || '').substring(0, 10)}</span>
          </div>
        </div>
      `;
    }).join('');
  }
}

// Converte string de data do banco em timestamp numérico (ms)
function parseDbTimeMs(rawDateStr) {
  if (!rawDateStr) return 0;
  const normalized = String(rawDateStr).trim().replace(' ', 'T');
  const iso = /[Z+\-]\d{0,2}:?\d{0,2}$/.test(normalized) ? normalized : `${normalized}Z`;
  const ms = new Date(iso).getTime();
  return Number.isNaN(ms) ? 0 : ms;
}

// Calcula quanto estava investido em posições abertas em um determinado instante (ms)
function computeInvestedAtTime(timeMs, allTrades) {
  if (!timeMs) return 0;
  return allTrades.reduce((acc, t) => {
    const startMs = parseDbTimeMs(t.created_at);
    const endMs = t.closed_at ? parseDbTimeMs(t.closed_at) : Infinity;
    if (startMs > 0 && startMs <= timeMs + 1000 && timeMs < endMs) {
      return acc + (Number(t.entry_price || 0) * Number(t.quantity || 0));
    }
    return acc;
  }, 0);
}

// Calcula lucro realizado acumulado até um determinado instante (ms)
function computeProfitAtTime(timeMs, allTrades) {
  if (!timeMs) return 0;
  return allTrades
    .filter(t => t.status === 'CLOSED_TP' || t.status === 'CLOSED_SL')
    .reduce((acc, t) => {
      const closeMs = parseDbTimeMs(t.closed_at || t.created_at);
      if (closeMs > 0 && closeMs <= timeMs + 1000) {
        return acc + Number(t.pnl_usd || 0);
      }
      return acc;
    }, 0);
}

// Renderiza os 2 Gráficos: (1) Capital Total ao Longo do Tempo e (2) Resultado dos Trades (Lucros & Prejuízos)
function renderPortfolioChart(history, trades, openTrades, currentTrading, currentWithdraw, currentInvested) {
  if (typeof Chart === 'undefined') return;

  const commonScales = {
    x: {
      ticks: { color: '#64748b', font: { size: 9 }, maxRotation: 45 },
      grid: { color: 'rgba(255,255,255,0.04)' }
    },
    y: {
      ticks: { color: '#94a3b8', font: { size: 10 }, callback: v => `$${v}` },
      grid: { color: 'rgba(255,255,255,0.06)' }
    }
  };

  // 1. Gráfico de Patrimônio Total & Flutuação da Banca
  const baseCapital = 1000.0;
  const ledgerPoints = (history && history.length > 0)
    ? history
    : [{ trading_balance: currentTrading, withdrawable_pool: currentWithdraw, updated_at: new Date().toISOString() }];

  const capitalLabels = ledgerPoints.map((p, idx) => {
    const formatted = formatTimestampBr(p.updated_at);
    return formatted ? formatted.replace(/\/\d{4} às /, ' ') : `Pt ${idx + 1}`;
  });

  const totalCapitalSeries = ledgerPoints.map(p => {
    return Number(p.trading_balance || 0) + Number(p.withdrawable_pool || 0);
  });
  const baseCapitalSeries = ledgerPoints.map(() => baseCapital);

  const currentCapital = totalCapitalSeries[totalCapitalSeries.length - 1] || baseCapital;
  const capitalDiff = Math.round((currentCapital - baseCapital) * 100) / 100;
  const capitalBadge = document.getElementById('capitalSummaryBadge');
  if (capitalBadge) {
    const sign = capitalDiff >= 0 ? '+' : '';
    capitalBadge.innerText = `Patrimônio: $${currentCapital.toFixed(2)} (${sign}$${capitalDiff.toFixed(2)})`;
    capitalBadge.className = capitalDiff >= 0
      ? 'text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
      : 'text-[10px] font-bold px-2 py-0.5 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/20';
  }

  const canvas1 = document.getElementById('portfolioChart');
  if (canvas1) {
    if (portfolioChartInstance) portfolioChartInstance.destroy();
    portfolioChartInstance = new Chart(canvas1, {
      type: 'line',
      data: {
        labels: capitalLabels,
        datasets: [
          {
            label: 'Patrimônio Total ($)',
            data: totalCapitalSeries,
            borderColor: capitalDiff >= 0 ? '#10b981' : '#06b6d4',
            backgroundColor: capitalDiff >= 0 ? 'rgba(16, 185, 129, 0.12)' : 'rgba(6, 182, 212, 0.12)',
            borderWidth: 2.5,
            tension: 0.35,
            fill: true,
            pointRadius: 3,
            pointHoverRadius: 5,
          },
          {
            label: 'Capital Base ($1,000)',
            data: baseCapitalSeries,
            borderColor: '#94a3b8',
            borderDash: [5, 5],
            borderWidth: 1.5,
            pointRadius: 0,
            fill: false,
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: '#94a3b8', font: { size: 10 }, boxWidth: 12 } },
          tooltip: {
            callbacks: {
              afterLabel: function(context) {
                if (context.datasetIndex === 0) {
                  const val = Number(context.raw);
                  const diff = val - baseCapital;
                  const sign = diff >= 0 ? '+' : '';
                  return `Flutuação por Trades: ${sign}$${diff.toFixed(2)} (${(diff / baseCapital * 100).toFixed(2)}%)`;
                }
                return '';
              }
            }
          }
        },
        scales: commonScales
      }
    });
  }

  // 2. Gráfico de Resultado dos Trades (Lucros & Prejuízos)
  const closedTrades = (trades || [])
    .filter(t => t.status === 'CLOSED_TP' || t.status === 'CLOSED_SL')
    .sort((a, b) => parseDbTimeMs(a.closed_at || a.created_at) - parseDbTimeMs(b.closed_at || b.created_at));

  let cumPnl = 0;
  const tradeLabels = [];
  const cumPnlSeries = [];
  const singlePnlSeries = [];
  const barColors = [];

  closedTrades.forEach(t => {
    const pnl = Number(t.pnl_usd || 0);
    cumPnl = Math.round((cumPnl + pnl) * 100) / 100;
    const coin = (t.symbol || '').split('/')[0];
    const timeStr = formatTimestampBr(t.closed_at || t.created_at).replace(/\/\d{4} às /, ' ');
    tradeLabels.push(`#${t.id} ${coin} (${timeStr})`);
    cumPnlSeries.push(cumPnl);
    singlePnlSeries.push(pnl);
    barColors.push(pnl >= 0 ? 'rgba(16, 185, 129, 0.75)' : 'rgba(244, 63, 94, 0.75)');
  });

  const totalRealized = closedTrades.length > 0 ? cumPnl : (overviewData?.total_realized_pnl ?? 0);
  const isPositivePnl = totalRealized >= 0;
  const pnlBadge = document.getElementById('pnlSummaryBadge');
  if (pnlBadge) {
    const sign = totalRealized >= 0 ? '+' : '';
    pnlBadge.innerText = `Resultado Total: ${sign}$${Number(totalRealized).toFixed(2)}`;
    pnlBadge.className = isPositivePnl
      ? 'text-[10px] font-bold px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
      : 'text-[10px] font-bold px-2 py-0.5 rounded-full bg-rose-500/10 text-rose-400 border border-rose-500/20';
  }

  const canvas2 = document.getElementById('profitChart');
  if (canvas2) {
    if (profitChartInstance) profitChartInstance.destroy();
    profitChartInstance = new Chart(canvas2, {
      data: {
        labels: tradeLabels.length > 0 ? tradeLabels : ['Sem trades'],
        datasets: [
          {
            type: 'line',
            label: 'Resultado Acumulado ($)',
            data: cumPnlSeries.length > 0 ? cumPnlSeries : [0],
            borderColor: isPositivePnl ? '#10b981' : '#f43f5e',
            backgroundColor: isPositivePnl ? 'rgba(16, 185, 129, 0.10)' : 'rgba(244, 63, 94, 0.10)',
            borderWidth: 2.5,
            tension: 0.3,
            fill: true,
            pointRadius: 3.5,
            pointHoverRadius: 6,
            yAxisID: 'y',
          },
          {
            type: 'bar',
            label: 'PnL do Trade ($)',
            data: singlePnlSeries.length > 0 ? singlePnlSeries : [0],
            backgroundColor: barColors.length > 0 ? barColors : ['rgba(16, 185, 129, 0.5)'],
            borderRadius: 4,
            barThickness: 8,
            yAxisID: 'y',
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: '#94a3b8', font: { size: 10 }, boxWidth: 12 } },
          tooltip: {
            callbacks: {
              label: function(context) {
                const val = Number(context.raw);
                const sign = val >= 0 ? '+' : '';
                return `${context.dataset.label}: ${sign}$${val.toFixed(2)}`;
              }
            }
          }
        },
        scales: commonScales
      }
    });
  }
}

// Disparo de Ações
async function triggerAction(endpoint, loadingText) {
  showToast(loadingText);
  try {
    const res = await fetch(endpoint, { method: 'POST', headers: authHeaders() });
    if (res.status === 401) {
      showLoginModal();
      return;
    }
    const data = await res.json();
    if (data.success) {
      showToast(data.message || 'Ação concluída com sucesso!');
      sendLocalNotification('CashBot Atualizado', data.message || 'Ação concluída');
      await refreshData();
    } else {
      showToast(data.error || 'Erro ao executar ação');
    }
  } catch (err) {
    showToast('Falha na comunicação com o servidor.');
  }
}

// Salva Configuração do Telegram
async function saveTelegramConfig() {
  const token = document.getElementById('cfgTelegramToken').value.trim();
  const chatId = document.getElementById('cfgTelegramChatId').value.trim();

  if (!token || !chatId) {
    showToast('Preencha o Token e o Chat ID.');
    return;
  }

  showToast('Salvando credenciais...');
  try {
    const res = await fetch('/api/save-config', {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ TELEGRAM_BOT_TOKEN: token, TELEGRAM_CHAT_ID: chatId })
    });
    if (res.status === 401) {
      showLoginModal();
      return;
    }
    const data = await res.json();
    if (data.success) {
      showToast('Configuração salva com sucesso!');
    } else {
      showToast('Erro ao salvar configuração.');
    }
  } catch (e) {
    showToast('Falha na conexão.');
  }
}

// Inicialização
document.addEventListener('DOMContentLoaded', () => {
  refreshData();
  // Atualiza automaticamente a cada 15 segundos
  setInterval(refreshData, 15000);
});

