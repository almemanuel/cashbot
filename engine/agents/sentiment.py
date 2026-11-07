"""
Agente 2: Sentimento e Notícias (Google Gemini Flash)
Peso: 0.40 (40%)
Avalia o índice Crypto Fear & Greed (com cache por ciclo para evitar N+1) e manchetes recentes.
Segue Object Calisthenics (1 nível de indentação por método, sem else, coleções encapsuladas).
"""

import os
import json
import logging
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus
from typing import Dict, Any, List, Optional
import requests

from domain import FearAndGreed, AgentVerdict, HeadlineCollection

logger = logging.getLogger("cashbot.sentiment")

FEAR_AND_GREED_API = "https://api.alternative.me/fng/?limit=1"
CRYPTOCOMPARE_NEWS_API = "https://min-api.cryptocompare.com/data/v2/news/"

COIN_NAMES = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "SOL": "Solana",
}

CRITICAL_VETO_KEYWORDS = [
    "hacked", "exploit", "drained", "network halt", "network outage",
    "insolvency", "bankrupt", "rug pull", "critical vulnerability"
]

POSITIVE_NEWS_KEYWORDS = [
    "etf", "inflow", "adoption", "upgrade", "partnership", "surge",
    "rally", "bullish", "all-time high", "ath", "institutional", "breakout"
]

NEGATIVE_NEWS_KEYWORDS = [
    "lawsuit", "sec", "ban", "crash", "plunge", "outflow",
    "bearish", "liquidation", "hack", "outage", "delay", "investigation"
]


