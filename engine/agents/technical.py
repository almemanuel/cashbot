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
Você é um Day Trader Quantitativo Institucional operando no Timeframe de 15 Minutos (Spot Modo Perda Zero).
O objetivo é GIRO RÁPIDO INTRADAY (Scalp / Day Trade): capturar movimentos curtos e explosivos de +0.8% a +2.2% em minutos ou poucas horas, sem ficar preso em topos esticados.

Analise os dados quantitativos intradiários (15m) de {symbol}:
- Preço Atual: ${ind.current_price} | VWAP Intradiário (24h): ${ind.vwap}
- Bandas de Bollinger (20, 2): Superior ${ind.bb_upper} | Inferior ${ind.bb_lower}
- Volume Ratio (Fluxo Institucional vs Média): {ind.volume_ratio}x | Momentum 1h: {ind.momentum_1h_pct:+0.2f}%
- Máxima 24h: ${ind.recent_high_7d} (Espaço até topo: +{ind.upside_to_7d_high_pct}%) | Mínima 24h: ${ind.recent_low_7d}
- EMA 20 (15m): ${ind.ema20} | EMA 50 (15m): ${ind.ema50} | EMA 200 (15m): ${ind.ema200}
- RSI 14 (15m): {ind.rsi14} | ATR 14 (15m): ${ind.atr14}

Técnicas de Day Trade Quantitativo a aplicar:
1. GATILHO DE COMPRA DE ALTA PROBABILIDADE (Nota 68 a 94):
   - Pullback na VWAP ou EMA 20 com retomada compradora (RSI entre 38 e 64), OU
   - Reversão na Banda de Bollinger Inferior com defesa compradora, OU
   - Breakout com Volume Institucional (`volume_ratio >= 1.2x`) e espaço livre até a Banda Superior.
2. ALVO CURTO CIRÚRGICO (`take_profit_pct` entre `0.8` e `2.2`):
   - Escolha um alvo curto e rápido (ex: `0.9%` a `1.8%`) posicionado antes da resistência imediata / Banda de Bollinger Superior para realizar lucro rápido no próximo ciclo de 15 minutos!
3. VETO DE COMPRA DE TOPO (`veto: true` ou nota < 55):
   - Jamais compre ativo já esticado acima da Banda de Bollinger Superior com RSI > 72 (exaustão de topo).
4. REGRA DE LINGUAGEM PARA LEIGOS NO CAMPO `reasoning`:
   - Embora você faça toda a análise matemática acima, escreva o campo `reasoning` em **1 frase curta, simples e humana para um investidor leigo**, SEM usar siglas técnicas (`VWAP`, `EMA20`, `RSI`, `Bollinger`, `ATR`). Exemplo: "O preço deu uma recuada ficando barato e o volume de compras voltou a crescer com força, abrindo espaço para subir rápido."

Responda EXCLUSIVAMENTE em formato JSON com o seguinte schema:
{{
  "score": <número float de 0 a 100>,
  "veto": <true ou false>,
  "stop_loss_pct": <percentual técnico de referência entre 0.8 e 1.8>,
  "take_profit_pct": <percentual de alvo curto de day trade entre 0.8 e 2.2, ex: 1.2>,
  "reasoning": "<1 frase simples e direta em português para leigos, sem siglas técnicas, explicando por que a moeda tem chance de subir agora>"
}}
"""

    def _heuristic_analysis(self, symbol: str, indicators: Dict[str, Any]) -> Dict[str, Any]:
        """Motor heurístico quantitativo de Day Trade sem else e com 1 nível de indentação."""
        ind = self._to_indicators_domain(indicators)
        reasons: List[str] = []

        trend_delta = self._evaluate_trend(ind, reasons)
        rsi_delta = self._evaluate_momentum(ind, reasons)
        flow_delta = self._evaluate_order_flow(ind, reasons)
        veto = self._should_veto(ind, reasons)

        raw_score = 50.0 + trend_delta + rsi_delta + flow_delta
        clamped_score = max(0.0, min(100.0, raw_score))
        summary = " ".join(reasons[:2]) if reasons else "Preço estável aguardando maior fluxo comprador."

        return AgentVerdict(
            score=round(clamped_score, 2),
            veto=veto,
            reasoning=summary,
            stop_loss_pct=1.0,
            take_profit_pct=min(1.8, max(0.9, round(ind.upside_to_7d_high_pct * 0.45, 2))),
        ).to_dict()

    @staticmethod
    def _evaluate_order_flow(ind: TechnicalIndicators, reasons: List[str]) -> float:
        bonus = 0.0
        if ind.is_above_vwap:
            reasons.append("Os compradores estão dominando o preço nas últimas horas.")
            bonus += 6.0
        if ind.is_volume_breakout:
            reasons.append("Entrou bastante dinheiro novo comprando a moeda agora.")
            bonus += 8.0
        if ind.is_near_bb_lower_support:
            reasons.append("O preço recuou até uma faixa barata que costuma atrair compradores.")
            bonus += 8.0
        return bonus

    @staticmethod
    def _evaluate_trend(ind: TechnicalIndicators, reasons: List[str]) -> float:
        if ind.is_strong_uptrend:
            reasons.append("A moeda está em ritmo firme de valorização no curto prazo.")
            return 28.0
        if ind.is_above_ema50:
            reasons.append("O preço se mantém firme com bom espaço para subir.")
            return 18.0
        if ind.upside_to_7d_high_pct >= 2.0 and not ind.is_oversold:
            reasons.append(f"Está com bom desconto em relação à máxima do dia (+{ind.upside_to_7d_high_pct:.1f}% de espaço).")
            return 12.0
        return -10.0

    @staticmethod
    def _evaluate_momentum(ind: TechnicalIndicators, reasons: List[str]) -> float:
        if ind.is_healthy_momentum:
            reasons.append("Tem fôlego saudável para subir sem estar cara demais.")
            return 16.0
        if ind.is_overbought:
            reasons.append("Já subiu demais nas últimas horas e pode descansar.")
            return -20.0
        if ind.is_oversold:
            reasons.append("Caiu bastante recentemente e ainda busca estabilidade.")
            return -15.0
        return 8.0

    @staticmethod
    def _should_veto(ind: TechnicalIndicators, reasons: List[str]) -> bool:
        if ind.is_oversold and not ind.is_above_ema50:
            reasons.append("Momento de queda forte, melhor aguardar estabilizar.")
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
            vwap=float(indicators.get("vwap", indicators["current_price"])),
            bb_upper=float(indicators.get("bb_upper", 0.0)),
            bb_lower=float(indicators.get("bb_lower", 0.0)),
            volume_ratio=float(indicators.get("volume_ratio", 1.0)),
            momentum_1h_pct=float(indicators.get("momentum_1h_pct", 0.0)),
        )
