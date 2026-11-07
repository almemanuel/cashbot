# 🤖 CashBot — Multi-Agent Crypto Trading & Portfolio Engine

Sistema autônomo de **Giro Rápido no Mercado Spot (Modo Perda Zero)** com comitê de Inteligência Artificial (**Groq + Google Gemini**), operando sob **custo zero perpétuo** de infraestrutura (**GitHub Actions + Neon PostgreSQL + Render Free Tier**) e interface **PWA Mobile-First** protegida por senha.

---

## ⚙️ Como o CashBot Funciona (Motor Day Trade Quantitativo 15m)

### 1. Ciclo de 15 em 15 Minutos com Comitê de IA Sempre Ativo (`*/15 * * * *`)
O robô roda automaticamente na nuvem via **GitHub Actions** a cada **15 minutos** ([`.github/workflows/trading_engine.yml`](.github/workflows/trading_engine.yml)):
* **Etapa 1 — Comitê de IA (Groq + Gemini) em Todo Ciclo:** A cada 15 minutos, o robô analisa a *Watchlist Dinâmica* (e todas as moedas que estiverem abertas na carteira) usando **velas intradiárias de 15 minutos (`15m`)**, gravando as deliberações no **Neon PostgreSQL** e atualizando o horário de **Última análise** no topo do painel.
* **Etapa 2 — Realização Rápida de Lucro & Rotação Tática:**
  * **Alvo Curto de Day Trade (`+0.8%` a `+2.2%`):** Se o preço atingir o *Take Profit* curto, realiza o lucro na hora.
  * **Realização Tática no Lucro (`>= +0.35%`):** Se uma posição aberta já estiver no positivo (`>= +0.35%`) e passar de **45 minutos** aberta (ou a IA detectar enfraquecimento com nota `< 58` ou `RSI > 68`), o robô **embolsa esse lucro imediatamente** e libera a vaga para girar em uma moeda mais explosiva.
* **Etapa 3 — Modo Perda Zero Absoluto (`Hold Spot`):** Se o preço oscilar abaixo da entrada, o robô **jamais vende no prejuízo** — ele segura o ativo no Spot até voltar ao campo positivo.

---

### 2. Indicadores Institucionais de Day Trade (Timeframe 15m)
Para cada moeda, o motor calcula 250 velas de **15 minutos** e entrega ao Comitê de IA:
1. **Agente Técnico (`engine/agents/technical.py` — Peso 60%):**
   * **VWAP Intradiário (24h):** Preço Médio Ponderado por Volume usado por institucionais.
   * **Bandas de Bollinger (20, 2):** Identifica recuos na banda inferior (compra descontada) e evita compras esticadas na banda superior.
   * **Volume Spike Ratio & Momentum 1h:** Detecta entrada de fluxo comprador (*Smart Money*) acima da média.
   * **EMAs (20, 50, 200), RSI 14 e ATR 14 no gráfico de 15m.**
2. **Agente de Sentimento (`engine/agents/sentiment.py` — Peso 40%):**
   * Faz *prefetch* em lote (sem gargalo N+1) do índice **Fear & Greed** e das manchetes reais via **CryptoCompare News API** + fallback **Google News RSS**.
3. **Diversificação Ágil (`engine/agents/risk.py`):**
   * Moedas com **Nota Final $\ge$ 63/100** e **sem Veto** são aprovadas.
   * O capital livre é dividido proporcionalmente às notas em **até 4 posições simultâneas**, acelerando o giro intradiário.

---

### 3. Modo "Perda Zero" no Spot (`Hold 0% Perda`)
* Como o robô opera exclusivamente no **Mercado Spot (sem alavancagem)**, a carteira detém o ativo real e **não sofre liquidação**.
* **Sem Venda em Pânico na Queda:** Se o preço recuar após a compra, o robô **não se assusta nem realiza prejuízo no fundo** — ele mantém a posição em *Hold* aguardando a retomada do preço até atingir o **Take Profit** (`+2.0%` a `+5.5%`).

---

