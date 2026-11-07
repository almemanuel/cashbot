"""
Sistema de Notificações Instantâneas do CashBot.
Envia alertas em linguagem simples, direta e amigável para leitura rápida no celular via Telegram.
Segue Object Calisthenics (1 nível de indentação por método, sem else).
"""

import os
import html
import logging
from typing import Optional, Tuple, List, Dict, Any
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
        details: str,
        ranking_lines: Optional[List[str]] = None,
        tech_reason: str = "",
        sent_reason: str = "",
        trading_balance: float = 0.0,
        withdrawable_pool: float = 0.0
    ) -> bool:
        """Envia um resumo humano e direto da análise do dia."""
        coin = symbol.split("/")[0]
        ranking_block = self._format_ranking_block(ranking_lines, coin, final_score, veto)
        explanation_block = self._format_explanation_block(coin, details, tech_reason, sent_reason)
        wallet_block = self._format_wallet_footer(trading_balance, withdrawable_pool)

        msg = (
            f"🤖 <b>CashBot — Resumo de Hoje</b>\n\n"
            f"⏸️ <b>O que o robô fez:</b> Não comprou nada hoje.\n"
            f"<i>(Para entrar comprando com segurança, uma moeda precisa atingir pelo menos <b>65 pontos</b> de 100).</i>\n\n"
            f"📊 <b>Notas das moedas analisadas hoje:</b>\n"
            f"{ranking_block}\n\n"
            f"💡 <b>Por que ficamos de fora (destaque: {coin}):</b>\n"
            f"{explanation_block}"
            f"{wallet_block}"
        )
        return self.send_message(msg)

    @staticmethod
    def _format_wallet_footer(trading_balance: float, withdrawable_pool: float) -> str:
        if trading_balance <= 0 and withdrawable_pool <= 0:
            return ""
        brl_est = withdrawable_pool * 5.80
        status_saque = (
            f"<b>US$ {withdrawable_pool:,.2f}</b> <i>(≈ R$ {brl_est:,.2f} — Liberado p/ Pix!)</i>"
            if withdrawable_pool >= 10.0
            else "US$ 0.00 <i>(Reinvestindo 100% até atingir o mínimo de US$ 10 p/ saque)</i>"
        )
        return (
            f"\n\n💼 <b>Sua Carteira Agora:</b>\n"
            f"• 🔄 <b>Capital de Giro Ativo:</b> US$ {trading_balance:,.2f}\n"
            f"• 💸 <b>Valor Sugerido p/ Saque (Pix):</b> {status_saque}"
        )

    @staticmethod
    def _format_ranking_block(
        ranking_lines: Optional[List[str]],
        coin: str,
        final_score: float,
        veto: bool
    ) -> str:
        if ranking_lines:
            return "\n".join(ranking_lines)
        veto_tag = " 🚫 <i>(Bloqueada por risco)</i>" if veto else ""
        return f"• <b>{coin}:</b> {final_score:.0f}/100 pts{veto_tag}"

    @staticmethod
    def _format_explanation_block(
        coin: str,
        details: str,
        tech_reason: str,
        sent_reason: str
    ) -> str:
        if tech_reason or sent_reason:
            safe_tech = html.escape(tech_reason)
            safe_sent = html.escape(sent_reason)
            return (
                f"• <b>Gráfico ({coin}):</b> {safe_tech}\n"
                f"• <b>Notícias e Humor:</b> {safe_sent}"
            )
        return f"• {html.escape(details)}"

    def notify_order_placed(
        self,
        symbol: str,
        entry_price: float,
        qty: float,
        sl_price: float,
        tp_price: float,
        is_simulated: bool = False,
        ranking_lines: Optional[List[str]] = None,
        tech_reason: str = "",
        sent_reason: str = ""
    ) -> bool:
        """Notifica abertura de compra em linguagem simples e clara."""
        tag = "🧪 <b>[TESTE SIMULADO]</b>\n" if is_simulated else ""
        coin = symbol.split("/")[0]
        total_invested = entry_price * qty
        tp_pct = ((tp_price - entry_price) / entry_price) * 100.0 if entry_price > 0 else 0.0
        sl_pct = ((entry_price - sl_price) / entry_price) * 100.0 if entry_price > 0 else 0.0
        expected_profit = (tp_price - entry_price) * qty
        why_block = self._format_buy_reason_block(coin, tech_reason, sent_reason, ranking_lines)
        msg = (
            f"{tag}🟢 <b>CashBot — Nova Compra de Giro Rápido!</b>\n\n"
            f"🪙 <b>Moeda comprada:</b> {symbol}\n"
            f"💵 <b>Valor alocado:</b> US$ {total_invested:,.2f}\n"
            f"🏷️ <b>Preço de entrada:</b> US$ {entry_price:,.4f}\n\n"
            f"🛡️ <b>Alvos dinâmicos definidos pela IA:</b>\n"
            f"• 🎯 <b>Vender com Lucro em:</b> US$ {tp_price:,.4f} (<b>+{tp_pct:.1f}%</b> 👉 lucro de <b>+US$ {expected_profit:,.2f}</b>)\n"
            f"• 🛑 <b>Parar Perda em:</b> US$ {sl_price:,.4f} (<b>-{sl_pct:.1f}%</b>)\n\n"
            f"{why_block}"
            f"<i>Você não precisa fazer nada. O robô acompanha sozinho e te avisa quando vender!</i>"
        )
        return self.send_message(msg)

    @staticmethod
    def _format_buy_reason_block(
        coin: str,
        tech_reason: str,
        sent_reason: str,
        ranking_lines: Optional[List[str]]
    ) -> str:
        if not (tech_reason or sent_reason or ranking_lines):
            return ""
        ranking_str = "\n".join(ranking_lines or [])
        return (
            f"💡 <b>Por que o robô escolheu {coin} hoje:</b>\n"
            f"• <b>Gráfico:</b> {html.escape(tech_reason)}\n"
            f"• <b>Notícias e Humor:</b> {html.escape(sent_reason)}\n\n"
            f"📊 <b>Placar das moedas analisadas:</b>\n{ranking_str}\n\n"
        )

    def notify_order_closed(
        self,
        symbol: str,
        outcome: str,
        entry_price: float,
        exit_price: float,
        pnl_usd: float,
        to_withdraw: float,
        to_reinvest: float,
        is_simulated: bool = False,
        new_trading_balance: float = 0.0,
        new_withdrawable_pool: float = 0.0
    ) -> bool:
        """Notifica fechamento de posição (Lucro ou Proteção) de forma simples."""
        tag = "🧪 <b>[TESTE SIMULADO]</b>\n" if is_simulated else ""
        header, result_line = self._resolve_human_close_summary(outcome, pnl_usd, entry_price, exit_price)
        profit_block = self._format_profit_allocation(pnl_usd, to_reinvest, to_withdraw)
        wallet_block = self._format_wallet_footer(new_trading_balance, new_withdrawable_pool)

        msg = (
            f"{tag}{header}\n\n"
            f"🪙 <b>Moeda:</b> {symbol}\n"
            f"📥 <b>Comprou por:</b> US$ {entry_price:,.4f}\n"
            f"📤 <b>Vendeu por:</b> US$ {exit_price:,.4f}\n"
            f"{result_line}\n\n"
            f"{profit_block}"
            f"<i>O robô já está livre para buscar a próxima oportunidade.</i>"
            f"{wallet_block}"
        )
        return self.send_message(msg)

    @staticmethod
    def _resolve_human_close_summary(
        outcome: str,
        pnl_usd: float,
        entry_price: float,
        exit_price: float
    ) -> Tuple[str, str]:
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        if outcome == "TP":
            header = "💰 <b>CashBot — Venda com Lucro Concluída!</b>"
            line = f"✅ <b>Seu Lucro:</b> +US$ {pnl_usd:,.2f} (+{pnl_pct:.1f}%)"
            return header, line
        header = "🛑 <b>CashBot — Venda de Proteção Acionada (Stop)</b>"
        line = f"🛡️ <b>Perda controlada em:</b> -US$ {abs(pnl_usd):,.2f} ({pnl_pct:.1f}%)"
        return header, line

    @staticmethod
    def _format_profit_allocation(pnl_usd: float, to_reinvest: float, to_withdraw: float) -> str:
        if pnl_usd <= 0:
            return ""
        return (
            f"🏦 <b>Divisão inteligente deste lucro:</b>\n"
            f"• 📈 <b>Reinvestido no Giro (Bola de Neve):</b> +US$ {to_reinvest:,.2f}\n"
            f"• 💸 <b>Separado p/ Saque (Pix):</b> +US$ {to_withdraw:,.2f}\n\n"
        )


def _run_cli_test() -> None:
    from dotenv import load_dotenv
    load_dotenv()
    notifier = TelegramNotifier()
    if not notifier.is_configured:
        print("Telegram não configurado. Defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no .env para receber alertas no celular.")
        return
    print("Enviando mensagem de teste para o Telegram...")
    res = notifier.send_message("🧪 <b>CashBot:</b> O alerta no seu celular está funcionando perfeitamente!")
    print("Resultado:", res)


if __name__ == "__main__":
    _run_cli_test()
