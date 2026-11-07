"""
Agente 1: Análise Técnica (Groq API - Llama 3.3 70B)
Peso: 0.60 (60%)
Avalia estrutura de preço, médias móveis (EMA 20, 50, 200), RSI 14 e volatilidade ATR.
Segue Object Calisthenics (1 nível de indentação por método, sem else, domínio encapsulado).
"""

import os
import json
import logging
from typing import Dict, Any, Optional, List
import requests

from domain import TechnicalIndicators, AgentVerdict

logger = logging.getLogger("cashbot.technical")

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"


class TechnicalAgent:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = "llama-3.3-70b-versatile"

    def analyze(self, symbol: str, indicators: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analisa os indicadores técnicos e devolve dict compatível com AgentVerdict (score, veto, reasoning).
        """
        ind = self._to_indicators_domain(indicators)
        if not self.api_key:
            logger.warning("GROQ_API_KEY não configurada. Usando motor heurístico local para simulação.")
            return self._heuristic_analysis(symbol, ind.to_dict())

        llm_verdict = self._request_groq_analysis(symbol, ind)
        if llm_verdict is not None:
            return llm_verdict.to_dict()

        return self._heuristic_analysis(symbol, ind.to_dict())

    def _request_groq_analysis(self, symbol: str, ind: TechnicalIndicators) -> Optional[AgentVerdict]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Você é um motor JSON estrito de análise técnica para criptoativos."},
                {"role": "user", "content": self._build_prompt(symbol, ind)}
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }
        try:
            resp = requests.post(GROQ_ENDPOINT, headers=headers, json=payload, timeout=15)
            return self._parse_groq_response(resp)
        except Exception as e:
            logger.error(f"Falha na requisição Groq: {e}")
            return None

    def _parse_groq_response(self, resp: requests.Response) -> Optional[AgentVerdict]:
        if resp.status_code != 200:
            logger.error(f"Erro na API Groq ({resp.status_code}): {resp.text}")
            return None
        content = self._extract_groq_content(resp.json())
        data = json.loads(content)
        return AgentVerdict(
            score=float(data.get("score", 50.0)),
            veto=bool(data.get("veto", False)),
            reasoning=str(data.get("reasoning", "Análise via Llama 3.3 concluída."))
        )

    @staticmethod
    def _extract_groq_content(payload: Dict[str, Any]) -> str:
        choices = payload.get("choices", [{}])
        message = choices[0].get("message", {})
        return str(message.get("content", "{}"))

    @staticmethod
    def _build_prompt(symbol: str, ind: TechnicalIndicators) -> str:
        return f"""
Você é um Trader Quantitativo Sênior especialista em Swing Trade Spot.
Analise os seguintes dados técnicos diários (D1) para o par {symbol}:

- Preço Atual: ${ind.current_price}
- EMA 20: ${ind.ema20}
- EMA 50: ${ind.ema50}
- EMA 200: ${ind.ema200}
- RSI 14: {ind.rsi14}
- ATR 14: ${ind.atr14}

Critérios de pontuação:
1. Tendência de Alta Forte (Preço > EMA 20 > EMA 50 > EMA 200): +40 a +50 pontos.
2. Momentum Saudável (RSI entre 45 e 65 em expansão de volume): +20 a +30 pontos.
3. Alinhamento de Médias e suporte: +10 a +20 pontos.
4. RSI > 75 (Sobrecompra extrema) ou Preço abaixo da EMA 200 (Tendência de Baixa): Atribuir nota baixa (< 45).
5. VETO (veto: true): Ativar veto SOMENTE se o ativo estiver em clara reversão para baixa expressiva (Preço < EMA 50 e RSI em colapso < 35) ou RSI > 80.

Responda EXCLUSIVAMENTE em formato JSON com o seguinte schema:
{{
  "score": <número float de 0 a 100>,
  "veto": <true ou false>,
  "reasoning": "<resumo conciso de até 2 frases em português explicando o motivo>"
}}
"""

    def _heuristic_analysis(self, symbol: str, indicators: Dict[str, Any]) -> Dict[str, Any]:
        """Motor heurístico de contingência sem else e com 1 nível de indentação."""
        ind = self._to_indicators_domain(indicators)
        reasons: List[str] = []

        trend_delta = self._evaluate_trend(ind, reasons)
        rsi_delta = self._evaluate_momentum(ind, reasons)
        veto = self._should_veto(ind, reasons)

        raw_score = 50.0 + trend_delta + rsi_delta
        clamped_score = max(0.0, min(100.0, raw_score))
        summary = " ".join(reasons) if reasons else "Indicadores em consolidação neutra."

        return AgentVerdict(
            score=round(clamped_score, 2),
            veto=veto,
            reasoning=summary
        ).to_dict()

    @staticmethod
    def _evaluate_trend(ind: TechnicalIndicators, reasons: List[str]) -> float:
        if ind.is_strong_uptrend:
            reasons.append("Tendência de alta perfeita (Preço > EMA20 > EMA50 > EMA200).")
            return 30.0
        if ind.is_above_ema50:
            reasons.append("Preço acima da EMA50 em recuperação.")
            return 15.0
        if ind.is_below_ema200:
            reasons.append("Preço abaixo da EMA200 (tendência primária de baixa).")
            return -25.0
        return 0.0

    @staticmethod
    def _evaluate_momentum(ind: TechnicalIndicators, reasons: List[str]) -> float:
        if ind.is_healthy_momentum:
            reasons.append(f"RSI {ind.rsi14:.1f} em zona de aceleração positiva saudável.")
            return 15.0
        if ind.is_overbought:
            reasons.append(f"RSI {ind.rsi14:.1f} em sobrecompra extrema (risco de correção).")
            return -20.0
        if ind.is_oversold:
            reasons.append(f"RSI {ind.rsi14:.1f} em região de sobrevenda.")
            return -15.0
        return 0.0

    @staticmethod
    def _should_veto(ind: TechnicalIndicators, reasons: List[str]) -> bool:
        if ind.is_oversold and not ind.is_above_ema50:
            reasons.append("Veto: Fraqueza técnica severa com perda de médias.")
            return True
        return False

    @staticmethod
    def _to_indicators_domain(indicators: Any) -> TechnicalIndicators:
        if isinstance(indicators, TechnicalIndicators):
            return indicators
        return TechnicalIndicators(
            current_price=float(indicators["current_price"]),
            ema20=float(indicators["ema20"]),
            ema50=float(indicators["ema50"]),
            ema200=float(indicators["ema200"]),
            rsi14=float(indicators["rsi14"]),
            atr14=float(indicators["atr14"]),
        )
