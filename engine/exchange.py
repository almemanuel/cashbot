"""
Cliente de Exchange para Binance Spot Testnet com fallback para Simulação Completa.
Suporta CCXT ou requisições REST diretas da Binance Testnet.
"""

import os
import time
import logging
import random
from typing import List, Dict, Any, Optional

logger = logging.getLogger("cashbot.exchange")

# Importa ccxt caso disponível
try:
    import ccxt
    HAS_CCXT = True
except ImportError:
    HAS_CCXT = False

import requests

BINANCE_TESTNET_BASE = "https://testnet.binance.vision"

class ExchangeClient:
    def __init__(self, api_key: Optional[str] = None, secret_key: Optional[str] = None, simulation_mode: bool = True):
        self.api_key = api_key or os.getenv("BINANCE_TESTNET_API_KEY")
        self.secret_key = secret_key or os.getenv("BINANCE_TESTNET_SECRET_KEY")
        
        env_sim = os.getenv("SIMULATION_MODE", "True").lower() in ("true", "1", "yes")
        self.simulation_mode = simulation_mode or env_sim or not (self.api_key and self.secret_key)
        
        self.exchange = None
        if HAS_CCXT and self.api_key and self.secret_key:
            try:
                self.exchange = ccxt.binance({
                    'apiKey': self.api_key,
                    'secret': self.secret_key,
                    'options': {'defaultType': 'spot'},
                    'enableRateLimit': True,
                })
                self.exchange.set_sandbox_mode(True)
            except Exception as e:
                logger.warning(f"Erro ao inicializar CCXT sandbox: {e}. Entrando em modo simulado.")
                self.simulation_mode = True

    def fetch_daily_candles(self, symbol: str, limit: int = 60) -> List[Dict[str, float]]:
        """
        Coleta os últimos candles diários (1d).
        Retorna lista de dicts com 'open', 'high', 'low', 'close', 'volume'.
        """
        # Formata símbolo (ex: BTC/USDT -> BTCUSDT para Binance REST)
        clean_symbol = symbol.replace("/", "").upper()
        
        # Tenta endpoint público da Binance (mesmo na simulação podemos ler dados reais de mercado)
        try:
            url = f"https://api.binance.com/api/v3/klines?symbol={clean_symbol}&interval=1d&limit={limit}"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                candles = []
                for item in data:
                    candles.append({
                        "open": float(item[1]),
                        "high": float(item[2]),
                        "low": float(item[3]),
                        "close": float(item[4]),
                        "volume": float(item[5]),
                    })
                return candles
        except Exception as e:
            logger.warning(f"Falha ao consultar klines da Binance para {symbol}: {e}. Gerando candles de simulação.")

        # Gerador sintético realista caso sem internet
        base_prices = {"BTC/USDT": 92000.0, "ETH/USDT": 3400.0, "SOL/USDT": 185.0}
        current = base_prices.get(symbol, 100.0)
        candles = []
        for _ in range(limit):
            variation = random.uniform(-0.02, 0.025)
            open_p = current
            close_p = open_p * (1.0 + variation)
            high_p = max(open_p, close_p) * (1.0 + random.uniform(0.002, 0.015))
            low_p = min(open_p, close_p) * (1.0 - random.uniform(0.002, 0.015))
            current = close_p
            candles.append({
                "open": round(open_p, 4),
                "high": round(high_p, 4),
                "low": round(low_p, 4),
                "close": round(close_p, 4),
                "volume": round(random.uniform(500, 3000), 2)
            })
        return candles

    def create_market_buy_and_oco(self, symbol: str, quantity: float, stop_loss: float, take_profit: float) -> Dict[str, Any]:
        """
        Submete ordem de compra a mercado e imediatamente submete ordem OCO vinculada.
        No modo simulação, gera IDs virtuais com status verificado.
        """
        if self.simulation_mode or not self.exchange:
            logger.info(f"[SIMULAÇÃO] Compra a mercado executada para {symbol}. Qtd: {quantity}")
            logger.info(f"[SIMULAÇÃO] Ordem OCO armada: Stop Loss em ${stop_loss}, Take Profit em ${take_profit}")
            fake_order_id = int(time.time() * 1000)
            return {
                "order_list_id": fake_order_id,
                "status": "OPEN_OCO",
                "simulated": True
            }

        try:
            # 1. Compra a mercado
            market_order = self.exchange.create_market_buy_order(symbol, quantity)
            logger.info(f"Compra a mercado executada na Testnet: {market_order.get('id')}")

            # 2. Ordem OCO de saída
            # ccxt create_order com params OCO ou chamada direta
            oco_params = {
                'stopPrice': self.exchange.price_to_precision(symbol, stop_loss),
                'stopLimitPrice': self.exchange.price_to_precision(symbol, stop_loss * 0.998),
                'stopLimitTimeInForce': 'GTC'
            }
            oco_order = self.exchange.create_order(
                symbol=symbol,
                type='limit',
                side='sell',
                amount=quantity,
                price=take_profit,
                params=oco_params
            )
            order_list_id = oco_order.get('orderListId') or oco_order.get('id')
            return {
                "order_list_id": order_list_id,
                "status": "OPEN_OCO",
                "simulated": False
            }
        except Exception as e:
            logger.error(f"Erro ao submeter ordens na Binance Testnet: {e}. Efetuando fallback para simulação.")
            return {
                "order_list_id": int(time.time() * 1000),
                "status": "OPEN_OCO",
                "simulated": True
            }

    def check_oco_status(self, symbol: str, order_list_id: int, entry_price: float, stop_loss: float, take_profit: float) -> Dict[str, Any]:
        """
        Verifica o estado da ordem OCO.
        Retorna status: 'OPEN_OCO', 'CLOSED_TP', 'CLOSED_SL'.
        """
        # No modo de simulação, consulta o preço atual do ativo
        candles = self.fetch_daily_candles(symbol, limit=1)
        current_price = candles[-1]["close"] if candles else entry_price

        if self.simulation_mode or not self.exchange:
            if current_price >= take_profit:
                return {"status": "CLOSED_TP", "exit_price": take_profit}
            elif current_price <= stop_loss:
                return {"status": "CLOSED_SL", "exit_price": stop_loss}
            else:
                return {"status": "OPEN_OCO", "exit_price": None}

        # Na testnet real
        try:
            orders = self.exchange.fetch_open_orders(symbol)
            matching = [o for o in orders if str(o.get('orderListId', '')) == str(order_list_id)]
            if not matching:
                # Ambas as pontas saíram dos abertos -> uma foi preenchida
                if current_price >= take_profit:
                    return {"status": "CLOSED_TP", "exit_price": take_profit}
                else:
                    return {"status": "CLOSED_SL", "exit_price": stop_loss}
            return {"status": "OPEN_OCO", "exit_price": None}
        except Exception as e:
            logger.error(f"Erro ao checar status OCO na Binance: {e}")
            return {"status": "OPEN_OCO", "exit_price": None}

