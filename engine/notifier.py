"""
Sistema de Notificações Instantâneas do CashBot.
Envia alertas diretamente para o smartphone via Telegram Bot (gratuito)
e registra logs no terminal/persistência.
"""

import os
import requests
import logging

logger = logging.getLogger("cashbot.notifier")

class TelegramNotifier:
    def __init__(self, token: str = None, chat_id: str = None):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.base_url = f"https://api.telegram.org/bot{self.token}" if self.token else None

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Envia mensagem de texto formatada para o celular via Telegram."""
        if not self.is_configured:
            logger.info(f"[NOTIFIER (Console only - configure TELEGRAM_BOT_TOKEN/CHAT_ID)]\n{text}")
            return False

        try:
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }
            resp = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info("Notificação enviada com sucesso ao Telegram.")
                return True
            else:
                logger.error(f"Erro ao enviar Telegram ({resp.status_code}): {resp.text}")
                return False
        except Exception as e:
            logger.error(f"Falha de conexão com Telegram: {e}")
            return False

    def notify_daily_analysis(self, symbol: str, tech_score: float, sent_score: float, final_score: float, veto: bool, action: str, details: str):
        """Notifica o resultado do consenso do comitê de IA."""
        status_icon = "🟢" if action == "BUY" else ("🔴" if veto else "🟡")
        msg = (
            f"🤖 <b>CashBot — Deliberação de IA</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Ativo:</b> #{symbol}\n"
            f"<b>Veredito:</b> {status_icon} <b>{action}</b> (Score: {final_score:.1f}/100)\n\n"
            f"📊 <b>Score Técnico (Groq / Llama 70B):</b> {tech_score:.1f}\n"
            f"📰 <b>Score Sentimento (Gemini Flash):</b> {sent_score:.1f}\n"
            f"🛡️ <b>Veto Aplicado:</b> {'SIM (Operação Bloqueada)' if veto else 'NÃO'}\n\n"
            f"📝 <b>Resumo:</b>\n<i>{details}</i>\n"
        )
        return self.send_message(msg)

    def notify_order_placed(self, symbol: str, entry_price: float, qty: float, sl_price: float, tp_price: float, is_simulated: bool = False):
        """Notifica abertura de compra + ordem OCO vinculada."""
        tag = "🧪 <b>[SIMULAÇÃO]</b> " if is_simulated else "🚀 "
        msg = (
            f"{tag}<b>ORDEM EXECUTADA + OCO ARMADA!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Ativo:</b> {symbol}\n"
            f"<b>Entrada:</b> ${entry_price:,.2f}\n"
            f"<b>Quantidade:</b> {qty:.6f}\n\n"
            f"🛑 <b>Stop Loss (Risco):</b> ${sl_price:,.2f}\n"
            f"🎯 <b>Take Profit (Alvo 2R):</b> ${tp_price:,.2f}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>Ordem OCO ativa na Binance. O bot monitorará o encerramento.</i>"
        )
        return self.send_message(msg)

    def notify_order_closed(self, symbol: str, outcome: str, entry_price: float, exit_price: float, pnl_usd: float, to_withdraw: float, to_reinvest: float, is_simulated: bool = False):
        """Notifica fechamento de posição (Take Profit ou Stop Loss)."""
        tag = "🧪 [SIMULAÇÃO] " if is_simulated else ""
        if outcome == "TP":
            header = f"🎯 {tag}<b>TAKE PROFIT ATINGIDO! LUCRO!</b> 💰"
            icon = "🟢"
        else:
            header = f"🛑 {tag}<b>STOP LOSS ACIONADO (Risco Controlado)</b>"
            icon = "🔴"

        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        msg = (
            f"{header}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Ativo:</b> {symbol}\n"
            f"<b>Preço de Entrada:</b> ${entry_price:,.2f}\n"
            f"<b>Preço de Saída:</b> ${exit_price:,.2f}\n"
            f"<b>PnL:</b> {icon} <b>${pnl_usd:+,.2f} ({pnl_pct:+.2f}%)</b>\n\n"
        )
        if pnl_usd > 0:
            msg += (
                f"🏦 <b>Alocação do Lucro Líquido:</b>\n"
                f"  ├─ 💼 Capital de Giro (+50%): +${to_reinvest:,.2f}\n"
                f"  └─ 💸 Pool para Saque Pix (+50%): +${to_withdraw:,.2f}\n"
            )
        msg += "━━━━━━━━━━━━━━━━━━━━\n<i>Sistema pronto para a próxima oportunidade.</i>"
        return self.send_message(msg)

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    notifier = TelegramNotifier()
    if notifier.is_configured:
        print("Enviando mensagem de teste para o Telegram...")
        res = notifier.send_message("🧪 <b>CashBot Teste:</b> Notificação configurada com sucesso no seu celular!")
        print("Resultado:", res)
    else:
        print("Telegram não configurado. Defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env para receber alertas no celular.")

