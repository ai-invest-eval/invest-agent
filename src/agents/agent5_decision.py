"""Agent 5 node contract; implementation belongs to its assigned developer."""

from src.schemas import InvestmentDecisionUpdate
from src.state import InvestmentState


def investment_decision(state: InvestmentState) -> InvestmentDecisionUpdate:
    """입력: selected_startup, startup_profile, tech_analysis, market_analysis, competitor_analysis, references.

    출력: investment_decision, evaluation_history (State 변경분만 반환).
    """
    # TODO(5번): QA~QO 1~5점·근거·출처·결측 여부를 구조화해 검증
    # TODO(5번): docs/investment_criteria_v4.md를 채점 기준으로 적용
    # TODO(5번): Judge reason/source를 공통 rationale/references로 매핑
    # TODO(5번): question_evidence에 QuestionEvidence 기록, question_scores와 동기화
    # TODO(5번): 영역 가중치·기준점·결측 기본점은 설정 파일로 분리
    # TODO(5번): 총점·결측 비중·최종 판정은 Python으로 계산
    # TODO(5번): 관문 → 결측 비중 → 총점/창업자 기준 순서로 판정
    # TODO(5번): 자격 관문 None은 보류, 리스크 관문 None은 평가 진행+미확인 표시
    # TODO(5번): 미확인 리스크 키를 unconfirmed_gates에 기록, 없으면 []
    # TODO(5번): 결측은 2점(QN/QO는 3점), QN/QO 결측도 결측 비중에 포함
    # TODO(5번): QD의 pipeline/platform별 기준표 선택, 총점75/창업자60/결측0.30 적용
    # TODO(5번): 2번의 business_model을 재분류하지 않고 unknown이면 QD만 결측2점 처리
    # TODO(5번): 영역 키 founder/market/product/moat/traction/deal 고정
    # TODO(5번): hold_reason은 v4 사유 사용, 판정 전 반올림·임의 사유 코드 추가 금지
    # TODO(5번): QN은 동일 단계 중앙값 대비 비율, 출처/비교 표본 미확보 시 결측3점
    # TODO(5번): QN은 v4대로 평가, 문서에 없는 24개월·최소3개 등 추가 조건 강제 금지
    # TODO(5번): QN 경계 중첩은 낮은 점수 적용, 상세 규칙은 docs/data_contracts.md
    # TODO(5번): 현재 기업 프로필·분석·판정을 복사해 평가 이력 한 건만 추가
    raise NotImplementedError("Agent 5 구현 예정")
