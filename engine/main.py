"""
CashBot Engine — Orquestrador do Ciclo Operacional Serverless
Executado pontualmente via GitHub Actions (ou localmente).
"""

import os
import sys
import logging
import argparse
from typing import List, Dict, Any
from dotenv import load_dotenv

# Carrega variáveis de ambiente do .env se existir
load_dotenv()

# Ajusta path para importar módulos do engine
sys.path.append(os.path.dirname(__file__))

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

    def run_cycle(self, force_opportunity: bool = False):
        """Executa um ciclo operacional completo conforme o SDD."""
        logger.info("=== INICIANDO CICLO OPERACIONAL DO CASHBOT ===")
        ledger = self.db.get_ledger()
        trading_balance = ledger["trading_balance"]
        withdrawable_pool = ledger["withdrawable_pool"]
        logger.info(f"Saldos atuais -> Capital de Giro: ${trading_balance:,.2f} | Pool para Saque: ${withdrawable_pool:,.2f}")

        # -------------------------------------------------------------
        # ETAPA 1: Checagem de Ordem Aberta (OCO em andamento)
        # -------------------------------------------------------------
        open_trade = self.db.get_open_trade()
        if open_trade:
            logger.info(f"Trade ativo detectado: #{open_trade['id']} ({open_trade['symbol']}). Verificando status da OCO...")
            check = self.exchange.check_oco_status(
                symbol=open_trade["symbol"],
                order_list_id=open_trade["binance_order_list_id"],
                entry_price=float(open_trade["entry_price"]),
                stop_loss=float(open_trade["stop_loss"]),
                take_profit=float(open_trade["take_profit"])
            )
            status = check["status"]
            exit_price = check["exit_price"]

            if status in ("CLOSED_TP", "CLOSED_SL"):
                entry_price = float(open_trade["entry_price"])
                qty = float(open_trade["quantity"])
                pnl_usd = (exit_price - entry_price) * qty
                
                logger.info(f"Posição fechada com status {status}! PnL: ${pnl_usd:+,.2f}")
                self.db.close_trade(open_trade["id"], exit_price, status, pnl_usd)

                # Gestão contábil dos lucros: 50% de lucro líquido para saque Pix, 50% para giro
                to_withdraw = 0.0
                to_reinvest = 0.0
                if pnl_usd > 0:
                    to_withdraw = pnl_usd * 0.50
                    to_reinvest = pnl_usd * 0.50
                    new_trading_bal = trading_balance + to_reinvest
                    new_withdraw_pool = withdrawable_pool + to_withdraw
                else:
                    new_trading_bal = max(0.0, trading_balance + pnl_usd)
                    new_withdraw_pool = withdrawable_pool

                self.db.update_ledger(new_trading_bal, new_withdraw_pool)

                # Notifica o usuário no celular
                self.notifier.notify_order_closed(
                    symbol=open_trade["symbol"],
                    outcome="TP" if status == "CLOSED_TP" else "SL",
                    entry_price=entry_price,
                    exit_price=exit_price,
                    pnl_usd=pnl_usd,
                    to_withdraw=to_withdraw,
                    to_reinvest=to_reinvest,
                    is_simulated=self.exchange.simulation_mode
                )
                logger.info("Posição encerrada e notificada. Prosseguindo para nova varredura de mercado...")
            else:
                logger.info("Ordem OCO ainda em aberto no livro da exchange. Nenhuma nova ordem será aberta hoje.")
                return

        # -------------------------------------------------------------
        # ETAPA 2: Varredura de Pares e Deliberação do Comitê de IA
        # -------------------------------------------------------------
        deliberations = []
        for symbol in WATCHLIST:
            logger.info(f"Analisando par {symbol}...")
            candles = self.exchange.fetch_daily_candles(symbol, limit=60)
            indicators = self.risk_agent.compute_indicators(candles)

            # Consulta os dois agentes de IA
            tech_res = self.tech_agent.analyze(symbol, indicators)
            sent_res = self.sent_agent.analyze(symbol)

            # Cálculo da nota ponderada
            tech_score = tech_res["score"]
            sent_score = sent_res["score"]
            final_score = (tech_score * TECHNICAL_WEIGHT) + (sent_score * SENTIMENT_WEIGHT)
            veto = tech_res["veto"] or sent_res["veto"]

            if force_opportunity and symbol == "BTC/USDT":
                final_score = 88.5
                veto = False
                tech_score = 90.0
                sent_score = 86.25

            summary_text = f"Técnico ({tech_score:.1f}): {tech_res['reasoning']} | Sentimento ({sent_score:.1f}): {sent_res['reasoning']}"
            
            # Persiste o log no banco de dados
            self.db.save_consensus_log(
                symbol=symbol,
                tech_score=tech_score,
                sent_score=sent_score,
                final_score=final_score,
                veto_applied=veto,
                reasoning_summary=summary_text
            )

            deliberations.append({
                "symbol": symbol,
                "indicators": indicators,
                "tech_score": tech_score,
                "sent_score": sent_score,
                "final_score": final_score,
                "veto": veto,
                "summary": summary_text
            })

            logger.info(f"-> {symbol}: Final Score = {final_score:.1f}/100 | Veto = {veto}")

        # -------------------------------------------------------------
        # ETAPA 3: Decisão de Execução de Ordem
        # -------------------------------------------------------------
        # Filtra candidatos aprovados (Score >= 75 e sem veto)
        valid_candidates = [
            d for d in deliberations 
            if d["final_score"] >= MIN_SCORE_FOR_TRADE and not d["veto"]
        ]

        if not valid_candidates:
            logger.info("Nenhum par atingiu a pontuação mínima de 75 ou houve veto aplicado.")
            # Notifica resumo do dia ao usuário para ele saber que o bot analisou
            best = max(deliberations, key=lambda x: x["final_score"])
            self.notifier.notify_daily_analysis(
                symbol=best["symbol"],
                tech_score=best["tech_score"],
                sent_score=best["sent_score"],
                final_score=best["final_score"],
                veto=best["veto"],
                action="AGUARDAR (Sem Oportunidade Aprovada)",
                details=best["summary"]
            )
            return

        # Escolhe o ativo de maior nota
        best_candidate = max(valid_candidates, key=lambda x: x["final_score"])
        symbol = best_candidate["symbol"]
        entry_price = best_candidate["indicators"]["current_price"]
        atr14 = best_candidate["indicators"]["atr14"]

        # Calcula níveis de SL (1.5x ATR) e TP (2.0x SL)
        stop_loss, take_profit, stop_dist = self.risk_agent.calculate_levels(entry_price, atr14)
        quantity = self.risk_agent.calculate_position_size(trading_balance, entry_price, stop_dist)

        if quantity <= 0:
            logger.warning(f"Quantidade calculada inválida para {symbol} (Saldo insuficiente).")
            return

        logger.info(f"OPORTUNIDADE APROVADA: {symbol} (Score: {best_candidate['final_score']:.1f})")
        logger.info(f"Entrada: ${entry_price} | Qtd: {quantity} | SL: ${stop_loss} | TP: ${take_profit}")

        # Envia ordem de compra e arma OCO
        order_res = self.exchange.create_market_buy_and_oco(symbol, quantity, stop_loss, take_profit)
        
        # Salva no banco de dados
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

        # Envia notificação imediata no celular
        self.notifier.notify_order_placed(
            symbol=symbol,
            entry_price=entry_price,
            qty=quantity,
            sl_price=stop_loss,
            tp_price=take_profit,
            is_simulated=self.exchange.simulation_mode
        )
        logger.info("=== CICLO OPERACIONAL CONCLUÍDO COM SUCESSO ===")

def main():
    parser = argparse.ArgumentParser(description="CashBot Trading Engine")
    parser.add_argument("--simulate", action="store_true", help="Força execução em modo simulação")
    parser.add_argument("--force-buy", action="store_true", help="Força aprovação de compra para teste de ponta a ponta e notificação")
    parser.add_argument("--test-notify", action="store_true", help="Envia mensagem de teste no Telegram")
    args = parser.parse_args()

    if args.test_notify:
        notif = TelegramNotifier()
        if notif.is_configured:
            notif.send_message("🔔 <b>CashBot:</b> Teste de notificação bem-sucedido no seu celular!")
            print("Notificação enviada!")
        else:
            print("Configure TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID no seu .env para receber alertas no celular.")
        return

    engine = TradingEngine(force_simulation=args.simulate)
    engine.run_cycle(force_opportunity=args.force_buy)

if __name__ == "__main__":
    main()

