"""
CashBot Engine — Orquestrador do Ciclo Operacional Serverless
Executado pontualmente via GitHub Actions (ou localmente).
Segue Object Calisthenics (métodos curtos, 1 nível de indentação, sem else) e zero N+1.
"""

import os
import sys
import logging
import argparse
from typing import List, Dict, Any, Optional, Tuple
from dotenv import load_dotenv

load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

sys.path.append(os.path.dirname(__file__))

from domain import TechnicalIndicators, Deliberation
from database import Database
from exchange import ExchangeClient
from agents.technical import TechnicalAgent
from agents.sentiment import SentimentAgent
from agents.risk import RiskAgent
from notifier import TelegramNotifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("cashbot.main")

WATCHLIST = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
MAX_DYNAMIC_PAIRS = 6
MIN_SCORE_FOR_TRADE = 65.0
TECHNICAL_WEIGHT = 0.60
SENTIMENT_WEIGHT = 0.40


class TradingEngine:
    def __init__(self, force_simulation: bool = False):
        self.db = Database()
        self.notifier = TelegramNotifier()
        self.tech_agent = TechnicalAgent()
        self.sent_agent = SentimentAgent()
        self.risk_agent = RiskAgent()
        self.exchange = ExchangeClient(simulation_mode=force_simulation)

    def run_cycle(self, force_opportunity: bool = False, bypass_cooldown: bool = False) -> None:
        """Executa um ciclo operacional completo conforme o SDD."""
        logger.info("=== INICIANDO CICLO OPERACIONAL DO CASHBOT ===")
        ledger = self.db.get_ledger()
        logger.info(
            f"Saldos atuais -> Capital de Giro: ${ledger['trading_balance']:,.2f} | "
            f"Pool para Saque: ${ledger['withdrawable_pool']:,.2f}"
        )

        open_trades = self.db.get_open_trades()
        self._check_all_open_trades(open_trades)

        remaining_open = self.db.get_open_trades()
        updated_ledger = self.db.get_ledger()
        free_capital = self._compute_free_capital(updated_ledger, remaining_open)

        if len(remaining_open) >= 3 or free_capital < 12.0:
            logger.info(
                f"Carteira com {len(remaining_open)} posição(ões) ativa(s) e "
                f"${free_capital:,.2f} livre. Monitoramento de Take Profit concluído."
            )
            return

        if not (force_opportunity or bypass_cooldown) and self.db.has_recent_consensus(minutes=45):
            logger.info(
                "Take Profit checado em todas as posições. "
                "Comitê de IA já deliberou nos últimos 45 min — poupando cota gratuita."
            )
            return

        deliberations = self._evaluate_watchlist(force_opportunity)
        self.db.save_consensus_logs_batch([d.to_dict() for d in deliberations])

        self._decide_and_execute(deliberations, updated_ledger, remaining_open)

    def _check_all_open_trades(self, open_trades: List[Dict[str, Any]]) -> None:
        """Verifica todas as ordens OCO abertas na carteira e encerra quantas tiverem atingido TP ou SL."""
        for trade in open_trades:
            current_ledger = self.db.get_ledger()
            self._try_settle_open_trade(trade, current_ledger)

    @staticmethod
    def _compute_free_capital(ledger: Dict[str, float], open_trades: List[Dict[str, Any]]) -> float:
        total_available = ledger["trading_balance"] + ledger["withdrawable_pool"]
        locked_usd = sum(float(t["entry_price"]) * float(t["quantity"]) for t in open_trades)
        return max(0.0, round(total_available - locked_usd, 2))

    def _try_settle_open_trade(self, open_trade: Dict[str, Any], ledger: Dict[str, float]) -> bool:
        """
        Verifica se a ordem OCO aberta já atingiu TP ou SL.
        Retorna True se a posição foi encerrada (liberando nova varredura), ou False se segue aberta.
        """
        logger.info(f"Trade ativo detectado: #{open_trade['id']} ({open_trade['symbol']}). Verificando status da OCO...")
        check = self.exchange.check_oco_status(
            symbol=open_trade["symbol"],
            order_list_id=open_trade["binance_order_list_id"],
            entry_price=float(open_trade["entry_price"]),
            stop_loss=float(open_trade["stop_loss"]),
            take_profit=float(open_trade["take_profit"])
        )
        status = check["status"]
        if status not in ("CLOSED_TP", "CLOSED_SL"):
            return False

        self._settle_closed_position(open_trade, status, float(check["exit_price"]), ledger)
        return True

    def _settle_closed_position(
        self,
        open_trade: Dict[str, Any],
        status: str,
        exit_price: float,
        ledger: Dict[str, float]
    ) -> None:
        entry_price = float(open_trade["entry_price"])
        qty = float(open_trade["quantity"])
        pnl_usd = (exit_price - entry_price) * qty

        logger.info(f"Posição fechada com status {status}! PnL: ${pnl_usd:+,.2f}")
        self.db.close_trade(open_trade["id"], exit_price, status, pnl_usd)

        new_trading, new_pool, to_withdraw, to_reinvest = self.risk_agent.allocate_trade_pnl(
            trading_balance=ledger["trading_balance"],
            withdrawable_pool=ledger["withdrawable_pool"],
            pnl_usd=pnl_usd,
        )
        self.db.update_ledger(new_trading, new_pool)

        outcome = "TP" if status == "CLOSED_TP" else "SL"
        self.notifier.notify_order_closed(
            symbol=open_trade["symbol"],
            outcome=outcome,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl_usd=pnl_usd,
            to_withdraw=to_withdraw,
            to_reinvest=to_reinvest,
            is_simulated=self.exchange.simulation_mode,
            new_trading_balance=new_trading,
            new_withdrawable_pool=new_pool,
        )
        logger.info("Posição encerrada e notificada. Prosseguindo para nova varredura de mercado...")

    def _evaluate_watchlist(self, force_opportunity: bool) -> List[Deliberation]:
        """Descobre a Watchlist Dinâmica na Binance, pré-carrega notícias em lote e delibera."""
        dynamic_pairs = self.exchange.discover_dynamic_watchlist(max_pairs=MAX_DYNAMIC_PAIRS)
        self.sent_agent.prefetch_market_context(dynamic_pairs)
        return [self._deliberate_symbol(symbol, force_opportunity) for symbol in dynamic_pairs]

    def _deliberate_symbol(self, symbol: str, force_opportunity: bool) -> Deliberation:
        logger.info(f"Analisando par {symbol}...")
        candles = self.exchange.fetch_daily_candles(symbol, limit=250)
        raw_ind = self.risk_agent.compute_indicators(candles)
        indicators = TechnicalIndicators(**raw_ind)

        tech_res = self.tech_agent.analyze(symbol, raw_ind)
        sent_res = self.sent_agent.analyze(symbol)

        tech_score, sent_score, final_score, veto = self._compute_consensus_scores(
            symbol, tech_res, sent_res, force_opportunity
        )
        summary_text = (
            f"Técnico ({tech_score:.1f}): {tech_res['reasoning']} | "
            f"Sentimento ({sent_score:.1f}): {sent_res['reasoning']}"
        )
        logger.info(f"-> {symbol}: Final Score = {final_score:.1f}/100 | Veto = {veto}")

        return Deliberation(
            symbol=symbol,
            indicators=indicators,
            tech_score=tech_score,
            sent_score=sent_score,
            final_score=final_score,
            veto=veto,
            summary=summary_text,
            tech_reason=str(tech_res["reasoning"]),
            sent_reason=str(sent_res["reasoning"]),
            ai_stop_loss_pct=float(tech_res.get("stop_loss_pct", 0.0)),
            ai_take_profit_pct=float(tech_res.get("take_profit_pct", 0.0)),
        )

    @staticmethod
    def _compute_consensus_scores(
        symbol: str,
        tech_res: Dict[str, Any],
        sent_res: Dict[str, Any],
        force_opportunity: bool
    ) -> Tuple[float, float, float, bool]:
        if force_opportunity and symbol == "BTC/USDT":
            return 90.0, 86.25, 88.5, False

        tech_score = float(tech_res["score"])
        sent_score = float(sent_res["score"])
        final_score = (tech_score * TECHNICAL_WEIGHT) + (sent_score * SENTIMENT_WEIGHT)
        veto = bool(tech_res["veto"] or sent_res["veto"])
        return tech_score, sent_score, final_score, veto

    def _decide_and_execute(
        self,
        deliberations: List[Deliberation],
        ledger: Dict[str, float],
        open_trades: List[Dict[str, Any]]
    ) -> None:
        open_symbols = {str(t["symbol"]) for t in open_trades}
        valid_candidates = [
            d for d in deliberations
            if d.is_approved(MIN_SCORE_FOR_TRADE) and d.symbol not in open_symbols
        ]
        if not valid_candidates:
            self._notify_no_opportunity(deliberations, ledger)
            return

        ranked_candidates = sorted(valid_candidates, key=lambda x: x.final_score, reverse=True)
        total_capital = self._reinvest_unwithdrawn_pool(ledger)
        locked_usd = sum(float(t["entry_price"]) * float(t["quantity"]) for t in open_trades)
        free_capital = max(0.0, round(total_capital - locked_usd, 2))

        allocations = self.risk_agent.split_capital_for_candidates(
            free_balance=free_capital,
            scores=[c.final_score for c in ranked_candidates],
            open_positions_count=len(open_trades),
        )
        for candidate, allocated_usd in zip(ranked_candidates, allocations):
            self._open_position_for_candidate(candidate, deliberations, allocated_usd)

    def _reinvest_unwithdrawn_pool(self, ledger: Dict[str, float]) -> float:
        """
        Se o usuário não sacou o valor sugerido até a próxima oportunidade de compra,
        reincorpora o saldo disponível ao Capital de Giro para maximizar os juros compostos.
        """
        combined_ledger_usd = round(ledger["trading_balance"] + ledger["withdrawable_pool"], 2)
        effective_usd = self.exchange.fetch_free_usdt_balance(combined_ledger_usd)

        if ledger["withdrawable_pool"] > 0:
            logger.info(
                f"Reinvestindo saldo não sacado (${ledger['withdrawable_pool']:,.2f}) "
                f"no Capital de Giro -> Força Total: ${effective_usd:,.2f}"
            )
            self.db.update_ledger(effective_usd, 0.0)

        return effective_usd

    def _notify_no_opportunity(self, deliberations: List[Deliberation], ledger: Dict[str, float]) -> None:
        logger.info(f"Nenhum par atingiu a pontuação mínima de {MIN_SCORE_FOR_TRADE} ou houve veto aplicado.")
        ranked = sorted(deliberations, key=lambda x: x.final_score, reverse=True)
        best = ranked[0]
        ranking_lines = [self._format_coin_rank_line(d) for d in ranked]
        self.notifier.notify_daily_analysis(
            symbol=best.symbol,
            tech_score=best.tech_score,
            sent_score=best.sent_score,
            final_score=best.final_score,
            veto=best.veto,
            action="AGUARDAR",
            details=best.summary,
            ranking_lines=ranking_lines,
            tech_reason=best.tech_reason,
            sent_reason=best.sent_reason,
            trading_balance=ledger["trading_balance"],
            withdrawable_pool=ledger["withdrawable_pool"],
        )

    @staticmethod
    def _format_coin_rank_line(d: Deliberation) -> str:
        coin = d.symbol.split("/")[0]
        veto_tag = " 🚫 <i>(Risco alto)</i>" if d.veto else ""
        return f"• <b>{coin}:</b> {d.final_score:.0f}/100 pts{veto_tag}"

    def _open_position_for_candidate(
        self,
        candidate: Deliberation,
        deliberations: List[Deliberation],
        trading_balance: float
    ) -> None:
        symbol = candidate.symbol
        entry_price = candidate.indicators.current_price
        atr14 = candidate.indicators.atr14

        stop_loss, take_profit, stop_dist = self.risk_agent.calculate_levels(
            entry_price=entry_price,
            atr14=atr14,
            ai_stop_pct=candidate.ai_stop_loss_pct,
            ai_tp_pct=candidate.ai_take_profit_pct,
        )
        quantity = self.risk_agent.calculate_position_size(trading_balance, entry_price, stop_dist)
        if quantity <= 0:
            logger.warning(f"Quantidade calculada inválida para {symbol} (Saldo insuficiente).")
            return

        logger.info(f"OPORTUNIDADE APROVADA: {symbol} (Score: {candidate.final_score:.1f})")
        logger.info(f"Entrada: ${entry_price} | Qtd: {quantity} | SL: ${stop_loss} | TP: ${take_profit}")

        order_res = self.exchange.create_market_buy_and_oco(symbol, quantity, stop_loss, take_profit)
        trade_id = self.db.save_trade(
            symbol=symbol,
            entry_price=entry_price,
            qty=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            binance_order_list_id=order_res.get("order_list_id"),
            status="OPEN_OCO"
        )
        logger.info(f"Trade registrado no banco com ID #{trade_id}.")

        ranked = sorted(deliberations, key=lambda x: x.final_score, reverse=True)
        ranking_lines = [self._format_coin_rank_line(d) for d in ranked]
        self.notifier.notify_order_placed(
            symbol=symbol,
            entry_price=entry_price,
            qty=quantity,
            sl_price=stop_loss,
            tp_price=take_profit,
            is_simulated=self.exchange.simulation_mode,
            ranking_lines=ranking_lines,
            tech_reason=candidate.tech_reason,
            sent_reason=candidate.sent_reason,
        )
        logger.info("=== CICLO OPERACIONAL CONCLUÍDO COM SUCESSO ===")


def _handle_test_notify() -> None:
    notif = TelegramNotifier()
    if not notif.is_configured:
        print("Configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no seu .env para receber alertas no celular.")
        return
    notif.send_message("🔔 <b>CashBot:</b> Teste de notificação bem-sucedido no seu celular!")
    print("Notificação enviada!")


def main() -> None:
    parser = argparse.ArgumentParser(description="CashBot Trading Engine")
    parser.add_argument("--simulate", action="store_true", help="Força execução em modo simulação")
    parser.add_argument("--force-buy", action="store_true", help="Força aprovação de compra para teste de ponta a ponta e notificação")
    parser.add_argument("--test-notify", action="store_true", help="Envia mensagem de teste no Telegram")
    args = parser.parse_args()

    if args.test_notify:
        _handle_test_notify()
        return

    is_manual = os.getenv("GITHUB_EVENT_NAME", "") != "schedule"
    engine = TradingEngine(force_simulation=args.simulate)
    engine.run_cycle(force_opportunity=args.force_buy, bypass_cooldown=is_manual)


if __name__ == "__main__":
    main()
