"""
Agente 3: Risco e Dimensionamento Determinístico
Realiza cálculos matemáticos de ATR, EMAs, RSI e define Stop Loss (1.5x ATR)
e Take Profit (2.0x SL -> R:R 1:2).
"""

from typing import List, Dict, Any, Tuple

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

    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
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
    """
    Calcula o Average True Range (ATR) de 14 períodos.
    candles: lista de dicts com 'high', 'low', 'close'.
    """
    if len(candles) < 2:
        return 0.0

    true_ranges = []
    for i in range(1, len(candles)):
        h = candles[i]['high']
        l = candles[i]['low']
        prev_close = candles[i-1]['close']
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0

    atr = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr

class RiskAgent:
    """Calcula dimensionamento de posição, Stop Loss e Take Profit com base no SDD."""

    def __init__(self, risk_pct_per_trade: float = 0.02, max_position_pct: float = 0.30):
        self.risk_pct_per_trade = risk_pct_per_trade  # 2% de risco de perda máxima do capital
        self.max_position_pct = max_position_pct      # Alocação máxima de 30% do saldo total

    def compute_indicators(self, candles: List[Dict[str, float]]) -> Dict[str, Any]:
        """Calcula EMAs (20, 50, 200), RSI (14) e ATR (14)."""
        closes = [c['close'] for c in candles]
        current_price = closes[-1] if closes else 0.0

        ema20 = calculate_ema(closes, 20)[-1] if len(closes) >= 20 else current_price
        ema50 = calculate_ema(closes, 50)[-1] if len(closes) >= 50 else current_price
        ema200 = calculate_ema(closes, 200)[-1] if len(closes) >= 200 else current_price
        rsi14 = calculate_rsi(closes, 14)
        atr14 = calculate_atr(candles, 14)

        return {
            "current_price": current_price,
            "ema20": round(ema20, 4),
            "ema50": round(ema50, 4),
            "ema200": round(ema200, 4),
            "rsi14": round(rsi14, 2),
            "atr14": round(atr14, 4),
        }

    def calculate_levels(self, entry_price: float, atr14: float) -> Tuple[float, float, float]:
        """
        Stop Loss: Entrada - (1.5 * ATR14)
        Take Profit: Entrada + (2.0 * Distância SL) [R:R 1:2]
        Retorna (stop_loss, take_profit, stop_distance)
        """
        stop_dist = 1.5 * atr14
        # Evita stop loss negativo ou zerado em ativos de alta volatilidade
        if stop_dist >= entry_price * 0.5:
            stop_dist = entry_price * 0.05  # limite de 5% de segurança

        stop_loss = round(entry_price - stop_dist, 4)
        take_profit = round(entry_price + (2.0 * stop_dist), 4)

        return stop_loss, take_profit, stop_dist

    def calculate_position_size(self, balance: float, entry_price: float, stop_dist: float) -> float:
        """
        Calcula a quantidade de moedas a comprar respeitando o risco máximo por trade
        e o teto de capital de giro alocado.
        """
        if balance <= 0 or entry_price <= 0 or stop_dist <= 0:
            return 0.0

        # Risco financeiro máximo aceito neste trade (ex: 2% do saldo)
        risk_budget = balance * self.risk_pct_per_trade
        # Quantidade necessária para que a perda no Stop Loss seja igual ao risk_budget
        qty_by_risk = risk_budget / stop_dist

        # Teto máximo de capital de giro empregado nesta ordem
        max_capital = balance * self.max_position_pct
        qty_by_capital = max_capital / entry_price

        # Escolhe a quantidade mais conservadora
        chosen_qty = min(qty_by_risk, qty_by_capital)

        # Arredondamento seguro (mínimo de precisão)
        return round(chosen_qty, 6)

