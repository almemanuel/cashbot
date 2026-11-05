"""
Agente 1: Análise Técnica (Groq API - Llama 3.3 70B)
Peso: 0.60 (60%)
Avalia estrutura de preço, médias móveis (EMA 20, 50, 200), RSI 14 e volatilidade ATR.
"""

import os
import json
import logging
import requests
from typing import Dict, Any

logger = logging.getLogger("cashbot.technical")

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"

class TechnicalAgent:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = "llama-3.3-70b-versatile"

    def analyze(self, symbol: str, indicators: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analisa os indicadores técnicos e devolve score (0-100), veto (bool) e reasoning.
        """
        if not self.api_key:
            logger.warning("GROQ_API_KEY não configurada. Usando motor heurístico local para simulação.")
            return self._heuristic_analysis(symbol, indicators)

        prompt = f"""
Você é um Trader Quantitativo Sênior especialista em Swing Trade Spot.
Analise os seguintes dados técnicos diários (D1) para o par {symbol}:

- Preço Atual: ${indicators['current_price']}
- EMA 20: ${indicators['ema20']}
- EMA 50: ${indicators['ema50']}
- EMA 200: ${indicators['ema200']}
- RSI 14: {indicators['rsi14']}
- ATR 14: ${indicators['atr14']}

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

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "Você é um motor JSON estrito de análise técnica para criptoativos."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }

        try:
            resp = requests.post(GROQ_ENDPOINT, headers=headers, json=payload, timeout=15)
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                data = json.loads(content)
                return {
                    "score": float(data.get("score", 50.0)),
                    "veto": bool(data.get("veto", False)),
                    "reasoning": str(data.get("reasoning", "Análise via Llama 3.3 concluída."))
                }
            else:
                logger.error(f"Erro na API Groq ({resp.status_code}): {resp.text}")
                return self._heuristic_analysis(symbol, indicators)
        except Exception as e:
            logger.error(f"Falha na requisição Groq: {e}")
            return self._heuristic_analysis(symbol, indicators)

    def _heuristic_analysis(self, symbol: str, indicators: Dict[str, Any]) -> Dict[str, Any]:
        """Motor heurístico de contingência / simulação rápida quando a API não estiver conectada."""
        price = indicators['current_price']
        ema20 = indicators['ema20']
        ema50 = indicators['ema50']
        ema200 = indicators['ema200']
        rsi = indicators['rsi14']

        score = 50.0
        veto = False
        reasons = []

        # Tendência
        if price > ema20 > ema50 > ema200:
            score += 30.0
            reasons.append("Tendência de alta perfeita (Preço > EMA20 > EMA50 > EMA200).")
        elif price > ema50:
            score += 15.0
            reasons.append("Preço acima da EMA50 em recuperação.")
        elif price < ema200:
            score -= 25.0
            reasons.append("Preço abaixo da EMA200 (tendência primária de baixa).")

        # RSI Momentum
        if 48.0 <= rsi <= 68.0:
            score += 15.0
            reasons.append(f"RSI {rsi:.1f} em zona de aceleração positiva saudável.")
        elif rsi > 75.0:
            score -= 20.0
            reasons.append(f"RSI {rsi:.1f} em sobrecompra extrema (risco de correção).")
        elif rsi < 35.0:
            score -= 15.0
            if price < ema50:
                veto = True
                reasons.append("Veto: Fraqueza técnica severa com perda de médias.")

        score = max(0.0, min(100.0, score))
        return {
            "score": round(score, 2),
            "veto": veto,
            "reasoning": " ".join(reasons) if reasons else "Indicadores em consolidação neutra."
        }

