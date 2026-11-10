"""
Agente 3: Risco, Velocidade de Giro e Dimensionamento Híbrido (IA + Guardrails)
Calcula EMAs, RSI, ATR, Suporte/Resistência de 7 dias e valida os alvos dinâmicos
escolhidos pela IA para tiros curtos (giro rápido de caixa).
Segue Object Calisthenics (1 nível de indentação por método, sem else).
"""

import math
from typing import List, Dict, Any, Tuple

CATASTROPHE_STOP_PCT = 7.5
MIN_STOP_PCT = 7.0
MAX_STOP_PCT = 8.0
MIN_TP_PCT = 0.45
MAX_TP_PCT = 1.0
DEFAULT_TP_PCT = 0.60
BINANCE_MIN_NOTIONAL_USD = 10.0
SAFE_MIN_SLOT_USD = 12.0
MAX_CONCURRENT_POSITIONS = 1
MIN_WITHDRAWABLE_USD = 10.0
DEFAULT_CAPITAL_USAGE_PCT = 0.85
REINVEST_PROFIT_RATIO = 0.10
WITHDRAW_PROFIT_RATIO = 0.90


def _round_price(value: float) -> float:
    """Preserva casas decimais adequadas para qualquer faixa de preço (ex: BTC vs PEPE)."""
    if value < 0.001:
        return round(value, 8)
    if value < 1.0:
        return round(value, 6)
    return round(value, 4)


