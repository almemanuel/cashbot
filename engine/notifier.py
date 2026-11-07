"""
Sistema de Notificações Instantâneas do CashBot.
Envia alertas diretamente para o smartphone via Telegram Bot (gratuito)
e registra logs no terminal/persistência.
Segue Object Calisthenics (1 nível de indentação por método, sem else).
"""

import os
import logging
from typing import Optional, Tuple
import requests

logger = logging.getLogger("cashbot.notifier")


class TelegramNotifier:
    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
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

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        try:
            resp = requests.post(f"{self.base_url}/sendMessage", json=payload, timeout=10)
            return self._handle_telegram_response(resp)
        except Exception as e:
            logger.error(f"Falha de conexão com Telegram: {e}")
            return False

    @staticmethod
    def _handle_telegram_response(resp: requests.Response) -> bool:
        if resp.status_code == 200:
            logger.info("Notificação enviada com sucesso ao Telegram.")
            return True
        logger.error(f"Erro ao enviar Telegram ({resp.status_code}): {resp.text}")
        return False

    def notify_daily_analysis(
        self,
        symbol: str,
        tech_score: float,
        sent_score: float,
        final_score: float,
        veto: bool,
        action: str,
        details: str
    ) -> bool:
        """Notifica o resultado do consenso do comitê de IA."""
        status_icon = self._resolve_action_icon(action, veto)
        veto_label = "SIM (Operação Bloqueada)" if veto else "NÃO"
        msg = (
            f"🤖 <b>CashBot — Deliberação de IA</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Ativo:</b> #{symbol}\n"
            f"<b>Veredito:</b> {status_icon} <b>{action}</b> (Score: {final_score:.1f}/100)\n\n"
            f"📊 <b>Score Técnico (Groq / Llama 70B):</b> {tech_score:.1f}\n"
            f"📰 <b>Score Sentimento & Notícias (Gemini Flash):</b> {sent_score:.1f}\n"
            f"🛡️ <b>Veto Aplicado:</b> {veto_label}\n\n"
            f"📝 <b>Resumo:</b>\n<i>{details}</i>\n"
        )
        return self.send_message(msg)

    @staticmethod
    def _resolve_action_icon(action: str, veto: bool) -> str:
        if action == "BUY":
            return "🟢"
        if veto:
            return "🔴"
        return "🟡"

    def notify_order_placed(
        self,
        symbol: str,
        entry_price: float,
        qty: float,
        sl_price: float,
        tp_price: float,
        is_simulated: bool = False
    ) -> bool:
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

    def notify_order_closed(
        self,
        symbol: str,
        outcome: str,
        entry_price: float,
        exit_price: float,
        pnl_usd: float,
        to_withdraw: float,
        to_reinvest: float,
        is_simulated: bool = False
    ) -> bool:
        """Notifica fechamento de posição (Take Profit ou Stop Loss)."""
        tag = "🧪 [SIMULAÇÃO] " if is_simulated else ""
        header, icon = self._resolve_close_banner(outcome, tag)
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        profit_block = self._format_profit_allocation(pnl_usd, to_reinvest, to_withdraw)

        msg = (
            f"{header}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Ativo:</b> {symbol}\n"
            f"<b>Preço de Entrada:</b> ${entry_price:,.2f}\n"
            f"<b>Preço de Saída:</b> ${exit_price:,.2f}\n"
            f"<b>PnL:</b> {icon} <b>${pnl_usd:+,.2f} ({pnl_pct:+.2f}%)</b>\n\n"
            f"{profit_block}"
            f"━━━━━━━━━━━━━━━━━━━━\n<i>Sistema pronto para a próxima oportunidade.</i>"
        )
        return self.send_message(msg)

    @staticmethod
    def _resolve_close_banner(outcome: str, tag: str) -> Tuple[str, str]:
        if outcome == "TP":
            return f"🎯 {tag}<b>TAKE PROFIT ATINGIDO! LUCRO!</b> 💰", "🟢"
        return f"🛑 {tag}<b>STOP LOSS ACIONADO (Risco Controlado)</b>", "🔴"

    @staticmethod
    def _format_profit_allocation(pnl_usd: float, to_reinvest: float, to_withdraw: float) -> str:
        if pnl_usd <= 0:
            return ""
        return (
            f"🏦 <b>Alocação do Lucro Líquido:</b>\n"
            f"  ├─ 💼 Capital de Giro (+50%): +${to_reinvest:,.2f}\n"
            f"  └─ 💸 Pool para Saque Pix (+50%): +${to_withdraw:,.2f}\n\n"
        )


def _run_cli_test() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    notifier = TelegramNotifier()
    if not notifier.is_configured:
        print("Telegram não configurado. Defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env para receber alertas no celular.")
        return
    print("Enviando mensagem de teste para o Telegram...")
    res = notifier.send_message("🧪 <b>CashBot Teste:</b> Notificação configurada com sucesso no seu celular!")
    print("Resultado:", res)


if __name__ == "__main__":
    _run_cli_test()
