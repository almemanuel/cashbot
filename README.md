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

### 3. Proteção Anti-Ruído, Disjuntor de Catástrofe (`-7.5%`), Rotação Ativa de Capital e Modo Recuperação 100%
* **Imune a Ruído Curto (Sem Stop Curto):** Oscilações normais de mercado (`-1%` a `-7%`) não derrubam a posição; o robô aguarda a retomada sem realizar prejuízo bobo.
* **Disjuntor de Catástrofe (`-7.5%`):** Mantém uma trava de emergência para proteger a banca contra colapsos severos (evitando que uma moeda derreta `-40%` ou `-80%`).
* **Rotação Ativa de Capital (Custo de Oportunidade):** Mesmo com as 4 vagas cheias, o robô continua varrendo o mercado. Se encontrar uma oportunidade com nota altíssima ($\ge 72$) e houver uma moeda aberta estagnada há $>60$ min no zero-a-zero com nota fraca ($\le 55$), o robô encerra o ativo estagnado no empate e entra imediatamente na moeda mais explosiva!
* **Stop Temporal Inteligente (`48h`):** Se uma operação completar **48 horas** estagnada (andando de lado ou com recuo leve de até `-2.0%` e sem força compradora na IA), o robô encerra para destravar o capital.
* **Modo Recuperação 100% do Capital (*High-Water Mark*):** Se o Disjuntor ou Stop Temporal gerar qualquer perda, **100% dos próximos lucros** voltam direto para o **Capital de Giro** até recompor o capital original centavo por centavo.
* **Análise de Continuidade no Ponto de Venda (`_should_ride_strong_uptrend`):** Mesmo quando a moeda bate no ponto de venda, antes de encerrar a operação o robô verifica se a tendência de alta continua forte (`Score IA >= 68`, `Preço > EMA20 > EMA50`, acima da `VWAP` e `RSI < 68` sem exaustão). Se ainda houver força compradora, ele **segura a venda por mais rodadas** e sobe o alvo (`Take Profit`) em **`+0.8%`** para capturar toda a pernada de alta!

---

### 4. Gestão Diária de Lucros, Pausa de 1h e Relatórios no Telegram (`22h às 23h BRT`)
Toda vez que uma posição fecha no lucro (`CLOSED_TP`), o `RiskAgent` aplica:
1. **Distribuição Ao Longo do Dia (60% Giro / 40% Saque):**
   * **60%** do lucro é reinvestido imediatamente no **Capital de Giro** (bola de neve intradiária).
   * **40%** vai acumulando na caixinha **Guardado para Saque Hoje**, ficando protegido durante o dia.
2. **Mensagens Limpas e Completas no Telegram (Zero Dependência de Front-End):**
   * Em **toda compra ou venda**, a mensagem traz o **Patrimônio Anterior**, **Patrimônio Atual**, **Lucro da Rodada**, **Total Operando nas Moedas**, **Caixa Livre** e **Guardado p/ Saque**, além de explicar o motivo da decisão em linguagem simples e direta para leigos (sem siglas técnicas).
3. **Janela de Pausa e Fechamento Diário (`WITHDRAW_WINDOW_START_BRT=22` até `WITHDRAW_WINDOW_END_BRT=23` no `.env`):**
   * **Às 22h BRT (Início da Janela):** O robô **pausa todas as compras e vendas por 1 hora** para não bagunçar o saldo e envia no Telegram o **Fechamento Consolidado do Dia** (Patrimônio no Início do Dia, Patrimônio no Fim do Dia, Lucro Total Conquistado Hoje, resumo das operações e se o valor reservado atingiu o mínimo de **US$ 10,00** para saque na Binance).
   * **Às 23h BRT (Fim da Janela e Reinício):** Se você não sacar até as 23h, o robô **reincorpora automaticamente 100% desse lucro ao Capital de Giro**, sincroniza o saldo real da conta na Binance e envia uma mensagem avisando que está iniciando o novo ciclo diário considerando o capital total `X` disponível em conta!

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