def calculate_ema(prices: List[float], period: int) -> List[float]:
    """Calcula a Média Móvel Exponencial (EMA)."""
    if len(prices) < period:
        return [prices[-1]] * len(prices)

    multiplier = 2.0 / (period + 1)
    ema = [sum(prices[:period]) / period]
    for price in prices[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    return ema


def calculate_rsi(prices: List[float], period: int = 14) -> float:
    """Calcula o Índice de Força Relativa (RSI de 14 períodos)."""
    if len(prices) <= period:
        return 50.0

    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calculate_atr(candles: List[Dict[str, float]], period: int = 14) -> float:
    """Calcula o Average True Range (ATR) de 14 períodos."""
    if len(candles) < 2:
        return 0.0

    true_ranges = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        prev_close = candles[i - 1]["close"]
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0

    atr = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


class RiskAgent:
    """Dimensiona posição de giro rápido e calcula divisão inteligente entre Banca e Saque."""

    def __init__(self, capital_usage_pct: float = DEFAULT_CAPITAL_USAGE_PCT, base_capital_floor: float = 100.0):
        self.capital_usage_pct = capital_usage_pct
        self.base_capital_floor = base_capital_floor

    def compute_indicators(self, candles: List[Dict[str, float]]) -> Dict[str, Any]:
        """Calcula EMAs (20, 50, 200), RSI (14), ATR (14), VWAP, Bandas de Bollinger e Volume Ratio (15m)."""
        closes = [c["close"] for c in candles]
        current_price = closes[-1] if closes else 0.0

        ema20 = calculate_ema(closes, 20)[-1] if len(closes) >= 20 else current_price
        ema50 = calculate_ema(closes, 50)[-1] if len(closes) >= 50 else current_price
        ema200 = calculate_ema(closes, 200)[-1] if len(closes) >= 200 else current_price
        rsi14 = calculate_rsi(closes, 14)
        atr14 = calculate_atr(candles, 14)

        recent_slice = candles[-96:] if len(candles) >= 96 else candles
        high_7d = max((c["high"] for c in recent_slice), default=current_price)
        low_7d = min((c["low"] for c in recent_slice), default=current_price)
        vwap = self._calculate_vwap(recent_slice, current_price)
        bb_upper, bb_lower = self._calculate_bollinger_bands(closes, current_price)
        volume_ratio = self._calculate_volume_ratio(candles)
        momentum_1h = self._calculate_momentum_1h(closes)

        return {
            "current_price": current_price,
            "ema20": _round_price(ema20),
            "ema50": _round_price(ema50),
            "ema200": _round_price(ema200),
            "rsi14": round(rsi14, 2),
            "atr14": _round_price(atr14),
            "recent_high_7d": _round_price(high_7d),
            "recent_low_7d": _round_price(low_7d),
            "vwap": _round_price(vwap),
            "bb_upper": _round_price(bb_upper),
            "bb_lower": _round_price(bb_lower),
            "volume_ratio": round(volume_ratio, 2),
            "momentum_1h_pct": round(momentum_1h, 2),
        }

    @staticmethod
    def _calculate_vwap(candles: List[Dict[str, float]], fallback: float) -> float:
        total_vol = sum(c.get("volume", 0.0) for c in candles)
        if total_vol <= 0:
            return fallback
        pv_sum = sum(((c["high"] + c["low"] + c["close"]) / 3.0) * c.get("volume", 0.0) for c in candles)
        return pv_sum / total_vol

    @staticmethod
    def _calculate_bollinger_bands(closes: List[float], fallback: float, period: int = 20) -> Tuple[float, float]:
        if len(closes) < period:
            return fallback * 1.015, fallback * 0.985
        window = closes[-period:]
        mean = sum(window) / period
        variance = sum((p - mean) ** 2 for p in window) / period
        std_dev = math.sqrt(variance)
        return mean + (2.0 * std_dev), max(0.0, mean - (2.0 * std_dev))

    @staticmethod
    def _calculate_volume_ratio(candles: List[Dict[str, float]], period: int = 20) -> float:
        if len(candles) < period:
            return 1.0
        vols = [c.get("volume", 0.0) for c in candles[-period:]]
        avg_vol = sum(vols) / period
        if avg_vol <= 0:
            return 1.0
        recent_vol = max(vols[-1], vols[-2] if len(vols) >= 2 else vols[-1])
        return recent_vol / avg_vol

    @staticmethod
    def _calculate_momentum_1h(closes: List[float]) -> float:
        if len(closes) < 5 or closes[-5] <= 0:
            return 0.0
        return ((closes[-1] - closes[-5]) / closes[-5]) * 100.0

    def calculate_levels(
        self,
        entry_price: float,
        atr14: float,
        ai_stop_pct: float = 0.0,
        ai_tp_pct: float = 0.0
    ) -> Tuple[float, float, float]:
        """
        Define o Disjuntor de Catástrofe (-7.5%) para evitar ruído curto mas proteger a banca
        contra colapsos severos, mantendo o Take Profit curto de Day Trade (+0.8% a +2.2%).
        Retorna (stop_loss, take_profit, stop_distance).
        """
        stop_pct = self._resolve_stop_pct(entry_price, atr14, ai_stop_pct)
        tp_pct = self._resolve_tp_pct(stop_pct, ai_tp_pct)

        stop_dist = entry_price * (stop_pct / 100.0)
        tp_dist = entry_price * (tp_pct / 100.0)

        stop_loss = _round_price(entry_price - stop_dist)
        take_profit = _round_price(entry_price + tp_dist)
        return stop_loss, take_profit, stop_dist

    @staticmethod
    def _resolve_stop_pct(entry_price: float, atr14: float, ai_stop_pct: float) -> float:
        return CATASTROPHE_STOP_PCT

    @staticmethod
    def _resolve_tp_pct(stop_pct: float, ai_tp_pct: float) -> float:
        if ai_tp_pct > 0:
            clamped_ai = max(MIN_TP_PCT, min(MAX_TP_PCT, ai_tp_pct))
            return round(clamped_ai, 2)
        return DEFAULT_TP_PCT

    def calculate_position_size(self, allocated_usd: float, entry_price: float, stop_dist: float) -> float:
        """
        Converte o capital em dólar alocado para este slot na quantidade exata de moedas,
        respeitando o lote mínimo de US$ 10.00 da Binance Spot.
        """
        if allocated_usd < BINANCE_MIN_NOTIONAL_USD or entry_price <= 0:
            return 0.0

        raw_qty = allocated_usd / entry_price
        if entry_price < 0.01:
            return round(raw_qty, 0)
        return round(raw_qty, 6)

    def split_capital_for_candidates(
        self,
        free_balance: float,
        scores: List[float],
        open_positions_count: int = 0
    ) -> List[float]:
        """
        Modo Sniper: concentra o capital disponível (85%) na única melhor oportunidade do ranking.
        """
        if open_positions_count >= MAX_CONCURRENT_POSITIONS or not scores:
            return []

        deployable = round(free_balance * self.capital_usage_pct, 2)
        if deployable < BINANCE_MIN_NOTIONAL_USD:
            return []

        return [deployable]

    def allocate_trade_pnl(
        self,
        trading_balance: float,
        withdrawable_pool: float,
        pnl_usd: float,
        unrecovered_loss_usd: float = 0.0
    ) -> Tuple[float, float, float, float]:
        """
        Divide o lucro realizado respeitando o Modo Recuperação 100% do Capital:
        - Se houver prejuízo anterior em aberto (unrecovered_loss_usd > 0), destina 100% do lucro
          para recompor o Capital de Giro até zerar o déficit.
        - O excedente acima do capital recuperado segue a regra normal: 60% Giro / 40% Saque.
        Retorna (new_trading_balance, new_withdrawable_pool, added_to_withdraw, added_to_reinvest).
        """
        if pnl_usd <= 0:
            new_trading = max(0.0, round(trading_balance + pnl_usd, 2))
            return new_trading, round(withdrawable_pool, 2), 0.0, 0.0

        recovered_now = min(pnl_usd, max(0.0, unrecovered_loss_usd))
        distributable_profit = max(0.0, round(pnl_usd - recovered_now, 2))

        total_after_trade = trading_balance + pnl_usd
        surplus_above_floor = max(0.0, total_after_trade - self.base_capital_floor)
        max_withdraw_by_floor = round(surplus_above_floor * WITHDRAW_PROFIT_RATIO, 2)

        to_withdraw = min(round(distributable_profit * WITHDRAW_PROFIT_RATIO, 2), max_withdraw_by_floor)
        to_reinvest = round(pnl_usd - to_withdraw, 2)

        new_trading = round(trading_balance + to_reinvest, 2)
        new_pool = round(withdrawable_pool + to_withdraw, 2)
        return new_trading, new_pool, to_withdraw, to_reinvest
