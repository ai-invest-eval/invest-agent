"""Agent 3-A node contract; implementation belongs to its assigned developer."""

from src.schemas import TechAnalysisUpdate
from src.state import InvestmentState


def tech_analysis(state: InvestmentState) -> TechAnalysisUpdate:
    """입력: selected_startup, startup_profile.

    출력: tech_analysis, references (State 변경분만 반환).
    """
    # TODO(3-A 담당): 기술 코퍼스에서 질문 계획·검색·근거 판단·최대 1회 재검색
    # TODO(3-A 담당): BGE-M3 Dense + Kiwi BM25를 RRF로 결합한 검색 사용
    # TODO(3-A 담당): AI 진위·실험/임상 검증·파이프라인·신약 규제 리스크 분석
    # TODO(3-A 담당): agent/topic 필터 적용, 사용한 청크 출처만 references에 추가
    # TODO(3-A 담당): 근거 부족 시 사실 생성 대신 미확인으로 표시
    raise NotImplementedError("Agent 3-A 구현 예정")