class SentimentAgent:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = "gemini-1.5-flash"
        self._fng_cache: Optional[FearAndGreed] = None
        self._news_cache: Dict[str, List[str]] = {}

    def reset_cycle_cache(self) -> None:
        """Limpa o cache em memória no início de um novo ciclo operacional."""
        self._fng_cache = None
        self._news_cache.clear()

    def prefetch_market_context(self, symbols: List[str], limit_per_symbol: int = 5) -> None:
        """
        Pré-carrega Fear & Greed (1 request) e notícias da Watchlist em lote (1 request)
        eliminando completamente o problema de N+1 requisições HTTP no loop de ativos.
        """
        self.reset_cycle_cache()
        self.get_fear_and_greed()
        self._prefetch_cryptocompare_batch(symbols, limit_per_symbol)

    def get_fear_and_greed(self) -> Dict[str, Any]:
        """Retorna o índice Fear & Greed usando cache por ciclo (evita N+1)."""
        if self._fng_cache is not None:
            return self._fng_cache.to_dict()

        self._fng_cache = self._fetch_fear_and_greed_remote()
        return self._fng_cache.to_dict()

    def get_recent_news(self, symbol: str, limit: int = 5) -> List[str]:
        """Retorna as manchetes recentes do ativo a partir do cache de lote ou busca pontual."""
        base_asset = self._extract_base_asset(symbol)
        if base_asset in self._news_cache:
            return self._news_cache[base_asset][:limit]

        headlines = self._fetch_cryptocompare_single(base_asset, limit)
        if not headlines:
            headlines = self._fetch_google_rss_news(base_asset, limit)

        self._news_cache[base_asset] = headlines
        return headlines

    def analyze(self, symbol: str) -> Dict[str, Any]:
        """
        Analisa o sentimento macro (Fear & Greed) + manchetes recentes do ativo.
        Retorna dict compatível com AgentVerdict (score, veto, reasoning).
        """
        fng_dict = self.get_fear_and_greed()
        fng = FearAndGreed(value=int(fng_dict["value"]), classification=str(fng_dict["classification"]))
        headlines = HeadlineCollection(self.get_recent_news(symbol, limit=5))

        if fng.is_extreme_panic:
            verdict = AgentVerdict(
                score=float(fng.value),
                veto=True,
                reasoning=f"Veto do Agente de Sentimento: Fear & Greed em {fng.value} ({fng.classification}) indica pânico generalizado."
            )
            return verdict.to_dict()

        if not self.api_key:
            logger.warning("GEMINI_API_KEY não configurada. Usando sentimento baseado em Fear & Greed + manchetes ao vivo.")
            return self._heuristic_analysis(symbol, fng_dict, headlines.top(5))

        llm_verdict = self._request_gemini_analysis(symbol, fng, headlines)
        if llm_verdict is not None:
            return llm_verdict.to_dict()

        return self._heuristic_analysis(symbol, fng_dict, headlines.top(5))

    def _fetch_fear_and_greed_remote(self) -> FearAndGreed:
        try:
            resp = requests.get(FEAR_AND_GREED_API, timeout=8)
            return self._parse_fng_response(resp)
        except Exception as e:
            logger.warning(f"Não foi possível obter Fear & Greed ao vivo: {e}. Usando valor padrão neutro.")
            return FearAndGreed(value=50, classification="Neutral")

    def _parse_fng_response(self, resp: requests.Response) -> FearAndGreed:
        if resp.status_code != 200:
            return FearAndGreed(value=50, classification="Neutral")
        first_entry = resp.json().get("data", [{}])[0]
        return FearAndGreed(
            value=int(first_entry.get("value", 50)),
            classification=str(first_entry.get("value_classification", "Neutral"))
        )

    def _prefetch_cryptocompare_batch(self, symbols: List[str], limit_per_symbol: int) -> None:
        base_assets = [self._extract_base_asset(s) for s in symbols]
        categories_param = ",".join(base_assets)
        try:
            resp = requests.get(
                CRYPTOCOMPARE_NEWS_API,
                params={"categories": categories_param, "lang": "EN"},
                timeout=8
            )
            self._distribute_batch_news(resp, base_assets, limit_per_symbol)
        except Exception as e:
            logger.debug(f"Prefetch em lote de notícias indisponível: {e}")

    def _distribute_batch_news(self, resp: requests.Response, base_assets: List[str], limit: int) -> None:
        if resp.status_code != 200:
            return
        raw_items = resp.json().get("Data", [])
        if not isinstance(raw_items, list):
            return
        for asset in base_assets:
            self._news_cache[asset] = self._filter_items_for_asset(raw_items, asset, limit)

    def _filter_items_for_asset(self, items: List[Dict[str, Any]], asset: str, limit: int) -> List[str]:
        collection = HeadlineCollection()
        coin_name = COIN_NAMES.get(asset, asset).lower()
        for item in items:
            self._append_if_matches_asset(collection, item, asset, coin_name)
        return collection.top(limit)

    def _append_if_matches_asset(self, collection: HeadlineCollection, item: Dict[str, Any], asset: str, coin_name: str) -> None:
        categories = str(item.get("categories", "")).upper()
        title = str(item.get("title", ""))
        if asset not in categories and coin_name not in title.lower():
            return
        source = str(item.get("source_info", {}).get("name", ""))
        collection.add(title, source)

    def _fetch_cryptocompare_single(self, base_asset: str, limit: int) -> List[str]:
        try:
            resp = requests.get(
                CRYPTOCOMPARE_NEWS_API,
                params={"categories": base_asset, "lang": "EN"},
                timeout=8
            )
            return self._extract_cryptocompare_titles(resp, limit)
        except Exception as e:
            logger.debug(f"CryptoCompare News indisponível para {base_asset}: {e}")
            return []

    def _extract_cryptocompare_titles(self, resp: requests.Response, limit: int) -> List[str]:
        if resp.status_code != 200:
            return []
        items = resp.json().get("Data", [])
        if not isinstance(items, list):
            return []
        collection = HeadlineCollection()
        for item in items[:limit]:
            source = str(item.get("source_info", {}).get("name", ""))
            collection.add(str(item.get("title", "")), source)
        return collection.top(limit)

    def _fetch_google_rss_news(self, base_asset: str, limit: int) -> List[str]:
        coin_name = COIN_NAMES.get(base_asset, base_asset)
        query = quote_plus(f"{coin_name} crypto when:2d")
        rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        try:
            resp = requests.get(rss_url, timeout=8, headers={"User-Agent": "CashBot/1.0"})
            return self._parse_rss_xml(resp, limit)
        except Exception as e:
            logger.warning(f"Não foi possível buscar notícias RSS para {base_asset}: {e}")
            return []

    def _parse_rss_xml(self, resp: requests.Response, limit: int) -> List[str]:
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)
        collection = HeadlineCollection()
        for item in root.findall("./channel/item")[:limit]:
            title_el = item.find("title")
            title_text = title_el.text if title_el is not None and title_el.text else ""
            collection.add(title_text)
        return collection.top(limit)

    def _request_gemini_analysis(self, symbol: str, fng: FearAndGreed, headlines: HeadlineCollection) -> Optional[AgentVerdict]:
        prompt = self._build_prompt(symbol, fng, headlines)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json"}
        }
        try:
            resp = requests.post(url, json=payload, timeout=15)
            return self._parse_gemini_response(resp, fng)
        except Exception as e:
            logger.error(f"Falha na requisição Gemini: {e}")
            return None

    def _parse_gemini_response(self, resp: requests.Response, fng: FearAndGreed) -> Optional[AgentVerdict]:
        if resp.status_code != 200:
            logger.error(f"Erro na API Gemini ({resp.status_code}): {resp.text}")
            return None
        raw_text = self._extract_gemini_text(resp.json())
        data = json.loads(raw_text)
        return AgentVerdict(
            score=float(data.get("score", float(fng.value))),
            veto=bool(data.get("veto", False)),
            reasoning=str(data.get("reasoning", f"Sentimento avaliado com base no índice {fng.classification} e notícias."))
        )

    @staticmethod
    def _extract_gemini_text(payload: Dict[str, Any]) -> str:
        candidates = payload.get("candidates", [{}])
        content = candidates[0].get("content", {})
        parts = content.get("parts", [{}])
        return str(parts[0].get("text", "{}"))

    @staticmethod
    def _build_prompt(symbol: str, fng: FearAndGreed, headlines: HeadlineCollection) -> str:
        return f"""
Você é um Analista de Risco, Sentimento e Notícias de Criptoativos.
Avalie o sentimento de mercado e o noticiário atual para {symbol}.

Dados atuais:
- Crypto Fear & Greed Index (Macro): {fng.value}/100 ({fng.classification})
- Últimas Manchetes de {symbol}:
{headlines.format_bullet_list()}

Critérios:
1. Atribua um score de 0 a 100 combinando o humor macro (Fear & Greed) e o impacto das manchetes específicas de {symbol}.
2. Veto (veto: true) IMEDIATO se as manchetes relatarem hack, exploit, parada na rede (outage/halt), insolvência ou risco sistêmico severo contra {symbol}.
3. Se o sentimento estiver favorável (55 a 75) e as notícias trouxerem catalisadores positivos (fluxo institucional, ETF, adoção, atualizações), atribua um score alto (75-90).
4. Em ganância extrema (> 85) ou notícias negativas relevantes, reduza a nota devido ao risco de correção.

Responda EXCLUSIVAMENTE em formato JSON com o schema:
{{
  "score": <número float 0-100>,
  "veto": <true ou false>,
  "reasoning": "<explicação concisa de até 2 frases em português citando o Fear & Greed e o tom das notícias>"
}}
"""

    def _heuristic_analysis(self, symbol: str, fng: Dict[str, Any], headlines: Optional[List[str]] = None) -> Dict[str, Any]:
        """Análise de contingência combinando Fear & Greed ao vivo e varredura léxica das manchetes."""
        val = int(fng["value"])
        classification = str(fng["classification"])
        collection = HeadlineCollection(headlines or [])

        critical_hit = collection.find_first_matching(CRITICAL_VETO_KEYWORDS)
        if critical_hit:
            return AgentVerdict(
                score=15.0,
                veto=True,
                reasoning=f"VETO DE NOTÍCIA CRÍTICA em {symbol}: '{critical_hit[:90]}...' (F&G: {val})."
            ).to_dict()

        base_score = self._compute_fng_base_score(val)
        news_delta = self._compute_news_delta(collection)
        final_score = max(0.0, min(100.0, base_score + news_delta))
        news_summary = self._format_news_summary(collection, news_delta)

        return AgentVerdict(
            score=round(final_score, 2),
            veto=val < 20,
            reasoning=f"F&G em {val} ({classification}). {news_summary}"
        ).to_dict()

    @staticmethod
    def _compute_fng_base_score(val: int) -> float:
        if val < 20:
            return float(val)
        if val < 40:
            return 45.0 + (val - 20) * 0.5
        if val <= 75:
            return 65.0 + (val - 40) * 0.6
        return 70.0 - (val - 75) * 0.8

    @staticmethod
    def _compute_news_delta(collection: HeadlineCollection) -> float:
        pos_hits = collection.count_keyword_hits(POSITIVE_NEWS_KEYWORDS)
        neg_hits = collection.count_keyword_hits(NEGATIVE_NEWS_KEYWORDS)
        raw_delta = (pos_hits * 3.5) - (neg_hits * 4.5)
        return max(-15.0, min(15.0, raw_delta))

    @staticmethod
    def _format_news_summary(collection: HeadlineCollection, news_delta: float) -> str:
        if collection.is_empty():
            return "Sem manchetes atípicas nas últimas 24h."
        top_headline = collection.top(1)[0][:82]
        tone = SentimentAgent._resolve_tone_label(news_delta)
        count = len(collection.top(10))
        return f"Noticiário {tone} ({count} manchetes; destaque: \"{top_headline}...\")."

    @staticmethod
    def _resolve_tone_label(news_delta: float) -> str:
        if news_delta > 0:
            return "otimista"
        if news_delta < 0:
            return "cauteloso"
        return "neutro"

    @staticmethod
    def _extract_base_asset(symbol: str) -> str:
        return symbol.split("/")[0].upper()
