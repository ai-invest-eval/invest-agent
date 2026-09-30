"""3-B: 시장 RAG + 필요 시 웹 보완. 2번의 사업 모델과 대표 시장은 보존."""

import os

from src.schemas import MarketAnalysisUpdate
from src.state import InvestmentState


def market_analysis(state: InvestmentState) -> MarketAnalysisUpdate:
    from src.agents.rag_analysis import RagAnalysisAgent, live_ask, live_web_search
    from src.rag.retrieval import HybridRetriever

    web = live_web_search if os.getenv("TAVILY_API_KEY") else None
    return RagAnalysisAgent(
        "market", HybridRetriever("market").search, live_ask(), web
    )(state)
