"""Agent 5 node contract; implementation belongs to its assigned developer."""

from src.schemas import InvestmentDecisionUpdate
from src.state import InvestmentState


def investment_decision(state: InvestmentState) -> InvestmentDecisionUpdate:
    """입력: selected_startup, startup_profile, tech_analysis, market_analysis, competitor_analysis, references.

    출력: investment_decision, evaluation_history (State 변경분만 반환).
    """
    # TODO(5번): QA~QO 1~5점·근거·출처·결측 여부를 구조화해 검증
    # TODO(5번): question_evidence에 QuestionEvidence 기록, question_scores와 동기화
    # TODO(5번): 영역 가중치·기준점·결측 기본점은 설정 파일로 분리
    # TODO(5번): 총점·결측 비중·최종 판정은 Python으로 계산
    # TODO(5번): 관문 → 결측 비중 → 총점/창업자 기준 순서로 판정
    # TODO(5번): 자격 관문 None은 보류, 리스크 관문 None은 평가 진행+미확인 표시
    # TODO(5번): 결측은 2점(QN/QO는 3점), QN/QO 결측도 결측 비중에 포함
    # TODO(5번): QD의 pipeline/platform별 기준표 선택, 총점75/창업자60/결측0.30 적용
    # TODO(5번): 현재 기업 프로필·분석·판정을 복사해 평가 이력 한 건만 추가
    raise NotImplementedError("Agent 5 구현 예정")
