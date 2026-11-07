"""
Agente 1: Análise Técnica (Groq API - Descoberta Dinâmica do Melhor Modelo)
Peso: 0.60 (60%)
Avalia estrutura de preço, médias móveis (EMA 20, 50, 200), RSI 14 e volatilidade ATR.
Segue Object Calisthenics (1 nível de indentação por método, sem else, domínio encapsulado)
e resolve o modelo 1 única vez por ciclo (sem N+1).
"""

import os
import re
import json
import logging
from typing import Dict, Any, Optional, List
import requests

from domain import TechnicalIndicators, AgentVerdict

logger = logging.getLogger("cashbot.technical")

GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"

EXCLUDED_MODEL_TOKENS = (
    "whisper", "guard", "safeguard", "orpheus", "tts", "embed", "audio", "vision"
)
PREFERRED_FAMILY_BONUSES = {
    "gpt-oss": 25.0,
    "llama": 20.0,
    "qwen": 18.0,
    "deepseek": 18.0,
    "mixtral": 12.0,
}


class TechnicalAgent:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.explicit_model = model or os.getenv("GROQ_MODEL")
        self._ranked_models: List[str] = []

    def resolve_ranked_models(self) -> List[str]:
        """
        Descobre dinamicamente os modelos de texto disponíveis na conta Groq,
        ordenados do mais capaz ao mais leve, com cache por ciclo (zero N+1).
        """
        if self.explicit_model:
            return [self.explicit_model]
        if self._ranked_models:
            return self._ranked_models

        available = self._fetch_available_models()
        candidates = [m for m in available if self._is_chat_llm(m)]
        self._ranked_models = self._rank_candidates(candidates)
        logger.info(f"Fila de modelos Groq ranqueados: {self._ranked_models}")
        return self._ranked_models

    def _fetch_available_models(self) -> List[str]:
        if not self.api_key:
            return []
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            resp = requests.get(GROQ_MODELS_URL, headers=headers, timeout=8)
            return self._parse_models_list(resp)
        except Exception as e:
            logger.warning(f"Não foi possível listar modelos da Groq: {e}")
            return []

    @staticmethod
    def _parse_models_list(resp: requests.Response) -> List[str]:
        if resp.status_code != 200:
            return []
        items = resp.json().get("data", [])
        return [str(item.get("id", "")) for item in items if item.get("id")]

    @staticmethod
    def _is_chat_llm(model_id: str) -> bool:
        lower_id = model_id.lower()
        return not any(token in lower_id for token in EXCLUDED_MODEL_TOKENS)

    def _rank_candidates(self, candidates: List[str]) -> List[str]:
        if not candidates:
            return ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]
        return sorted(candidates, key=self._score_model_capability, reverse=True)

    @staticmethod
    def _score_model_capability(model_id: str) -> float:
        """Pontua o modelo pelo número de parâmetros (ex: 120b -> 120) + bônus da família."""
        lower_id = model_id.lower()
        param_match = re.search(r"(\d+)b\b", lower_id)
        param_score = float(param_match.group(1)) if param_match else 10.0
        family_bonus = sum(
            bonus for fam, bonus in PREFERRED_FAMILY_BONUSES.items() if fam in lower_id
        )
        return param_score + family_bonus

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
        prompt = self._build_prompt(symbol, ind)
        for model_name in list(self.resolve_ranked_models()):
            verdict = self._try_groq_model(model_name, prompt)
            if verdict is not None:
                return verdict
            self._demote_failed_model(model_name)
        return None

    def _demote_failed_model(self, model_name: str) -> None:
        if model_name not in self._ranked_models:
            return
        self._ranked_models.remove(model_name)
        self._ranked_models.append(model_name)

    def _try_groq_model(self, model_name: str, prompt: str) -> Optional[AgentVerdict]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "Você é um motor JSON estrito de análise técnica para criptoativos."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"}
        }
        try:
            resp = requests.post(GROQ_ENDPOINT, headers=headers, json=payload, timeout=15)
            return self._parse_groq_response(resp, model_name)
        except Exception as e:
            logger.error(f"Falha na requisição Groq ({model_name}): {e}")
            return None

    def _parse_groq_response(self, resp: requests.Response, model_name: str) -> Optional[AgentVerdict]:
        if resp.status_code != 200:
            logger.warning(f"Modelo Groq {model_name} indisponível ({resp.status_code}), tentando próximo da fila...")
            return None
        content = self._extract_groq_content(resp.json())
        data = json.loads(content)
        return AgentVerdict(
            score=float(data.get("score", 50.0)),
            veto=bool(data.get("veto", False)),
            reasoning=str(data.get("reasoning", f"Análise via {model_name} concluída.")),
            stop_loss_pct=float(data.get("stop_loss_pct", 2.5)),
            take_profit_pct=float(data.get("take_profit_pct", 5.0)),
        )

    @staticmethod
    def _extract_groq_content(payload: Dict[str, Any]) -> str:
        choices = payload.get("choices", [{}])
        message = choices[0].get("message", {})
        return str(message.get("content", "{}"))

    @staticmethod
    def _build_prompt(symbol: str, ind: TechnicalIndicators) -> str:
        return f"""
Você é um Trader Quantitativo especialista em GIRO RÁPIDO (Short-Term Swing / Tiro Curto em Spot).
O objetivo NÃO é segurar posição por semanas, e sim capturar lucros rápidos de curto prazo (+3% a +8%) com alta probabilidade de execução para gerar caixa rápido.

Analise os dados atuais de {symbol}:
- Preço Atual: ${ind.current_price}
- Máxima de 7 dias (Resistência curta): ${ind.recent_high_7d} (Espaço até o topo: +{ind.upside_to_7d_high_pct}%)
- Mínima de 7 dias (Suporte curto): ${ind.recent_low_7d}
- EMA 20: ${ind.ema20} | EMA 50: ${ind.ema50} | EMA 200: ${ind.ema200}
- RSI 14: {ind.rsi14} | ATR 14: ${ind.atr14}

Critérios de avaliação para Giro Rápido:
1. Priorize ativos com fôlego imediato para subir de +3.5% a +8.0% nos próximos 1 a 3 dias (repique de suporte com RSI entre 36 e 58, ou aceleração acima da EMA 20 com espaço até a máxima de 7d): nota 70 a 92.
2. Defina `stop_loss_pct` (entre 1.5 e 4.2) posicionado de forma inteligente abaixo do suporte imediato.
3. Defina `take_profit_pct` (entre 3.2 e 8.0, sendo pelo menos 1.5x o stop_loss_pct) em um nível realista que bata rápido (antes de travar na resistência).
4. VETO (veto: true) se o ativo estiver esticado demais no topo (RSI > 80) ou em colapso sem suporte (RSI < 28).

Responda EXCLUSIVAMENTE em formato JSON com o seguinte schema:
{{
  "score": <número float de 0 a 100>,
  "veto": <true ou false>,
  "stop_loss_pct": <percentual de stop loss sugerido, ex: 2.5>,
  "take_profit_pct": <percentual de alvo de lucro rápido sugerido, ex: 5.2>,
  "reasoning": "<explicação direta em 1 ou 2 frases em português sobre o gatilho rápido e o alvo escolhido>"
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
            reasoning=summary,
            stop_loss_pct=2.5,
            take_profit_pct=min(7.5, max(4.2, ind.upside_to_7d_high_pct)),
        ).to_dict()

    @staticmethod
    def _evaluate_trend(ind: TechnicalIndicators, reasons: List[str]) -> float:
        if ind.is_strong_uptrend:
            reasons.append("Fôlego comprador alinhado no curto prazo (Preço > EMA20 > EMA50).")
            return 28.0
        if ind.is_above_ema50:
            reasons.append("Preço sustentado acima da EMA50 com espaço para repique rápido.")
            return 18.0
        if ind.upside_to_7d_high_pct >= 4.0 and not ind.is_oversold:
            reasons.append(f"Desconto tático com +{ind.upside_to_7d_high_pct:.1f}% de espaço até o topo de 7 dias.")
            return 12.0
        return -10.0

    @staticmethod
    def _evaluate_momentum(ind: TechnicalIndicators, reasons: List[str]) -> float:
        if ind.is_healthy_momentum:
            reasons.append(f"RSI {ind.rsi14:.1f} com tração ideal para tiro curto.")
            return 16.0
        if ind.is_overbought:
            reasons.append(f"RSI {ind.rsi14:.1f} esticado no curto prazo.")
            return -20.0
        if ind.is_oversold:
            reasons.append(f"RSI {ind.rsi14:.1f} em sobrevenda acentuada.")
            return -15.0
        return 8.0

    @staticmethod
    def _should_veto(ind: TechnicalIndicators, reasons: List[str]) -> bool:
        if ind.is_oversold and not ind.is_above_ema50:
            reasons.append("Veto: Queda forte sem sinal de exaustão vendedora.")
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
            recent_high_7d=float(indicators.get("recent_high_7d", indicators["current_price"])),
            recent_low_7d=float(indicators.get("recent_low_7d", indicators["current_price"])),
        )
