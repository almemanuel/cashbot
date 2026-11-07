"""
Objetos de Domínio e Coleções de Primeira Classe (Object Calisthenics).
Encapsula primitivos e coleções mantendo compatibilidade com serialização dict/JSON.
"""

from dataclasses import dataclass, asdict
from typing import List, Dict, Any


class DictCompatibleMixin:
    """Permite acesso via atributo ou chave dict para compatibilidade com JSON/API."""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


@dataclass(frozen=True)
class FearAndGreed(DictCompatibleMixin):
    value: int
    classification: str

    @property
    def is_extreme_panic(self) -> bool:
        return self.value < 20


@dataclass(frozen=True)
class TechnicalIndicators(DictCompatibleMixin):
    current_price: float
    ema20: float
    ema50: float
    ema200: float
    rsi14: float
    atr14: float
    recent_high_7d: float = 0.0
    recent_low_7d: float = 0.0

    @property
    def is_strong_uptrend(self) -> bool:
        return self.current_price > self.ema20 > self.ema50

    @property
    def is_above_ema50(self) -> bool:
        return self.current_price > self.ema50

    @property
    def is_below_ema200(self) -> bool:
        return self.current_price < self.ema200

    @property
    def is_healthy_momentum(self) -> bool:
        return 45.0 <= self.rsi14 <= 68.0

    @property
    def is_overbought(self) -> bool:
        return self.rsi14 > 78.0

    @property
    def is_oversold(self) -> bool:
        return self.rsi14 < 32.0

    @property
    def upside_to_7d_high_pct(self) -> float:
        if self.current_price <= 0 or self.recent_high_7d <= self.current_price:
            return 5.0
        return round(((self.recent_high_7d - self.current_price) / self.current_price) * 100.0, 2)


@dataclass(frozen=True)
class RiskLevels(DictCompatibleMixin):
    stop_loss: float
    take_profit: float
    stop_distance: float


@dataclass(frozen=True)
class AgentVerdict(DictCompatibleMixin):
    score: float
    veto: bool
    reasoning: str
    stop_loss_pct: float = 0.0
    take_profit_pct: float = 0.0


@dataclass(frozen=True)
class Deliberation(DictCompatibleMixin):
    symbol: str
    indicators: TechnicalIndicators
    tech_score: float
    sent_score: float
    final_score: float
    veto: bool
    summary: str
    tech_reason: str = ""
    sent_reason: str = ""
    ai_stop_loss_pct: float = 0.0
    ai_take_profit_pct: float = 0.0

    def is_approved(self, min_score: float) -> bool:
        if self.veto:
            return False
        return self.final_score >= min_score


class HeadlineCollection:
    """Coleção de Primeira Classe para manchetes de um ativo (Regra 4 de Object Calisthenics)."""

    def __init__(self, items: List[str] = None):
        self._items: List[str] = list(items or [])

    def add(self, title: str, source: str = "") -> None:
        cleaned = title.strip()
        if not cleaned:
            return
        formatted = f"{cleaned} ({source})" if source else cleaned
        self._items.append(formatted)

    def top(self, limit: int = 5) -> List[str]:
        return self._items[:limit]

    def is_empty(self) -> bool:
        return len(self._items) == 0

    def format_bullet_list(self) -> str:
        if self.is_empty():
            return "  - Nenhuma manchete crítica recente encontrada nas últimas 24h."
        return "\n".join(f"  - {h}" for h in self._items)

    def find_first_matching(self, keywords: List[str]) -> str:
        matches = [h for h in self._items if self._contains_any(h.lower(), keywords)]
        return matches[0] if matches else ""

    def count_keyword_hits(self, keywords: List[str]) -> int:
        return sum(self._count_in_text(h.lower(), keywords) for h in self._items)

    @staticmethod
    def _contains_any(text: str, keywords: List[str]) -> bool:
        return any(kw in text for kw in keywords)

    @staticmethod
    def _count_in_text(text: str, keywords: List[str]) -> int:
        return sum(1 for kw in keywords if kw in text)
