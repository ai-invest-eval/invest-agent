"""3-A: 기술 RAG → 근거 판단·최대 1회 재검색 → QG/QH·규제 분석."""

from src.schemas import TechAnalysisUpdate
from src.state import InvestmentState


def tech_analysis(state: InvestmentState) -> TechAnalysisUpdate:
    from src.agents.rag_analysis import RagAnalysisAgent, live_ask
    from src.rag.retrieval import HybridRetriever

    return RagAnalysisAgent("tech", HybridRetriever("tech").search, live_ask())(state)
