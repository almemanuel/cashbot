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
MIN_SCORE_FOR_TRADE = 75.0
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

    def run_cycle(self, force_opportunity: bool = False) -> None:
        """Executa um ciclo operacional completo conforme o SDD."""
        logger.info("=== INICIANDO CICLO OPERACIONAL DO CASHBOT ===")
        ledger = self.db.get_ledger()
        logger.info(
            f"Saldos atuais -> Capital de Giro: ${ledger['trading_balance']:,.2f} | "
            f"Pool para Saque: ${ledger['withdrawable_pool']:,.2f}"
        )

        open_trade = self.db.get_open_trade()
        if open_trade and not self._try_settle_open_trade(open_trade, ledger):
            logger.info("Ordem OCO ainda em aberto no livro da exchange. Nenhuma nova ordem será aberta hoje.")
            return

        updated_ledger = self.db.get_ledger()
        deliberations = self._evaluate_watchlist(force_opportunity)
        self.db.save_consensus_logs_batch([d.to_dict() for d in deliberations])

        self._decide_and_execute(deliberations, updated_ledger["trading_balance"])

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

        to_withdraw, to_reinvest = self._split_profit(pnl_usd)
        new_trading, new_pool = self._calculate_updated_balances(ledger, pnl_usd, to_withdraw, to_reinvest)
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
            is_simulated=self.exchange.simulation_mode
        )
        logger.info("Posição encerrada e notificada. Prosseguindo para nova varredura de mercado...")

    @staticmethod
    def _split_profit(pnl_usd: float) -> Tuple[float, float]:
        if pnl_usd <= 0:
            return 0.0, 0.0
        half = pnl_usd * 0.50
        return half, half

    @staticmethod
    def _calculate_updated_balances(
        ledger: Dict[str, float],
        pnl_usd: float,
        to_withdraw: float,
        to_reinvest: float
    ) -> Tuple[float, float]:
        trading_balance = ledger["trading_balance"]
        withdrawable_pool = ledger["withdrawable_pool"]
        if pnl_usd > 0:
            return trading_balance + to_reinvest, withdrawable_pool + to_withdraw
        return max(0.0, trading_balance + pnl_usd), withdrawable_pool

    def _evaluate_watchlist(self, force_opportunity: bool) -> List[Deliberation]:
        """Pré-carrega contexto de mercado em lote (sem N+1) e delibera sobre cada ativo."""
        self.sent_agent.prefetch_market_context(WATCHLIST)
        return [self._deliberate_symbol(symbol, force_opportunity) for symbol in WATCHLIST]

    def _deliberate_symbol(self, symbol: str, force_opportunity: bool) -> Deliberation:
        logger.info(f"Analisando par {symbol}...")
        candles = self.exchange.fetch_daily_candles(symbol, limit=60)
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
            summary=summary_text
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

    def _decide_and_execute(self, deliberations: List[Deliberation], trading_balance: float) -> None:
        valid_candidates = [d for d in deliberations if d.is_approved(MIN_SCORE_FOR_TRADE)]
        if not valid_candidates:
            self._notify_no_opportunity(deliberations)
            return

        best_candidate = max(valid_candidates, key=lambda x: x.final_score)
        self._open_position_for_candidate(best_candidate, trading_balance)

    def _notify_no_opportunity(self, deliberations: List[Deliberation]) -> None:
        logger.info("Nenhum par atingiu a pontuação mínima de 75 ou houve veto aplicado.")
        best = max(deliberations, key=lambda x: x.final_score)
        self.notifier.notify_daily_analysis(
            symbol=best.symbol,
            tech_score=best.tech_score,
            sent_score=best.sent_score,
            final_score=best.final_score,
            veto=best.veto,
            action="AGUARDAR (Sem Oportunidade Aprovada)",
            details=best.summary
        )

    def _open_position_for_candidate(self, candidate: Deliberation, trading_balance: float) -> None:
        symbol = candidate.symbol
        entry_price = candidate.indicators.current_price
        atr14 = candidate.indicators.atr14

        stop_loss, take_profit, stop_dist = self.risk_agent.calculate_levels(entry_price, atr14)
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

        self.notifier.notify_order_placed(
            symbol=symbol,
            entry_price=entry_price,
            qty=quantity,
            sl_price=stop_loss,
            tp_price=take_profit,
            is_simulated=self.exchange.simulation_mode
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

    engine = TradingEngine(force_simulation=args.simulate)
    engine.run_cycle(force_opportunity=args.force_buy)


if __name__ == "__main__":
    main()
