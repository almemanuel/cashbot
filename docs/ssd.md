# System Design Document (SDD)

## Multi-Agent Crypto Trading & Portfolio Monitoring System (Serverless & Zero-Cost Architecture)

## 1. Visão Geral e Princípios Arquiteturais

### 1.1 Objetivo

Construir e implantar um sistema automatizado para Swing Trade em criptoativos na Binance Spot Testnet operando sob **custo zero perpétuo** de infraestrutura e inteligência artificial. O pipeline analítico adota um modelo de consenso ponderado entre modelos de linguagem (Groq + Gemini Flash) e cálculos estatísticos locais.

### 1.2 Princípios de Design "Zero-Server"

* **Sem Servidor Ativo (No 24/7 Containers):** Eliminação de servidores FastAPI/Uvicorn rodando o dia todo. O motor de execução funciona como um job pontual ativado por relógio via **GitHub Actions**.
* **Infraestrutura Serverless Desacoplada:** Persistência via **Neon PostgreSQL** e interface web estática/PWA hospedada no **Cloudflare Pages**.
* **Sem API Intermediária Dedicada:** O frontend lê as métricas e logs diretamente do banco de dados relacional via conexão HTTP autenticada (driver Neon Serverless), dispensando a manutenção de endpoints backend clássicos.
* **Saída Delegada (Native OCO):** O encerramento de posições não depende de polling de software; ordens de Take Profit e Stop Loss são inseridas diretamente no matching engine da exchange via OCO.
* **Segurança e Isolamento de Chaves:** Chaves de API ficam isoladas em GitHub Secrets e Cloudflare Environment Variables, limitadas exclusivamente a leitura e envio de ordens Spot. **Permissões de saque na API são estritamente proibidas**.

---

## 2. Visão Geral dos Componentes e Camada de Custos

| Camada | Ferramenta / Serviço | Papel Arquitetural | Cota Gratuita / Custo |
| :--- | :--- | :--- | :--- |
| **Worker / Engine** | GitHub Actions | Executa o script Python diário (análise, consenso e envio de ordens). | 2.000 min/mês (Consumo previsto: ~30 min/mês = **Grátis**) |
| **Database** | Neon (PostgreSQL) | Armazena histórico de ordens, logs de consenso e saldos virtuais. | 0.5 GB Storage + auto-suspend (**Grátis**) |
| **Interface / PWA** | Cloudflare Pages | Hospeda o frontend React/Vite com suporte a PWA (Mobile & Desktop). | Hospedagem estática e largura de banda ilimitadas (**Grátis**) |
| **IA Técnica** | Groq API | Processa indicadores técnicos com Llama 3.3 70B em alta velocidade. | Free Tier oficial (alta taxa de requisições por minuto) (**Grátis**) |
| **IA Sentimento** | Google Gemini API | Analisa notícias e Fear & Greed com Gemini Flash. | Google AI Studio Free Tier (**Grátis**) |
| **Exchange** | Binance Spot Testnet | Executa ordens simuladas e hospeda ordens OCO no livro oficial. | Acesso público para testes (**Grátis**) |

---

## 3. Arquitetura Lógica e Fluxo Operacional

```
[Trigger Diário: 21:05 BRT (00:05 UTC)]
                 │
                 ▼
     ┌───────────────────────┐
     │    GitHub Actions     │  (Executa ambiente efêmero Python)
     │     (Worker Job)      │
     └───────────┬───────────┘
                 │
                 ├─► 1. Busca cotações D1 e calcula indicadores (ATR, RSI, EMAs)
                 ├─► 2. Dispara consulta ao Groq (Agente Técnico)
                 ├─► 3. Dispara consulta ao Gemini Flash (Agente Sentimento)
                 ├─► 4. Consensus Engine avalia Score e ausência de Veto
                 ├─► 5. Se aprovado: Envia Compra a Mercado + OCO na Binance Testnet
                 └─► 6. Persiste resultados e saldos diretamente no Neon
                                      │
                                      ▼
                           ┌─────────────────────┐
                           │ Neon (PostgreSQL)   │
                           │  (Serverless DB)    │
                           └──────────▲──────────┘
                                      │ (Query segura via HTTP / SDK)
                                      │
                           ┌──────────┴──────────┐
                           │  Cloudflare Pages   │
                           │  (React PWA no Cel) │
                           └─────────────────────┘
```

---

## 4. Ciclo Operacional e Temporização

