// CashBot Frontend Logic & PWA Controller

// Registra Service Worker se suportado pelo navegador
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js')
    .then(() => console.log('CashBot PWA Service Worker registrado com sucesso.'))
    .catch((err) => console.log('Falha ao registrar Service Worker:', err));
}

let activeTab = 'dashboard';
let overviewData = null;

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

// Atualização de dados da API
async function refreshData() {
  const icon = document.getElementById('refreshIcon');
  if (icon) icon.classList.add('fa-spin');

  try {
    const res = await fetch('/api/overview');
    if (!res.ok) throw new Error('Falha ao obter dados');
    const data = await res.json();
    overviewData = data;
    renderData(data);
  } catch (err) {
    console.error('Erro ao buscar dados:', err);
    showToast('Erro ao sincronizar dados com o bot.');
  } finally {
    if (icon) setTimeout(() => icon.classList.remove('fa-spin'), 600);
  }
}

function renderData(data) {
  const ledger = data.ledger || { trading_balance: 1000, withdrawable_pool: 0 };
  const openTrade = data.open_trade;
  const trades = data.recent_trades || [];
  const logs = data.recent_consensus || [];

  // 1. Ledger e Pool de Retirada
  const withdrawable = Number(ledger.withdrawable_pool || 0);
  const trading = Number(ledger.trading_balance || 0);
  const total = withdrawable + trading;
  const brlRate = 5.80; // Estimativa cambial para conveniência

  document.getElementById('withdrawableUsd').innerText = `$${withdrawable.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  document.getElementById('withdrawableBrl').innerText = `≈ R$ ${(withdrawable * brlRate).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  document.getElementById('tradingBalanceUsd').innerText = `$${trading.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  document.getElementById('totalPortfolioUsd').innerText = `$${total.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  // 2. Posição Aberta
  const openContent = document.getElementById('openTradeContent');
  const badgeStatus = document.getElementById('badgeTradeStatus');

  if (openTrade && openTrade.status === 'OPEN_OCO') {
    badgeStatus.className = 'text-[10px] font-bold px-2.5 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/30 animate-pulse';
    badgeStatus.innerText = 'OCO ATIVA NO LIVRO';

    const entry = Number(openTrade.entry_price);
    const sl = Number(openTrade.stop_loss);
    const tp = Number(openTrade.take_profit);
    const qty = Number(openTrade.quantity);

    openContent.innerHTML = `
      <div class="space-y-3">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="text-lg font-extrabold text-white">${openTrade.symbol}</span>
            <span class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-400 font-bold">LONG SPOT</span>
          </div>
          <span class="text-xs font-mono text-slate-300">Qtd: ${qty.toFixed(6)}</span>
        </div>

        <div class="grid grid-cols-3 gap-2 text-center text-xs py-2 bg-slate-950/60 rounded-xl border border-slate-800">
          <div>
            <span class="text-[10px] text-rose-400 font-semibold block uppercase">Stop Loss</span>
            <span class="font-bold text-rose-300">$${sl.toLocaleString()}</span>
          </div>
          <div>
            <span class="text-[10px] text-slate-400 font-semibold block uppercase">Entrada</span>
            <span class="font-bold text-white">$${entry.toLocaleString()}</span>
          </div>
          <div>
            <span class="text-[10px] text-emerald-400 font-semibold block uppercase">Take Profit</span>
            <span class="font-bold text-emerald-300">$${tp.toLocaleString()}</span>
          </div>
        </div>

        <div class="text-[11px] text-slate-400 flex items-center justify-between">
          <span>Risco Máx: -$${((entry - sl) * qty).toFixed(2)}</span>
          <span class="text-emerald-400 font-semibold">Alvo 2R: +$${((tp - entry) * qty).toFixed(2)}</span>
        </div>
      </div>
    `;
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
    lastSymbol.innerText = latest.symbol;
    const finalScore = Number(latest.final_score);
    const techScore = Number(latest.technical_score);
    const sentScore = Number(latest.sentiment_score);
    const veto = Boolean(latest.veto_applied);

    const scoreColor = finalScore >= 75 && !veto ? 'text-emerald-400' : (veto ? 'text-rose-400' : 'text-amber-400');

    lastConsensusContainer.innerHTML = `
      <div class="flex items-center justify-between">
        <span class="text-xs text-slate-300 font-semibold">Consenso Final Ponderado:</span>
        <span class="text-base font-extrabold ${scoreColor}">
          ${finalScore.toFixed(1)}/100 ${veto ? '(VETO)' : (finalScore >= 75 ? '🎯 COMPRA' : 'AGUARDAR')}
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
      const isApproved = Number(l.final_score) >= 75 && !l.veto_applied;
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
            <span class="text-[10px] text-slate-500 ml-auto">${(l.created_at || '').substring(0, 16)}</span>
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

// Disparo de Ações
async function triggerAction(endpoint, loadingText) {
  showToast(loadingText);
  try {
    const res = await fetch(endpoint, { method: 'POST' });
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
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ TELEGRAM_BOT_TOKEN: token, TELEGRAM_CHAT_ID: chatId })
    });
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

