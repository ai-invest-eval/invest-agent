"""Agent 2 node contract; implementation belongs to its assigned developer."""

from src.schemas import CompanyProfileUpdate
from src.state import InvestmentState


def company_profile(state: InvestmentState) -> CompanyProfileUpdate:
    """입력: selected_startup.

    출력: startup_profile, references (State 변경분만 반환).
    """
    # TODO(2번): 공식 홈페이지·보도자료로 프로필과 채점용 항목 수집
    # TODO(2번): 플랫폼·파이프라인·팀·투자 이력·선급금·기업가치·관문 확인
    # TODO(2번): business_model(pipeline/platform) 분류 근거와 lead_indication 수집
    # TODO(2번): 정보 부족 시 검색어 변경 후 최대 1회 재검색
    # TODO(2번): 확인된 없음과 미확인 구분, missing_fields에 미확인 항목 기록
    # TODO(2번): None/정보 없음 표현은 schemas.py 필드 타입과 함께 확정
    raise NotImplementedError("Agent 2 구현 예정")