### 4.1 Horário Operacional
* O fechamento oficial do candle diário da Binance ocorre às 00:00 UTC (**21:00 BRT**).
* **Disparo do Cron:** O fluxo do GitHub Actions é configurado com a expressão cron `5 0 * * *` (**21:05 BRT**), garantindo a consolidação dos dados do dia anterior.

### 4.2 Fluxo Sequencial de Execução do Script (`engine.py`)

1. **Checagem de Estado:** O script conecta ao Neon e consulta a tabela `trades`.
   * Se houver ordem com status `OPEN_OCO`, ele consulta a API da Binance para verificar se a OCO foi preenchida (por Stop Loss ou Take Profit).
   * Se a ordem foi preenchida:
     * Calcula o PnL final.
     * Atualiza o registro para `CLOSED_TP` ou `CLOSED_SL`.
     * Se fechou no lucro, divide o ganho líquido (50% para `withdrawable_pool` e 50% para `trading_balance`).
     * Libera o sistema para nova análise (`IDLE`).
   * Se a ordem ainda estiver ativa no livro: encerra a execução sem abrir novas ordens.
2. **Varredura e Análise de Pares (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`):**
   * Coleta dos últimos 60 candles diários via Binance Testnet.
   * Cálculo em memória de EMA 20, EMA 50, EMA 200, RSI 14 e ATR 14.
   * Chamadas em paralelo para Groq e Gemini API.
3. **Mecanismo de Consenso:**
   * Aplica a fórmula ponderada de pontuação.
   * Valida a ausência de veto de ambos os modelos.
4. **Execução de Ordem:**
   * Caso o ativo de maior nota atinja $\text{Score} \ge 75$:
     * Submete ordem de compra a mercado.
     * Submete ordem OCO vinculada (Stop Loss e Take Profit calculados via ATR).
5. **Gravação e Desligamento:**
   * Insere os logs de decisão em `consensus_logs`.
   * Atualiza o estado da posição e finaliza o runner do GitHub Actions (tempo total de máquina: ~40 segundos).

---

## 5. Especificação dos Agentes e Consenso

### 5.1 Agentes Especializados

* **Agente 1: Análise Técnica (Groq / Llama 3.3 70B):**
  * **Peso:** $0.60$ (60%).
  * **Foco:** Relação de tendência (médias móveis), momentum (RSI) e quebras de estrutura.
  * Retorna payload JSON com `score` (0 a 100), flag `veto` (boolean) e `reasoning` (resumo técnico).

* **Agente 2: Sentimento e Notícias (Gemini Flash):**
  * **Peso:** $0.40$ (40%).
  * **Foco:** Leitura do índice *Crypto Fear & Greed* e manchetes recentes.
  * **Condição de Veto:** Veta se Fear & Greed $< 20$ (pânico generalizado) ou se houver menção direta a exploits, hacks ou investigações criminais no ativo.

* **Agente 3: Risco e Dimensionamento (Função Python Determinística):**
  * Executa os cálculos matemáticos sem uso de LLM para eliminar erros de alucinação numérica.

### 5.2 Regras Matemáticas de Risco e Saída

* **Distância do Stop Loss ($D_{SL}$):**
  $$D_{SL} = 1.5 \times \text{ATR}_{14}$$
  $$\text{Preço Stop} = \text{Preço de Entrada} - D_{SL}$$
* **Preço do Take Profit:**
  $$\text{Preço TP} = \text{Preço de Entrada} + (2.0 \times D_{SL})$$
  *(Relação Risco:Retorno de 1:2)*
* **Consenso Final:**
  $$\text{Final Score} = (\text{Score}_{\text{técnico}} \times 0.60) + (\text{Score}_{\text{sentimento}} \times 0.40)$$
  * Disparo de compra ocorre apenas se $\text{Final Score} \ge 75$ e nenhum agente emitir veto.

---

## 6. Modelagem do Banco de Dados (Neon PostgreSQL)

```sql
-- Histórico e status das operações
CREATE TABLE trades (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    entry_price NUMERIC(18, 8) NOT NULL,
    exit_price NUMERIC(18, 8),
    quantity NUMERIC(18, 8) NOT NULL,
    stop_loss NUMERIC(18, 8) NOT NULL,
    take_profit NUMERIC(18, 8) NOT NULL,
    binance_order_list_id BIGINT, -- ID da ordem OCO na Binance
    status VARCHAR(20) NOT NULL, -- 'OPEN_OCO', 'CLOSED_TP', 'CLOSED_SL', 'MANUAL_EXIT'
    pnl_usd NUMERIC(18, 4) DEFAULT 0.0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMP WITH TIME ZONE
);

-- Logs das deliberações dos agentes
CREATE TABLE consensus_logs (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    technical_score NUMERIC(5, 2) NOT NULL,
    sentiment_score NUMERIC(5, 2) NOT NULL,
    final_score NUMERIC(5, 2) NOT NULL,
    veto_applied BOOLEAN NOT NULL DEFAULT FALSE,
    reasoning_summary TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Livro-razão contábil para isolamento de capital
CREATE TABLE portfolio_ledger (
    id SERIAL PRIMARY KEY,
    trading_balance NUMERIC(18, 4) NOT NULL, -- Capital de giro ativo
    withdrawable_pool NUMERIC(18, 4) NOT NULL, -- Lucro retido protegido para saque
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

---

## 7. Frontend e Interface PWA (Cloudflare Pages)

O frontend é uma Single Page Application (SPA) construída com **React + Tailwind CSS** e empacotada com manifest PWA para instalação direta na tela de início do smartphone.

### 7.1 Acesso aos Dados sem Backend Dedicado
* Para leituras (dashboard, scores, histórico de trades), a SPA conecta-se diretamente ao Neon utilizando o driver `@neondatabase/serverless` via WebSockets/HTTP, ou utiliza **Cloudflare Pages Functions** (Edge handlers leves de JavaScript incluídos gratuitamente no Cloudflare Pages) para consultar o banco sem expor credenciais diretas no bundle do cliente.

### 7.2 Telas do Aplicativo

1. **Dashboard Principal:**
   * **Pool de Retirada (Destaque):** Exibe o valor acumulado em dólares/reais pronto para saque manual via Binance Lite (Pix).
   * **Capital de Giro:** Saldo reservado para as próximas operações.
   * **Posição Aberta:** Indicador em tempo real de ativo comprado, preço de entrada, distância para o Stop Loss e para o Take Profit.
2. **Painel do Comitê de IA:**
   * Notas atribuídas no último ciclo pelo Groq e pelo Gemini.
   * Textos explicativos dos motivos da aprovação ou veto.
3. **Histórico de Trades:**
   * Lista de operações fechadas com badge verde (Take Profit atingido) ou vermelho (Stop Loss atingido) e percentuais de lucro.

---

## 8. Estrutura do Repositório (Monorepo Enxuto)

```
.
├── .github/
│   └── workflows/
│       └── trading_engine.yml    # Workflow agendado (Cron 21:05 BRT)
├── engine/                       # Backend sob demanda (Worker Python)
│   ├── agents/
│   │   ├── technical.py          # Agente Groq (Llama 3.3)
│   │   ├── sentiment.py          # Agente Gemini Flash
│   │   └── risk.py               # Matemática de ATR e dimensionamento
│   ├── database.py               # Conexão psycopg2 / SQLAlchemy com Neon
│   ├── exchange.py               # Cliente CCXT para Binance Spot Testnet
│   ├── main.py                   # Script de execução disparado pelo Actions
│   └── requirements.txt
├── web/                          # Frontend React PWA
│   ├── src/
│   │   ├── App.jsx
│   │   └── lib/db.js             # Consulta serverless ao banco
│   ├── functions/                # (Opcional) Cloudflare Edge Functions
│   │   └── api/overview.js
│   ├── public/
│   │   └── manifest.json         # Suporte a PWA (Mobile Home Screen)
│   ├── package.json
│   └── vite.config.js
└── README.md
```

---

## 9. Configuração de Variáveis de Ambiente e Segredos

### 9.1 GitHub Secrets (Configurados no repositório GitHub)
* `BINANCE_TESTNET_API_KEY`: Chave da Testnet Binance Spot.
* `BINANCE_TESTNET_SECRET_KEY`: Chave secreta da Testnet.
* `GROQ_API_KEY`: Chave gratuita de API da Groq.
* `GEMINI_API_KEY`: Chave gratuita de API do Google AI Studio.
* `DATABASE_URL`: Connection string do banco Neon (`postgres://...`).

### 9.2 Cloudflare Pages Environment Variables
* `DATABASE_URL`: Connection string do Neon para consultas das Edge Functions do dashboard.