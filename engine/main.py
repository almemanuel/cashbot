"""
CashBot Engine — Orquestrador do Ciclo Operacional Serverless
Executado pontualmente via GitHub Actions (ou localmente).
Segue Object Calisthenics (métodos curtos, 1 nível de indentação, sem else) e zero N+1.
"""

import os
import sys
import logging
import argparse
from datetime import datetime, timezone, timedelta
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
MAX_OPEN_SLOTS = 4
MIN_SCORE_FOR_TRADE = 63.0
TACTICAL_PROFIT_MIN_PCT = 0.35
TACTICAL_HOLD_MINUTES = 45.0
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
        """Executa um ciclo completo de Day Trade Quantitativo (15m) com IA sempre ativa."""
        logger.info("=== INICIANDO CICLO DAY TRADE QUANTITATIVO (15M) ===")
        ledger = self.db.get_ledger()
        logger.info(
            f"Saldos atuais -> Capital de Giro: ${ledger['trading_balance']:,.2f} | "
            f"Pool para Saque: ${ledger['withdrawable_pool']:,.2f}"
        )

        open_trades = self.db.get_open_trades()
        deliberations = self._evaluate_watchlist(force_opportunity, open_trades)
        self.db.save_consensus_logs_batch([d.to_dict() for d in deliberations])

        self._check_all_open_trades(open_trades, deliberations)

        remaining_open = self.db.get_open_trades()
        updated_ledger = self._reconcile_exchange_cash_flow(self.db.get_ledger(), remaining_open)
        free_capital = self._compute_free_capital(updated_ledger, remaining_open)

        if len(remaining_open) >= MAX_OPEN_SLOTS or free_capital < 12.0:
            logger.info(
                f"Carteira com {len(remaining_open)}/{MAX_OPEN_SLOTS} posições ativas e "
                f"${free_capital:,.2f} livre. Comitê de IA registrado e posições monitoradas."
            )
            return

        self._decide_and_execute(deliberations, updated_ledger, remaining_open, notify_wait=bypass_cooldown)

    def _check_all_open_trades(
        self,
        open_trades: List[Dict[str, Any]],
        deliberations: List[Deliberation]
    ) -> None:
        """Avalia saída no Take Profit ou realização tática de lucro curto assistida por IA."""
        delib_map = {d.symbol: d for d in deliberations}
        for trade in open_trades:
            current_ledger = self.db.get_ledger()
            self._try_settle_open_trade(trade, current_ledger, delib_map.get(str(trade["symbol"])))

    def _reconcile_exchange_cash_flow(
        self,
        ledger: Dict[str, float],
        open_trades: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """
        Detecta automaticamente aportes/saques na Binance e aplica a regra da Janela Diária de Saque:
        - Antes das 23h BRT (WITHDRAW_WINDOW_END_BRT), mantém o Pool de Saque reservado para o usuário.
        - Passou das 23h BRT, reincorpora o Pool de Saque não utilizado ao Capital de Giro!
        """
        ledger = self._sweep_expired_withdraw_pool(ledger)
        locked_usd = sum(float(t["entry_price"]) * float(t["quantity"]) for t in open_trades)
        expected_free = max(0.0, round(ledger["trading_balance"] + ledger["withdrawable_pool"] - locked_usd, 2))
        actual_free = round(self.exchange.fetch_free_usdt_balance(expected_free), 2)
        diff = round(actual_free - expected_free, 2)

        if abs(diff) <= 0.05:
            return ledger

        return self._apply_cash_flow_diff(ledger, locked_usd, actual_free, diff)

    def _sweep_expired_withdraw_pool(self, ledger: Dict[str, float]) -> Dict[str, float]:
        pool = float(ledger.get("withdrawable_pool", 0.0))
        if pool <= 0 or not self._is_past_withdraw_window_brt():
            return ledger

        new_trading = round(float(ledger["trading_balance"]) + pool, 2)
        logger.info(
            f"Janela de saque encerrada (pós-{self._withdraw_end_hour_brt()}h BRT): "
            f"Reinvestindo ${pool:,.2f} não sacados no Capital de Giro -> ${new_trading:,.2f}"
        )
        self.db.update_ledger(new_trading, 0.0)
        return {"trading_balance": new_trading, "withdrawable_pool": 0.0}

    @staticmethod
    def _withdraw_end_hour_brt() -> int:
        return int(os.getenv("WITHDRAW_WINDOW_END_BRT", "23"))

    @classmethod
    def _is_past_withdraw_window_brt(cls) -> bool:
        brt_now = datetime.now(timezone.utc) - timedelta(hours=3)
        return brt_now.hour >= cls._withdraw_end_hour_brt()

    def _apply_cash_flow_diff(
        self,
        ledger: Dict[str, float],
        locked_usd: float,
        actual_free: float,
        diff: float
    ) -> Dict[str, float]:
        if diff > 0:
            new_trading = round(ledger["trading_balance"] + diff, 2)
            new_pool = round(ledger["withdrawable_pool"], 2)
            logger.info(f"Novo aporte detectado na Binance (+${diff:,.2f})! Capital de Giro: ${new_trading:,.2f}")
            self.db.update_ledger(new_trading, new_pool)
            return {"trading_balance": new_trading, "withdrawable_pool": new_pool}

        withdrawn = abs(diff)
        new_pool = max(0.0, round(ledger["withdrawable_pool"] - withdrawn, 2))
        new_trading = max(0.0, round(locked_usd + actual_free - new_pool, 2))
        logger.info(f"Saque detectado na Binance (-${withdrawn:,.2f})! Saldo sincronizado.")
        self.db.update_ledger(new_trading, new_pool)
        return {"trading_balance": new_trading, "withdrawable_pool": new_pool}

    @staticmethod
    def _compute_free_capital(ledger: Dict[str, float], open_trades: List[Dict[str, Any]]) -> float:
        locked_usd = sum(float(t["entry_price"]) * float(t["quantity"]) for t in open_trades)
        return max(0.0, round(ledger["trading_balance"] - locked_usd, 2))

    def _try_settle_open_trade(
        self,
        open_trade: Dict[str, Any],
        ledger: Dict[str, float],
        delib: Optional[Deliberation] = None
    ) -> bool:
        """
        Verifica se a posição atingiu o Take Profit ou gatilho de Realização Tática no Lucro.
        Mesmo ao bater no ponto de venda, avalia se a tendência de alta segue forte para surfar mais rodadas!
        """
        entry_price = float(open_trade["entry_price"])
        take_profit = self._ensure_daytrade_take_profit(open_trade, entry_price)

        logger.info(f"Trade ativo #{open_trade['id']} ({open_trade['symbol']}): Entrada=${entry_price} | Alvo=${take_profit}")
        check = self.exchange.check_oco_status(
            symbol=open_trade["symbol"],
            order_list_id=open_trade["binance_order_list_id"],
            entry_price=entry_price,
            stop_loss=float(open_trade["stop_loss"]),
            take_profit=take_profit
        )
        status = check["status"]
        current_price = float(check.get("current_price") or entry_price)

        if status == "CLOSED_TP":
            if self._should_ride_strong_uptrend(open_trade, current_price, delib):
                return False
            self._settle_closed_position(open_trade, "CLOSED_TP", float(check["exit_price"]), ledger)
            return True

        if self._should_lock_tactical_profit(open_trade, entry_price, current_price, delib):
            if self._should_ride_strong_uptrend(open_trade, current_price, delib):
                return False
            logger.info(f"Realização Tática de Day Trade acionada para {open_trade['symbol']} a ${current_price}!")
            self._settle_closed_position(open_trade, "CLOSED_TP", current_price, ledger)
            return True

        return False

    def _should_ride_strong_uptrend(
        self,
        open_trade: Dict[str, Any],
        current_price: float,
        delib: Optional[Deliberation]
    ) -> bool:
        """
        Se o ativo bateu no ponto de venda mas a tendência de alta continua forte (IA >= 68,
        Preço > EMA20 > EMA50, acima da VWAP e RSI < 68 sem exaustão), sobe o alvo (+0.8%)
        e aguarda mais rodadas para maximizar o lucro!
        """
        if delib is None or delib.veto or delib.final_score < 68.0:
            return False
        ind = delib.indicators
        if not (ind.is_strong_uptrend and ind.is_above_vwap and ind.rsi14 < 68.0):
            return False

        new_tp = round(current_price * 1.008, 6 if current_price < 1.0 else 4)
        self.db.update_trade_take_profit(int(open_trade["id"]), new_tp)
        logger.info(
            f"Tendência de alta forte em {open_trade['symbol']} (Score {delib.final_score:.1f}, RSI {ind.rsi14:.1f})! "
            f"Segurando venda e subindo Take Profit para ${new_tp} (+0.8%)."
        )
        return True

    def _ensure_daytrade_take_profit(self, open_trade: Dict[str, Any], entry_price: float) -> float:
        current_tp = float(open_trade["take_profit"])
        if entry_price <= 0:
            return current_tp
        tp_pct = ((current_tp - entry_price) / entry_price) * 100.0
        if tp_pct <= 2.25:
            return current_tp

        new_tp = round(entry_price * 1.012, 6 if entry_price < 1.0 else 4)
        self.db.update_trade_take_profit(int(open_trade["id"]), new_tp)
        logger.info(
            f"Alvo antigo de Swing Trade ({tp_pct:.1f}%) recalibrado para Day Trade (+1.2% -> ${new_tp}) "
            f"em {open_trade['symbol']}."
        )
        return new_tp

    def _should_lock_tactical_profit(
        self,
        open_trade: Dict[str, Any],
        entry_price: float,
        current_price: float,
        delib: Optional[Deliberation]
    ) -> bool:
        if entry_price <= 0 or current_price <= entry_price:
            return False
        unrealized_pct = ((current_price - entry_price) / entry_price) * 100.0
        if unrealized_pct < TACTICAL_PROFIT_MIN_PCT:
            return False

        age_minutes = self._compute_trade_age_minutes(open_trade.get("created_at"))
        ai_weakening = delib is not None and (delib.final_score < 58.0 or delib.indicators.rsi14 > 68.0)
        return age_minutes >= TACTICAL_HOLD_MINUTES or ai_weakening

    @staticmethod
    def _compute_trade_age_minutes(created_at: Any) -> float:
        if not created_at:
            return 0.0
        if isinstance(created_at, datetime):
            dt = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 60.0)
        try:
            raw = str(created_at).strip().replace(" ", "T")
            iso = raw if ("+" in raw or raw.endswith("Z")) else f"{raw}+00:00"
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 60.0)
        except Exception:
            return 0.0

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

    def _evaluate_watchlist(
        self,
        force_opportunity: bool,
        open_trades: Optional[List[Dict[str, Any]]] = None
    ) -> List[Deliberation]:
        """Descobre a Watchlist Dinâmica na Binance + ativos abertos, pré-carrega notícias e delibera."""
        dynamic_pairs = self.exchange.discover_dynamic_watchlist(max_pairs=MAX_DYNAMIC_PAIRS)
        open_symbols = [str(t["symbol"]) for t in (open_trades or [])]
        all_pairs = list(dict.fromkeys(dynamic_pairs + open_symbols))
        self.sent_agent.prefetch_market_context(all_pairs)
        return [self._deliberate_symbol(symbol, force_opportunity) for symbol in all_pairs]

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
        open_trades: List[Dict[str, Any]],
        notify_wait: bool = False
    ) -> None:
        open_symbols = {str(t["symbol"]) for t in open_trades}
        valid_candidates = [
            d for d in deliberations
            if d.is_approved(MIN_SCORE_FOR_TRADE) and d.symbol not in open_symbols
        ]
        if not valid_candidates:
            if notify_wait:
                self._notify_no_opportunity(deliberations, ledger)
            return

        ranked_candidates = sorted(valid_candidates, key=lambda x: x.final_score, reverse=True)
        locked_usd = sum(float(t["entry_price"]) * float(t["quantity"]) for t in open_trades)
        free_capital = self._sync_free_balance_before_orders(ledger, locked_usd)

        allocations = self.risk_agent.split_capital_for_candidates(
            free_balance=free_capital,
            scores=[c.final_score for c in ranked_candidates],
            open_positions_count=len(open_trades),
        )
        for candidate, allocated_usd in zip(ranked_candidates, allocations):
            self._open_position_for_candidate(candidate, deliberations, allocated_usd)

    def _sync_free_balance_before_orders(self, ledger: Dict[str, float], locked_usd: float) -> float:
        """
        Calcula o saldo livre para novas compras preservando o Pool de Saque durante o dia
        (antes das 23h BRT). Apenas após as 23h BRT o Pool não sacado volta para o giro.
        """
        ledger = self._sweep_expired_withdraw_pool(ledger)
        return max(0.0, round(ledger["trading_balance"] - locked_usd, 2))

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