### 4. Gestão Inteligente de Lucros (Bola de Neve + Saque Pix)
Toda vez que uma posição fecha no lucro (`CLOSED_TP`), o `RiskAgent` aplica:
1. **Proteção do Piso da Banca:** Se o capital de giro estiver abaixo do piso configurado, 100% do lucro recompõe o caixa.
2. **Divisão 60% Giro / 40% Saque com Trava Mínima de US$ 10:**
   * **60%** do lucro vai direto para o **Capital de Giro** (efeito bola de neve).
   * **40%** vai para o **Pool de Saque (Pix)**, desde que o acumulado atinja pelo menos **US$ 10.00** (mínimo da Binance). Enquanto for menor que US$ 10, 100% é reinvestido automaticamente no giro.
3. **Sincronização Automática de Saldo Antes das Ordens (`_sync_free_balance_before_orders`):**
   * Antes de abrir qualquer nova posição, o robô consulta o **saldo livre real de USDT na Binance** (`fetch_free_usdt_balance`):
   * **Se você sacou na corretora (mesmo sem avisar no painel):** O robô detecta automaticamente o saldo real menor na Binance e dimensiona as compras apenas com o que de fato está na conta.
   * **Se você não sacou o valor sugerido:** O robô reincorpora automaticamente o saldo disponível ao Capital de Giro para maximizar os juros compostos (* o botão `"Já Saquei"` no painel serve apenas para quando você quiser simular uma retirada durante o Modo Simulação*).

---

## 📊 Painel Web PWA (`web_app.py` + `web/public/`)

* **Proteção por Senha (`HMAC-SHA256`):** Tela de bloqueio exigindo a senha configurada em `APP_PASSWORD` para acessar qualquer rota `/api/*`.
* **Cabeçalho em Tempo Real:** Exibe o banco ativo (`Binance Spot • Neon PostgreSQL`) e o horário exato da **Última análise** do comitê convertido para o fuso de Brasília.
* **Card Principal de Patrimônio:**
  * **Valor Sugerido para Saque (Pix)** em `US$` e `R$` + botão **"Já Saquei"**.
  * **3 Métricas na Base:** `Caixa Livre (Giro)`, `Valor Investido` (soma exata alocada nas posições abertas) e `Total do Portfólio`.
* **2 Gráficos Independentes (`Chart.js`):**
  1. **Valor Investido & Disponível p/ Saque (`$`)** ao longo do tempo.
  2. **Evolução do Lucro Realizado (`$`)** acumulado.

---

## ☁️ Como Rodar 100% Grátis na Nuvem

### 1. Banco de Dados Serverless (Neon PostgreSQL)
Crie um projeto gratuito em [neon.tech](https://neon.tech) e copie a `DATABASE_URL` (`postgresql://...`). As tabelas (`trades`, `consensus_logs`, `portfolio_ledger`) são criadas automaticamente na primeira execução.

### 2. Robô Automático 24/7 (GitHub Actions)
No repositório do GitHub, acesse **Settings → Secrets and variables → Actions → New repository secret** e cadastre:
* `DATABASE_URL`
* `GROQ_API_KEY`
* `GEMINI_API_KEY`
* `TELEGRAM_BOT_TOKEN`
* `TELEGRAM_CHAT_ID`
* `BINANCE_TESTNET_API_KEY`
* `BINANCE_TESTNET_SECRET_KEY`

### 3. Painel Web / PWA (Render Free Tier)
Conecte o repositório no [Render.com](https://render.com) como **Web Service** (plano **Free**), usando:
* **Build Command:** `pip install -r engine/requirements.txt`
* **Start Command:** `python web_app.py`
* Adicione as mesmas variáveis do `engine/.env` (incluindo `DATABASE_URL` e `APP_PASSWORD`).

---

## 💻 Execução Local

```bash
# Iniciar o servidor web + PWA na porta 8080
python web_app.py 8080

# Executar um ciclo manual do motor
python engine/main.py

# Testar alerta no Telegram
python engine/main.py --test-notify
```
