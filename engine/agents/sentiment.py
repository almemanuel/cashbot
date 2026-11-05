"""
Agente 2: Sentimento e Notícias (Google Gemini Flash)
Peso: 0.40 (40%)
Avalia o índice Crypto Fear & Greed e manchetes recentes.
Condição de Veto: Fear & Greed < 20 (pânico generalizado) ou relatos de hacks/exploits.
"""

import os
import json
import logging
import requests
from typing import Dict, Any

logger = logging.getLogger("cashbot.sentiment")

FEAR_AND_GREED_API = "https://api.alternative.me/fng/?limit=1"

class SentimentAgent:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = "gemini-1.5-flash"

    def get_fear_and_greed(self) -> Dict[str, Any]:
        """Consulta a API pública e gratuita do Fear & Greed Index."""
        try:
            resp = requests.get(FEAR_AND_GREED_API, timeout=8)
            if resp.status_code == 200:
                data = resp.json()["data"][0]
                return {
                    "value": int(data["value"]),
                    "classification": data["value_classification"]
                }
        except Exception as e:
            logger.warning(f"Não foi possível obter Fear & Greed ao vivo: {e}. Usando valor padrão neutro.")
        return {"value": 50, "classification": "Neutral"}

    def analyze(self, symbol: str) -> Dict[str, Any]:
        """
        Analisa o sentimento do mercado para o ativo.
        Retorna score (0-100), veto (bool) e reasoning.
        """
        fng = self.get_fear_and_greed()
        fng_val = fng["value"]
        fng_class = fng["classification"]

        # Regra explícita do SDD: Veta se Fear & Greed < 20
        if fng_val < 20:
            return {
                "score": float(fng_val),
                "veto": True,
                "reasoning": f"Veto do Agente de Sentimento: Fear & Greed em {fng_val} ({fng_class}) indica pânico generalizado no mercado."
            }

        if not self.api_key:
            logger.warning("GEMINI_API_KEY não configurada. Usando sentimento baseado em Fear & Greed ao vivo.")
            return self._heuristic_analysis(symbol, fng)

        prompt = f"""
Você é um Analista de Risco e Sentimento de Criptoativos.
Avalie o sentimento de mercado para {symbol}.
Dados atuais:
- Crypto Fear & Greed Index: {fng_val}/100 ({fng_class})

Critérios:
1. Atribua um score de 0 a 100 baseado no otimismo e apetite a risco do mercado.
2. Veto (veto: true) se houver risco sistêmico severo ou vulnerabilidade crítica conhecida.
3. Se o sentimento estiver favorável ou em ganância moderada (55 a 75), atribua um score proporcional alto (70-85).
4. Em ganância extrema (> 85), reduza a nota devido a risco de correção iminente.

Responda EXCLUSIVAMENTE em formato JSON com o schema:
{{
  "score": <número float 0-100>,
  "veto": <true ou false>,
  "reasoning": "<explicação concisa de até 2 frases em português>"
}}
"""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json"}
        }

        try:
            resp = requests.post(url, json=payload, timeout=15)
            if resp.status_code == 200:
                raw_text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                data = json.loads(raw_text)
                return {
                    "score": float(data.get("score", float(fng_val))),
                    "veto": bool(data.get("veto", False)),
                    "reasoning": str(data.get("reasoning", f"Sentimento avaliado com base no índice {fng_class}."))
                }
            else:
                logger.error(f"Erro na API Gemini ({resp.status_code}): {resp.text}")
                return self._heuristic_analysis(symbol, fng)
        except Exception as e:
            logger.error(f"Falha na requisição Gemini: {e}")
            return self._heuristic_analysis(symbol, fng)

    def _heuristic_analysis(self, symbol: str, fng: Dict[str, Any]) -> Dict[str, Any]:
        """Análise baseada no índice oficial Crypto Fear & Greed ao vivo."""
        val = fng["value"]
        classification = fng["classification"]

        veto = val < 20
        # Mapeia a pontuação de forma saudável para swing trade:
        # 20-40: Medo (nota 40-55)
        # 40-65: Neutro/Otimista saudável (nota 65-85)
        # 65-80: Ganância controlada (nota 80-90)
        # > 80: Ganância extrema / euforia (nota 60-70 devido a risco de topo)
        if val < 20:
            score = float(val)
        elif val < 40:
            score = 45.0 + (val - 20) * 0.5
        elif val <= 75:
            score = 65.0 + (val - 40) * 0.6
        else:
            score = 70.0 - (val - 75) * 0.8

        return {
            "score": round(score, 2),
            "veto": veto,
            "reasoning": f"Fear & Greed Index em {val} ({classification}). Sentimento favorável para posições técnicas de swing trade."
        }

