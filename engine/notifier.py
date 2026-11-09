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
            f"<b>US$ {withdrawable_pool:,.2f}</b> <i>(≈ R$ {brl_est:,.2f} — Reservado até 23h BRT!)</i>"
            if withdrawable_pool > 0
            else "US$ 0.00"
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
        sent_reason: str = "",
        prev_portfolio_total: float = 0.0,
        current_portfolio_total: float = 0.0,
        invested_total: float = 0.0,
        free_cash: float = 0.0,
        withdrawable_pool: float = 0.0
    ) -> bool:
        """Notifica abertura de compra em linguagem limpa, simples e completa para leigos."""
        tag = "🧪 <b>[TESTE SIMULADO]</b>\n" if is_simulated else ""
        coin = symbol.split("/")[0]
        total_invested = entry_price * qty
        tp_pct = ((tp_price - entry_price) / entry_price) * 100.0 if entry_price > 0 else 0.0
        expected_profit = (tp_price - entry_price) * qty
        why_block = self._format_buy_reason_block(coin, tech_reason, sent_reason)
        portfolio_block = self._format_operation_portfolio_block(
            prev_portfolio_total, current_portfolio_total, 0.0, invested_total, free_cash, withdrawable_pool
        )
        msg = (
            f"{tag}🟢 <b>CashBot — Nova Compra Realizada!</b>\n\n"
            f"🪙 <b>Moeda comprada:</b> {symbol}\n"
            f"💵 <b>Valor investido nesta compra:</b> US$ {total_invested:,.2f}\n"
            f"🏷️ <b>Preço de compra:</b> US$ {entry_price:,.4f}\n"
            f"🎯 <b>Meta de venda:</b> US$ {tp_price:,.4f} (<b>+{tp_pct:.1f}%</b> 👉 lucro estimado de <b>+US$ {expected_profit:,.2f}</b>)\n\n"
            f"{why_block}"
            f"{portfolio_block}"
        )
        return self.send_message(msg)

    @staticmethod
    def _format_buy_reason_block(
        coin: str,
        tech_reason: str,
        sent_reason: str
    ) -> str:
        if not (tech_reason or sent_reason):
            return ""
        return (
            f"💡 <b>Por que compramos {coin} agora:</b>\n"
            f"• <b>Momento do Preço:</b> {html.escape(tech_reason)}\n"
            f"• <b>Clima do Mercado:</b> {html.escape(sent_reason)}\n\n"
        )

    @staticmethod
    def _format_operation_portfolio_block(
        prev_total: float,
        current_total: float,
        round_profit: float,
        invested_total: float,
        free_cash: float,
        withdrawable_pool: float
    ) -> str:
        if current_total <= 0 and prev_total <= 0:
            return ""
        profit_line = (
            f"• ✨ <b>Lucro desta rodada:</b> +US$ {round_profit:,.2f}\n"
            if round_profit > 0
            else ""
        )
        brl_est = withdrawable_pool * 5.80
        return (
            f"💼 <b>Resumo da sua Conta:</b>\n"
            f"• 📊 <b>Patrimônio Anterior:</b> US$ {prev_total:,.2f}\n"
            f"• 💰 <b>Patrimônio Atual:</b> US$ {current_total:,.2f}\n"
            f"{profit_line}"
            f"• 📈 <b>Total Operando nas Moedas:</b> US$ {invested_total:,.2f}\n"
            f"• 💵 <b>Caixa Livre p/ Compras:</b> US$ {free_cash:,.2f}\n"
            f"• 💸 <b>Guardado p/ Saque Hoje:</b> US$ {withdrawable_pool:,.2f} <i>(≈ R$ {brl_est:,.2f})</i>"
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
        new_withdrawable_pool: float = 0.0,
        prev_portfolio_total: float = 0.0,
        current_portfolio_total: float = 0.0,
        invested_total: float = 0.0,
        free_cash: float = 0.0,
        unrecovered_loss_usd: float = 0.0
    ) -> bool:
        """Notifica fechamento de posição com resumo completo de patrimônio antes/depois e lucro da rodada."""
        tag = "🧪 <b>[TESTE SIMULADO]</b>\n" if is_simulated else ""
        header, result_line = self._resolve_human_close_summary(outcome, pnl_usd, entry_price, exit_price)
        profit_block = self._format_profit_allocation(pnl_usd, to_reinvest, to_withdraw, unrecovered_loss_usd)
        eff_current = current_portfolio_total or (new_trading_balance + new_withdrawable_pool)
        eff_prev = prev_portfolio_total or max(0.0, eff_current - pnl_usd)
        portfolio_block = self._format_operation_portfolio_block(
            eff_prev, eff_current, pnl_usd, invested_total, free_cash, new_withdrawable_pool
        )

        msg = (
            f"{tag}{header}\n\n"
            f"🪙 <b>Moeda vendida:</b> {symbol}\n"
            f"📥 <b>Preço de compra:</b> US$ {entry_price:,.4f}\n"
            f"📤 <b>Preço de venda:</b> US$ {exit_price:,.4f}\n"
            f"{result_line}\n\n"
            f"{profit_block}"
            f"{portfolio_block}"
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
        if outcome == "ROTATION":
            header = "🔄 <b>CashBot — Rotação Ativa de Capital</b>"
            line = f"⚡ <b>Vaga liberada p/ oportunidade melhor:</b> {pnl_usd:+.2f} USD ({pnl_pct:+.2f}%)"
            return header, line
        if pnl_usd >= 0:
            header = "💰 <b>CashBot — Venda com Lucro Concluída!</b>"
            line = f"✅ <b>Lucro da Rodada:</b> +US$ {pnl_usd:,.2f} (<b>+{pnl_pct:.2f}%</b>)"
            return header, line
        if outcome == "TIME_STOP":
            header = "⏱️ <b>CashBot — Troca de Moeda por Tempo (3h)</b>"
            line = f"🔄 <b>Ajuste de saída p/ destravar saldo:</b> {pnl_usd:+.2f} USD ({pnl_pct:+.2f}%)"
            return header, line
        header = "🛑 <b>CashBot — Disjuntor de Segurança (-7.5%) Acionado</b>"
        line = f"🛡️ <b>Perda travada p/ proteger a banca:</b> -US$ {abs(pnl_usd):,.2f} ({pnl_pct:.2f}%)"
        return header, line

    @staticmethod
    def _format_profit_allocation(
        pnl_usd: float,
        to_reinvest: float,
        to_withdraw: float,
        unrecovered_loss_usd: float = 0.0
    ) -> str:
        if pnl_usd <= 0:
            return (
                f"🛠️ <b>Modo Recuperação Ativado:</b>\n"
                f"• Os próximos lucros irão <b>100% para o seu Capital de Giro</b> até recuperar totalmente os <b>US$ {unrecovered_loss_usd:,.2f}</b>!\n\n"
            )
        if unrecovered_loss_usd > 0:
            return (
                f"🏦 <b>Modo Recuperação de Capital (100% Reinvestido):</b>\n"
                f"• 🔄 <b>Devolvido ao seu Capital:</b> +US$ {to_reinvest:,.2f}\n"
                f"• 🎯 <b>Falta recuperar:</b> US$ {unrecovered_loss_usd:,.2f}\n\n"
            )
        return (
            f"🏦 <b>Para onde foi esse lucro:</b>\n"
            f"• 🔄 <b>Somado ao Capital de Giro:</b> +US$ {to_reinvest:,.2f}\n"
            f"• 💸 <b>Separado p/ seu Saque Hoje:</b> +US$ {to_withdraw:,.2f}\n\n"
        )

    def notify_end_of_day_summary(
        self,
        stats: Dict[str, Any],
        start_hour: int = 22,
        end_hour: int = 23
    ) -> bool:
        """Envia o consolidado diário no início da janela de pausa/saque (22h BRT)."""
        start_total = float(stats.get("start_of_day_total", 0.0))
        end_total = float(stats.get("end_of_day_total", 0.0))
        day_profit = float(stats.get("day_profit_usd", 0.0))
        closed_count = int(stats.get("closed_today_count", 0))
        open_count = int(stats.get("open_trades_count", 0))
        invested_usd = float(stats.get("invested_usd", 0.0))
        free_cash = float(stats.get("free_cash_usd", 0.0))
        pool = float(stats.get("withdrawable_pool", 0.0))
        withdraw_guide = self._format_withdraw_eligibility(pool, end_hour)

        msg = (
            f"🌙 <b>CashBot — Fechamento do Dia ({start_hour}h BRT)</b>\n\n"
            f"📊 <b>Balanço de Hoje:</b>\n"
            f"• 🌅 <b>Patrimônio no Início do Dia:</b> US$ {start_total:,.2f}\n"
            f"• 🏁 <b>Patrimônio Agora no Fim do Dia:</b> US$ {end_total:,.2f}\n"
            f"• 💰 <b>Lucro Conquistado Hoje:</b> +US$ {day_profit:,.2f} <i>({closed_count} vendas com lucro hoje)</i>\n\n"
            f"⚙️ <b>Resumo das Operações:</b>\n"
            f"• 📈 <b>Moedas em andamento ({open_count}):</b> US$ {invested_usd:,.2f} investidos aguardando meta de lucro\n"
            f"• 💵 <b>Caixa Livre em Conta:</b> US$ {free_cash:,.2f}\n\n"
            f"{withdraw_guide}\n\n"
            f"⏸️ <b>Pausa Programada ({start_hour}h às {end_hour}h):</b> O robô não fará compras nem vendas nesta 1 hora para você sacar com tranquilidade sem bagunçar o saldo."
        )
        return self.send_message(msg)

    @staticmethod
    def _format_withdraw_eligibility(pool: float, end_hour: int) -> str:
        brl_est = pool * 5.80
        if pool >= 10.0:
            return (
                f"✅ <b>Saque Liberado (Acima do mínimo de US$ 10):</b>\n"
                f"Você tem <b>US$ {pool:,.2f}</b> <i>(≈ R$ {brl_est:,.2f})</i> separados para saque!\n"
                f"👉 Se quiser sacar na Binance, faça até as <b>{end_hour}h</b>. Caso não saque até lá, esse valor será somado automaticamente ao capital para investir mais forte amanhã!"
            )
        return (
            f"💸 <b>Reserva de Lucro Hoje:</b> US$ {pool:,.2f} <i>(≈ R$ {brl_est:,.2f})</i>\n"
            f"ℹ️ Como o valor ainda está abaixo do mínimo de saque da Binance (<b>US$ 10.00</b>), às <b>{end_hour}h</b> o robô vai juntar automaticamente esse lucro ao seu capital para render mais no próximo dia!"
        )

    def notify_daily_restart(
        self,
        total_capital: float,
        free_cash: float,
        invested_usd: float,
        open_count: int,
        swept_pool: float = 0.0
    ) -> bool:
        """Notifica a retomada de operações às 23h BRT informando o capital total considerado."""
        reinvest_note = (
            f"• 🔄 <b>Lucro de hoje reinvestido no giro:</b> +US$ {swept_pool:,.2f}\n"
            if swept_pool > 0
            else ""
        )
        msg = (
            f"🚀 <b>CashBot — Iniciando Novo Ciclo Diário!</b>\n\n"
            f"A janela de saque encerrou e o robô voltou a operar considerando o capital disponível na sua conta:\n\n"
            f"💼 <b>Capital Total em Operação:</b> <b>US$ {total_capital:,.2f}</b>\n"
            f"{reinvest_note}"
            f"• 💵 <b>Caixa Livre para Novas Compras:</b> US$ {free_cash:,.2f}\n"
            f"• 📈 <b>Já Investido ({open_count} moedas ativas):</b> US$ {invested_usd:,.2f}\n\n"
            f"<i>Boas operações! Você receberá um aviso a cada compra ou venda realizada.</i>"
        )
        return self.send_message(msg)


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
