# 🤖 CashBot — Multi-Agent Crypto Trading & Portfolio Monitoring

Sistema automatizado para Swing Trade em criptoativos operando sob **custo zero perpétuo** de infraestrutura e inteligência artificial (Groq + Gemini Flash), com interface **PWA Mobile-First** para celular e PC, e notificações instantâneas no smartphone.

---

## 📱 Acesso Rápido ao Appzinho (PC e Celular)

O servidor do aplicativo já está configurado e pronto para rodar sem precisar de Node.js nem privilégios de administrador:

* **No seu PC:** [http://localhost:8080](http://localhost:8080)
* **No seu Celular (mesmo Wi-Fi):** `http://192.168.0.149:8080`

> 💡 **Como instalar como App no Celular:**
> 1. Abra o link no Chrome (Android) ou Safari (iPhone).
> 2. Toque no botão de menu/compartilhar e selecione **"Adicionar à Tela de Início"**.
> 3. O CashBot será instalado com ícone próprio e abrirá em tela cheia como um app nativo!

---

## 🔔 Notificações Instantâneas no Celular

Para receber notificações com som e vibração toda vez que o bot fizer uma análise ou executar um trade (mesmo na simulação):

1. Abra o Telegram no celular e procure pelo bot oficial **[@BotFather](https://t.me/BotFather)**.
2. Envie o comando `/newbot` e siga as instruções para obter o seu **Bot Token**.
3. Envie uma mensagem para o bot **[@userinfobot](https://t.me/userinfobot)** para descobrir o seu **Chat ID**.
4. No app CashBot (na aba **Simulação**), cole seu Token e Chat ID e clique em **"Salvar Chaves"**.
5. Clique em **"Disparar Teste no Telegram"** para ver a notificação apitando no seu aparelho!

---

## 🚀 Como Iniciar o App

Para iniciar o servidor a qualquer momento:

```bash
python web_app.py 8080
```

Para rodar uma simulação da engine via linha de comando:

```bash
# Executa a varredura dos pares com o comitê de IA
python engine/main.py --simulate

# Força uma compra simulada para testar a ordem OCO e as notificações
python engine/main.py --simulate --force-buy
```

---

## 🏛️ Arquitetura do Sistema (Baseada no SDD)

* **Multi-Agent Consensus:**
  * **Agente Técnico (Groq / Llama 3.3 70B):** Avalia tendências, rompimentos, EMAs (20, 50, 200) e RSI 14 (Peso 60%).
  * **Agente de Sentimento (Google Gemini Flash):** Avalia notícias e o índice Crypto Fear & Greed ao vivo (Peso 40%).
  * **Agente de Risco (Determinístico):** Stop Loss baseado em $1.5 \times \text{ATR}_{14}$ e Take Profit em $2.0 \times \text{SL}$ (relação 1:2).
* **Gestão de Lucros (Pool de Retirada):**
  * Ao atingir o Take Profit, 50% do lucro líquido vai para o **Pool de Saque** (destinado a Pix) e 50% é reinvestido no **Capital de Giro**.
* **Infraestrutura Serverless (Custo Zero):**
  * **GitHub Actions:** Executa o script diariamente às 21:05 BRT (`.github/workflows/trading_engine.yml`).
  * **Neon PostgreSQL:** Banco serverless para persistência de trades, saldos e deliberações.
  * **PWA Frontend:** Hospedável gratuitamente no Cloudflare Pages ou servido localmente via Python.
