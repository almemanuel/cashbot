"""
Cliente de Exchange para Binance Spot Testnet com fallback para Simulação Completa.
Suporta CCXT ou requisições REST diretas da Binance Testnet.
Segue Object Calisthenics (1 nível de indentação por método, sem else).
"""

import os
import time
import logging
import random
from typing import List, Dict, Any, Optional
import requests

logger = logging.getLogger("cashbot.exchange")

try:
    import ccxt
    HAS_CCXT = True
except ImportError:
    HAS_CCXT = False

BINANCE_TESTNET_BASE = "https://testnet.binance.vision"
SYNTHETIC_BASE_PRICES = {"BTC/USDT": 92000.0, "ETH/USDT": 3400.0, "SOL/USDT": 185.0}


class ExchangeClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        simulation_mode: bool = True
    ):
        self.api_key = api_key or os.getenv("BINANCE_TESTNET_API_KEY")
        self.secret_key = secret_key or os.getenv("BINANCE_TESTNET_SECRET_KEY")
        env_sim = os.getenv("SIMULATION_MODE", "True").lower() in ("true", "1", "yes")
        self.simulation_mode = simulation_mode or env_sim or not (self.api_key and self.secret_key)
        self.exchange = self._init_ccxt_client()

    def _init_ccxt_client(self):
        if not (HAS_CCXT and self.api_key and self.secret_key):
            return None
        try:
            client = ccxt.binance({
                "apiKey": self.api_key,
                "secret": self.secret_key,
                "options": {"defaultType": "spot"},
                "enableRateLimit": True,
            })
            client.set_sandbox_mode(True)
            return client
        except Exception as e:
            logger.warning(f"Erro ao inicializar CCXT sandbox: {e}. Entrando em modo simulado.")
            self.simulation_mode = True
            return None

    def fetch_daily_candles(self, symbol: str, limit: int = 60) -> List[Dict[str, float]]:
        """
        Coleta os últimos candles diários (1d).
        Retorna lista de dicts com 'open', 'high', 'low', 'close', 'volume'.
        """
        live_candles = self._fetch_binance_klines(symbol, limit)
        if live_candles:
            return live_candles
        return self._generate_synthetic_candles(symbol, limit)

    def _fetch_binance_klines(self, symbol: str, limit: int) -> List[Dict[str, float]]:
        clean_symbol = symbol.replace("/", "").upper()
        url = f"https://api.binance.com/api/v3/klines?symbol={clean_symbol}&interval=1d&limit={limit}"
        try:
            resp = requests.get(url, timeout=10)
            return self._parse_klines_response(resp)
        except Exception as e:
            logger.warning(f"Falha ao consultar klines da Binance para {symbol}: {e}. Gerando candles de simulação.")
            return []

    def _parse_klines_response(self, resp: requests.Response) -> List[Dict[str, float]]:
        if resp.status_code != 200:
            return []
        return [self._map_kline_row(item) for item in resp.json()]

    @staticmethod
    def _map_kline_row(item: List[Any]) -> Dict[str, float]:
        return {
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[5]),
        }

    def _generate_synthetic_candles(self, symbol: str, limit: int) -> List[Dict[str, float]]:
        current = SYNTHETIC_BASE_PRICES.get(symbol, 100.0)
        candles: List[Dict[str, float]] = []
        for _ in range(limit):
            candle = self._build_next_synthetic_candle(current)
            current = candle["close"]
            candles.append(candle)
        return candles

    @staticmethod
    def _build_next_synthetic_candle(open_price: float) -> Dict[str, float]:
        variation = random.uniform(-0.02, 0.025)
        close_p = open_price * (1.0 + variation)
        high_p = max(open_price, close_p) * (1.0 + random.uniform(0.002, 0.015))
        low_p = min(open_price, close_p) * (1.0 - random.uniform(0.002, 0.015))
        return {
            "open": round(open_price, 4),
            "high": round(high_p, 4),
            "low": round(low_p, 4),
            "close": round(close_p, 4),
            "volume": round(random.uniform(500, 3000), 2),
        }

    def create_market_buy_and_oco(
        self,
        symbol: str,
        quantity: float,
        stop_loss: float,
        take_profit: float
    ) -> Dict[str, Any]:
        """
        Submete ordem de compra a mercado e imediatamente submete ordem OCO vinculada.
        """
        if self.simulation_mode or not self.exchange:
            return self._create_simulated_oco(symbol, quantity, stop_loss, take_profit)

        try:
            return self._create_live_oco(symbol, quantity, stop_loss, take_profit)
        except Exception as e:
            logger.error(f"Erro ao submeter ordens na Binance Testnet: {e}. Efetuando fallback para simulação.")
            return self._create_simulated_oco(symbol, quantity, stop_loss, take_profit)

    @staticmethod
    def _create_simulated_oco(
        symbol: str,
        quantity: float,
        stop_loss: float,
        take_profit: float
    ) -> Dict[str, Any]:
        logger.info(f"[SIMULAÇÃO] Compra a mercado executada para {symbol}. Qtd: {quantity}")
        logger.info(f"[SIMULAÇÃO] Ordem OCO armada: Stop Loss em ${stop_loss}, Take Profit em ${take_profit}")
        return {
            "order_list_id": int(time.time() * 1000),
            "status": "OPEN_OCO",
            "simulated": True,
        }

    def _create_live_oco(
        self,
        symbol: str,
        quantity: float,
        stop_loss: float,
        take_profit: float
    ) -> Dict[str, Any]:
        market_order = self.exchange.create_market_buy_order(symbol, quantity)
        logger.info(f"Compra a mercado executada na Testnet: {market_order.get('id')}")

        oco_params = {
            "stopPrice": self.exchange.price_to_precision(symbol, stop_loss),
            "stopLimitPrice": self.exchange.price_to_precision(symbol, stop_loss * 0.998),
            "stopLimitTimeInForce": "GTC",
        }
        oco_order = self.exchange.create_order(
            symbol=symbol,
            type="limit",
            side="sell",
            amount=quantity,
            price=take_profit,
            params=oco_params,
        )
        order_list_id = oco_order.get("orderListId") or oco_order.get("id")
        return {
            "order_list_id": order_list_id,
            "status": "OPEN_OCO",
            "simulated": False,
        }

    def check_oco_status(
        self,
        symbol: str,
        order_list_id: int,
        entry_price: float,
        stop_loss: float,
        take_profit: float
    ) -> Dict[str, Any]:
        """
        Verifica o estado da ordem OCO.
        Retorna status: 'OPEN_OCO', 'CLOSED_TP', 'CLOSED_SL'.
        """
        candles = self.fetch_daily_candles(symbol, limit=1)
        current_price = candles[-1]["close"] if candles else entry_price

        if self.simulation_mode or not self.exchange:
            return self._evaluate_price_triggers(current_price, stop_loss, take_profit)

        return self._check_live_oco_orders(symbol, order_list_id, current_price, stop_loss, take_profit)

    @staticmethod
    def _evaluate_price_triggers(current_price: float, stop_loss: float, take_profit: float) -> Dict[str, Any]:
        if current_price >= take_profit:
            return {"status": "CLOSED_TP", "exit_price": take_profit}
        if current_price <= stop_loss:
            return {"status": "CLOSED_SL", "exit_price": stop_loss}
        return {"status": "OPEN_OCO", "exit_price": None}

    def _check_live_oco_orders(
        self,
        symbol: str,
        order_list_id: int,
        current_price: float,
        stop_loss: float,
        take_profit: float
    ) -> Dict[str, Any]:
        try:
            orders = self.exchange.fetch_open_orders(symbol)
            return self._resolve_open_orders_state(orders, order_list_id, current_price, stop_loss, take_profit)
        except Exception as e:
            logger.error(f"Erro ao checar status OCO na Binance: {e}")
            return {"status": "OPEN_OCO", "exit_price": None}

    @staticmethod
    def _resolve_open_orders_state(
        orders: List[Dict[str, Any]],
        order_list_id: int,
        current_price: float,
        stop_loss: float,
        take_profit: float
    ) -> Dict[str, Any]:
        matching = [o for o in orders if str(o.get("orderListId", "")) == str(order_list_id)]
        if matching:
            return {"status": "OPEN_OCO", "exit_price": None}
        if current_price >= take_profit:
            return {"status": "CLOSED_TP", "exit_price": take_profit}
        return {"status": "CLOSED_SL", "exit_price": stop_loss}
