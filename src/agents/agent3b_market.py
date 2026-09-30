"""Agent 3-B node contract; implementation belongs to its assigned developer."""

from src.schemas import MarketAnalysisUpdate
from src.state import InvestmentState


def market_analysis(state: InvestmentState) -> MarketAnalysisUpdate:
    """입력: selected_startup, startup_profile.

    출력: market_analysis, references (State 변경분만 반환).
    """
    # TODO(3-B 담당): 시장 코퍼스 검색, 근거 부족 시 최대 1회 재검색
    # TODO(3-B 담당): BGE-M3 Dense + Kiwi BM25를 RRF로 결합한 검색 사용
    # TODO(3-B 담당): 주력 적응증 시장 규모(QD)에 수치·단위·연도·출처·정의 기재
    # TODO(3-B 담당): 치료 영역 수치와 세부 적응증 수치 구분, 없는 정보는 웹 보완
    # TODO(3-B 담당): QD는 pipeline이면 M7 치료 시장, platform이면 M1/M6 서비스 시장
    # TODO(3-B 담당): 제약사 수요·파트너십·Exit 환경 분석, 사용 출처만 추가
    raise NotImplementedError("Agent 3-B 구현 예정")
