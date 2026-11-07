# 🤖 CashBot — Multi-Agent Crypto Trading & Portfolio Engine

Sistema autônomo de **Giro Rápido no Mercado Spot (Modo Perda Zero)** com comitê de Inteligência Artificial (**Groq + Google Gemini**), operando sob **custo zero perpétuo** de infraestrutura (**GitHub Actions + Neon PostgreSQL + Render Free Tier**) e interface **PWA Mobile-First** protegida por senha.

---

## ⚙️ Como o CashBot Funciona (Fluxo Operacional)

### 1. Monitoramento a Cada 15 Minutos (`*/15 * * * *`) — Custo Zero
O robô roda automaticamente na nuvem via **GitHub Actions** a cada **15 minutos** ([`.github/workflows/trading_engine.yml`](.github/workflows/trading_engine.yml)):
* **Etapa 1 — Checagem de Lucro (A cada 15 min, 0 tokens de IA):** Consulta a cotação Spot ao vivo de todas as posições abertas através do espelho global da Binance (`https://data-api.binance.vision/api/v3`, imune a bloqueios regionais de IP nos EUA). Se alguma moeda bateu ou superou a meta de lucro (**Take Profit**), o robô realiza o lucro imediatamente, atualiza o banco e avisa no Telegram.
* **Etapa 2 — Proteção Inteligente de Cota de IA:** Se todas as **3 vagas da carteira** já estiverem preenchidas (ou se o Comitê de IA já tiver deliberado nos últimos **45 minutos**), o ciclo encerra sem gastar chamadas gratuitas da Groq/Gemini e sem enviar mensagens repetidas no Telegram.
* **Etapa 3 — Scanner Dinâmico da Binance:** Quando há capital e vaga livre na carteira, o robô faz 1 requisição global ao livro de 24h da Binance (`/ticker/24hr`) e seleciona até **6 ativos** combinando a *Core Watchlist* (`BTC/USDT`, `ETH/USDT`, `SOL/USDT`) com as moedas de maior liquidez (`> US$ 35M/24h`) e melhor impulso comprador do dia.

---

### 2. Comitê Multi-Agente de IA (Descoberta Dinâmica de Modelos + Fallback)
Para cada moeda da Watchlist Dinâmica, o motor executa:
1. **Agente Técnico (`engine/agents/technical.py` — Peso 60%):**
   * Calcula indicadores reais com 250 candles diários: `EMA 20`, `EMA 50`, `EMA 200`, `RSI 14`, `ATR 14` e Suporte/Resistência de 7 dias.
   * Consulta a API da **Groq** descobrindo dinamicamente os modelos ativos (ex: `openai/gpt-oss-120b`, `qwen/qwen3.8-27b`) com fila de fallback automático.
   * Define a nota técnica (`0–100`) e sugere o alvo curto de **Take Profit** (`+2.0%` a `+5.5%`) para giro rápido.
2. **Agente de Sentimento (`engine/agents/sentiment.py` — Peso 40%):**
   * Faz *prefetch* em lote (sem gargalo N+1) do índice **Fear & Greed** e das manchetes reais de cada moeda via **CryptoCompare News API** + fallback **Google News RSS**.
   * Consulta o **Google Gemini Flash** com descoberta automática dos modelos mais recentes e fallback em cascata.
3. **Regra de Aprovação e Diversificação (`engine/agents/risk.py`):**
   * Moedas com **Nota Final $\ge$ 65/100** e **sem Veto** são aprovadas.
   * O capital livre é dividido proporcionalmente às notas em **até 3 posições simultâneas** (respeitando o lote mínimo seguro de `US$ 12.00` por posição).

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
3. **Reinvestimento Automático de Saque Não Utilizado:** Se o usuário não clicar em **"Já Saquei"** até a abertura de uma nova compra, o saldo parado no Pool de Saque é reincorporado ao Capital de Giro para maximizar os juros compostos.

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
