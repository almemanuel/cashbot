"""
Agente 3: Risco, Velocidade de Giro e Dimensionamento Híbrido (IA + Guardrails)
Calcula EMAs, RSI, ATR, Suporte/Resistência de 7 dias e valida os alvos dinâmicos
escolhidos pela IA para tiros curtos (giro rápido de caixa).
Segue Object Calisthenics (1 nível de indentação por método, sem else).
"""

from typing import List, Dict, Any, Tuple

MIN_STOP_PCT = 1.5
MAX_STOP_PCT = 4.5
MIN_TP_PCT = 3.0
MAX_TP_PCT = 8.5
MIN_REWARD_RISK_RATIO = 1.5
BINANCE_MIN_NOTIONAL_USD = 10.0
SAFE_MIN_SLOT_USD = 12.0
MAX_CONCURRENT_POSITIONS = 3
MIN_WITHDRAWABLE_USD = 10.0
DEFAULT_CAPITAL_USAGE_PCT = 0.95
REINVEST_PROFIT_RATIO = 0.60
WITHDRAW_PROFIT_RATIO = 0.40


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
        """Calcula EMAs (20, 50, 200), RSI (14), ATR (14) e Máxima/Mínima de 7 dias."""
        closes = [c["close"] for c in candles]
        current_price = closes[-1] if closes else 0.0

        ema20 = calculate_ema(closes, 20)[-1] if len(closes) >= 20 else current_price
        ema50 = calculate_ema(closes, 50)[-1] if len(closes) >= 50 else current_price
        ema200 = calculate_ema(closes, 200)[-1] if len(closes) >= 200 else current_price
        rsi14 = calculate_rsi(closes, 14)
        atr14 = calculate_atr(candles, 14)

        recent_slice = candles[-7:] if len(candles) >= 7 else candles
        high_7d = max((c["high"] for c in recent_slice), default=current_price)
        low_7d = min((c["low"] for c in recent_slice), default=current_price)

        return {
            "current_price": current_price,
            "ema20": _round_price(ema20),
            "ema50": _round_price(ema50),
            "ema200": _round_price(ema200),
            "rsi14": round(rsi14, 2),
            "atr14": _round_price(atr14),
            "recent_high_7d": _round_price(high_7d),
            "recent_low_7d": _round_price(low_7d),
        }

    def calculate_levels(
        self,
        entry_price: float,
        atr14: float,
        ai_stop_pct: float = 0.0,
        ai_tp_pct: float = 0.0
    ) -> Tuple[float, float, float]:
        """
        Define Stop Loss e Take Profit de giro rápido combinando a escolha da IA
        com guardrails de segurança (Stop entre 1.5% e 4.5%; Alvo entre 3.0% e 8.5%).
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
        if ai_stop_pct > 0:
            return max(MIN_STOP_PCT, min(MAX_STOP_PCT, ai_stop_pct))
        atr_pct = ((0.8 * atr14) / entry_price) * 100.0 if entry_price > 0 else 2.5
        return max(MIN_STOP_PCT, min(MAX_STOP_PCT, atr_pct))

    @staticmethod
    def _resolve_tp_pct(stop_pct: float, ai_tp_pct: float) -> float:
        min_required_tp = max(MIN_TP_PCT, stop_pct * MIN_REWARD_RISK_RATIO)
        if ai_tp_pct > 0:
            clamped_ai = max(min_required_tp, min(MAX_TP_PCT, ai_tp_pct))
            return round(clamped_ai, 2)
        default_tp = min(MAX_TP_PCT, max(min_required_tp, stop_pct * 1.8))
        return round(default_tp, 2)

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
        Divide o capital livre de forma inteligente entre as oportunidades aprovadas na rodada,
        permitindo diversificar em até MAX_CONCURRENT_POSITIONS (3) ativos simultâneos
        desde que cada posição receba pelo menos SAFE_MIN_SLOT_USD (US$ 12).
        """
        deployable = round(free_balance * self.capital_usage_pct, 2)
        slots_left = max(0, MAX_CONCURRENT_POSITIONS - open_positions_count)
        max_affordable_slots = int(deployable // SAFE_MIN_SLOT_USD)
        allowed_count = min(len(scores), slots_left, max_affordable_slots)

        if allowed_count <= 0:
            return []

        if allowed_count == 1 and open_positions_count == 0 and deployable >= (SAFE_MIN_SLOT_USD * 2.2):
            return [round(deployable * 0.55, 2)]

        selected_scores = scores[:allowed_count]
        total_score = sum(selected_scores)
        return [
            round(deployable * (s / total_score), 2)
            for s in selected_scores
        ]

    def allocate_trade_pnl(
        self,
        trading_balance: float,
        withdrawable_pool: float,
        pnl_usd: float
    ) -> Tuple[float, float, float, float]:
        """
        Aplica Recomposição da Banca Base + Bola de Neve + Trava de Saque Mínimo da Binance (US$ 10).
        Enquanto o valor separável para saque for menor que US$ 10.00, 100% do lucro fica
        reinvestido no Capital de Giro multiplicando a banca.
        Retorna (new_trading_balance, new_withdrawable_pool, added_to_withdraw, added_to_reinvest).
        """
        if pnl_usd <= 0:
            new_trading = max(0.0, round(trading_balance + pnl_usd, 2))
            return new_trading, round(withdrawable_pool, 2), 0.0, 0.0

        total_after_trade = trading_balance + pnl_usd
        surplus_above_floor = max(0.0, total_after_trade - self.base_capital_floor)
        candidate_withdraw = round(surplus_above_floor * WITHDRAW_PROFIT_RATIO, 2)

        if withdrawable_pool + candidate_withdraw < MIN_WITHDRAWABLE_USD:
            new_trading = round(total_after_trade, 2)
            return new_trading, round(withdrawable_pool, 2), 0.0, round(pnl_usd, 2)

        to_withdraw = min(round(pnl_usd, 2), candidate_withdraw)
        to_reinvest = round(pnl_usd - to_withdraw, 2)

        new_trading = round(trading_balance + to_reinvest, 2)
        new_pool = round(withdrawable_pool + to_withdraw, 2)
        return new_trading, new_pool, to_withdraw, to_reinvest
