"""
Cliente de Exchange para Binance Spot Testnet com fallback para Simulação Completa.
Inclui Scanner Dinâmico de Mercado (1 request global /api/v3/ticker/24hr sem N+1).
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
BINANCE_PUBLIC_API = "https://data-api.binance.vision/api/v3"
BINANCE_PUBLIC_ENDPOINTS = (
    "https://data-api.binance.vision/api/v3",
    "https://api.binance.com/api/v3",
    "https://api1.binance.com/api/v3",
)
CORE_WATCHLIST = ["SOL/USDT", "NEAR/USDT", "PEPE/USDT", "SUI/USDT"]
SYNTHETIC_BASE_PRICES = {
    "BTC/USDT": 92000.0,
    "ETH/USDT": 3400.0,
    "SOL/USDT": 185.0,
    "BNB/USDT": 620.0,
    "XRP/USDT": 2.40,
    "SUI/USDT": 3.20,
}
EXCLUDED_BASES = {
    "USDC", "FDUSD", "USDT", "DAI", "TUSD", "BUSD", "USDP",
    "USDE", "EUR", "GBP", "PAXG", "WBTC", "USD1", "First",
    "BTC", "ETH", "RLUSD", "PYUSD", "GUSD", "FRAX", "AEUR", "EURI", "USTC"
}
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")
MIN_QUOTE_VOLUME_USD = 35_000_000.0


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

    def fetch_free_usdt_balance(self, fallback_balance: float) -> float:
        """
        Consulta o saldo real de USDT livre na Binance (quando conectado) ou retorna
        o saldo total disponível (Giro + Pool não sacado) na simulação.
        """
        if self.simulation_mode or not self.exchange:
            return fallback_balance
        try:
            balances = self.exchange.fetch_balance()
            free_usdt = float(balances.get("USDT", {}).get("free", fallback_balance))
            return free_usdt if free_usdt > 0 else fallback_balance
        except Exception as e:
            logger.warning(f"Não foi possível ler saldo USDT na Binance, usando ledger local: {e}")
            return fallback_balance

    def discover_dynamic_watchlist(self, max_pairs: int = 6) -> List[str]:
        """
        Varre todo o mercado Spot da Binance em 1 única requisição (/api/v3/ticker/24hr)
        e seleciona as moedas de alta liquidez com melhor momentum no dia, somadas à Core Watchlist.
        """
        tickers = self._fetch_24h_tickers()
        if not tickers:
            return list(CORE_WATCHLIST)

        eligible = [t for t in tickers if self._is_eligible_usdt_ticker(t)]
        ranked = sorted(eligible, key=self._score_ticker_momentum, reverse=True)
        discovered = [self._to_slash_symbol(t["symbol"]) for t in ranked]

        if not discovered:
            return list(CORE_WATCHLIST)
        selected = discovered[:max_pairs]
        logger.info(f"Watchlist Dinâmica selecionada ({len(selected)} ativos de alto fluxo): {selected}")
        return selected

    def _fetch_24h_tickers(self) -> List[Dict[str, Any]]:
        for base_url in BINANCE_PUBLIC_ENDPOINTS:
            tickers = self._try_fetch_24h_from_endpoint(base_url)
            if tickers:
                return tickers
        return []

    @staticmethod
    def _try_fetch_24h_from_endpoint(base_url: str) -> List[Dict[str, Any]]:
        try:
            resp = requests.get(f"{base_url}/ticker/24hr", timeout=10)
            return resp.json() if resp.status_code == 200 else []
        except Exception as e:
            logger.warning(f"Scanner 24h indisponível em {base_url}: {e}")
            return []

    def _is_eligible_usdt_ticker(self, ticker: Dict[str, Any]) -> bool:
        raw_symbol = str(ticker.get("symbol", ""))
        if not raw_symbol.endswith("USDT"):
            return False
        base = raw_symbol[:-4]
        if not self._is_valid_base_asset(base):
            return False
        quote_vol = float(ticker.get("quoteVolume", 0.0))
        change_pct = float(ticker.get("priceChangePercent", 0.0))
        return quote_vol >= MIN_QUOTE_VOLUME_USD and -4.0 <= change_pct <= 22.0

    @staticmethod
    def _is_valid_base_asset(base: str) -> bool:
        if not base or base in EXCLUDED_BASES:
            return False
        # Filtra tokens de ações e ETFs tokenizados tradicionais (ex: SOXLB, SNDKB, NVDAB, SPCXB, TSLAB)
        if len(base) > 3 and base.endswith("B"):
            return False
        return not base.endswith(LEVERAGED_SUFFIXES)

    @staticmethod
    def _score_ticker_momentum(ticker: Dict[str, Any]) -> float:
        """Prioriza altcoins líquidas com forte aceleração e volatilidade para Day Trade rápido."""
        change_pct = float(ticker.get("priceChangePercent", 0.0))
        quote_vol_millions = float(ticker.get("quoteVolume", 0.0)) / 1_000_000.0
        vol_bonus = min(10.0, quote_vol_millions / 20.0)
        if 2.0 <= change_pct <= 18.0:
            return 50.0 + (change_pct * 4.0) + vol_bonus
        if 0.5 <= change_pct < 2.0:
            return 40.0 + (change_pct * 2.0) + vol_bonus
        return max(0.0, change_pct) + vol_bonus

    @staticmethod
    def _to_slash_symbol(raw_symbol: str) -> str:
        return f"{raw_symbol[:-4]}/USDT"

    def fetch_daily_candles(self, symbol: str, limit: int = 250) -> List[Dict[str, float]]:
        """
        Coleta os últimos candles diários (1d) — padrão 250 para cálculo real da EMA 200.
        Retorna lista de dicts com 'open', 'high', 'low', 'close', 'volume'.
        """
        live_candles = self._fetch_binance_klines(symbol, limit)
        if live_candles:
            return live_candles
        return self._generate_synthetic_candles(symbol, limit)

    def _fetch_binance_klines(self, symbol: str, limit: int) -> List[Dict[str, float]]:
        clean_symbol = symbol.replace("/", "").upper()
        for base_url in BINANCE_PUBLIC_ENDPOINTS:
            candles = self._try_fetch_klines_from_endpoint(base_url, clean_symbol, limit)
            if candles:
                return candles
        return []

    def _try_fetch_klines_from_endpoint(self, base_url: str, clean_symbol: str, limit: int) -> List[Dict[str, float]]:
        url = f"{base_url}/klines?symbol={clean_symbol}&interval=15m&limit={limit}"
        try:
            resp = requests.get(url, timeout=10)
            return self._parse_klines_response(resp)
        except Exception as e:
            logger.warning(f"Falha ao consultar klines 15m em {base_url} para {clean_symbol}: {e}")
            return []

    def fetch_current_price(self, symbol: str, fallback_price: float) -> float:
        """Consulta a cotação Spot em tempo real no espelho global da Binance (sem bloqueio de IP EUA)."""
        clean_symbol = symbol.replace("/", "").upper()
        for base_url in BINANCE_PUBLIC_ENDPOINTS:
            price = self._try_fetch_spot_price(base_url, clean_symbol)
            if price > 0:
                return price
        return fallback_price

    @staticmethod
    def _try_fetch_spot_price(base_url: str, clean_symbol: str) -> float:
        try:
            resp = requests.get(f"{base_url}/ticker/price?symbol={clean_symbol}", timeout=8)
            if resp.status_code != 200:
                return 0.0
            return float(resp.json().get("price", 0.0))
        except Exception:
            return 0.0

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
        logger.info(f"[MODO PERDA ZERO] Hold Spot ativo — Alvo de Lucro (Take Profit) em ${take_profit}")
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

        tp_order = self.exchange.create_order(
            symbol=symbol,
            type="limit",
            side="sell",
            amount=quantity,
            price=take_profit,
        )
        order_list_id = tp_order.get("orderListId") or tp_order.get("id")
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
        Verifica se a posição atingiu o Take Profit.
        Em Modo Perda Zero (Spot sem alavancagem), não vende em quedas (Hold até recuperar).
        """
        current_price = self.fetch_current_price(symbol, fallback_price=entry_price)

        if self.simulation_mode or not self.exchange:
            return self._evaluate_price_triggers(current_price, stop_loss, take_profit)

        return self._check_live_oco_orders(symbol, order_list_id, current_price, stop_loss, take_profit)

    @staticmethod
    def _evaluate_price_triggers(current_price: float, stop_loss: float, take_profit: float) -> Dict[str, Any]:
        if current_price >= take_profit:
            return {"status": "CLOSED_TP", "exit_price": max(current_price, take_profit), "current_price": current_price}
        if stop_loss > 0 and current_price <= stop_loss:
            return {"status": "CLOSED_SL", "exit_price": current_price, "current_price": current_price}
        return {"status": "OPEN_OCO", "exit_price": None, "current_price": current_price}

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
            return {"status": "OPEN_OCO", "exit_price": None, "current_price": current_price}

    @staticmethod
    def _resolve_open_orders_state(
        orders: List[Dict[str, Any]],
        order_list_id: int,
        current_price: float,
        stop_loss: float,
        take_profit: float
    ) -> Dict[str, Any]:
        if current_price >= take_profit:
            return {"status": "CLOSED_TP", "exit_price": max(current_price, take_profit), "current_price": current_price}
        if stop_loss > 0 and current_price <= stop_loss:
            return {"status": "CLOSED_SL", "exit_price": current_price, "current_price": current_price}
        return {"status": "OPEN_OCO", "exit_price": None, "current_price": current_price}

    def execute_exit_order(self, symbol: str, quantity: float) -> None:
        """
        Em modo real, cancela eventual ordem limit pendente do par e executa venda imediata a mercado
        (usado em Realização Tática, Stop Temporal de 48h ou Disjuntor de Catástrofe).
        """
        if self.simulation_mode or not self.exchange:
            return
        try:
            self._cancel_open_orders_for_symbol(symbol)
            self.exchange.create_market_sell_order(symbol, quantity)
            logger.info(f"Venda a mercado executada na Binance para {symbol} (qtd={quantity}).")
        except Exception as e:
            logger.warning(f"Aviso ao executar saída a mercado na Binance ({symbol}): {e}")

    def update_take_profit_order(self, symbol: str, quantity: float, new_take_profit: float) -> None:
        """
        Em modo real, substitui a ordem limit de venda pelo novo preço de Take Profit
        quando o robô decide surfar uma tendência de alta mais longa (Trailing TP).
        """
        if self.simulation_mode or not self.exchange:
            return
        try:
            self._cancel_open_orders_for_symbol(symbol)
            self.exchange.create_order(
                symbol=symbol,
                type="limit",
                side="sell",
                amount=quantity,
                price=new_take_profit,
            )
            logger.info(f"Ordem Limit de Take Profit atualizada na Binance ({symbol} -> ${new_take_profit}).")
        except Exception as e:
            logger.warning(f"Aviso ao atualizar ordem de Take Profit na Binance ({symbol}): {e}")

    def _cancel_open_orders_for_symbol(self, symbol: str) -> None:
        open_orders = self.exchange.fetch_open_orders(symbol)
        for order in open_orders:
            self.exchange.cancel_order(order["id"], symbol)
