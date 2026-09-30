"""Agent 2 node contract; implementation belongs to its assigned developer."""

from src.schemas import CompanyProfileUpdate
from src.state import InvestmentState


def company_profile(state: InvestmentState) -> CompanyProfileUpdate:
    """입력: selected_startup.

    출력: startup_profile, references (State 변경분만 반환).
    """
    # TODO(2번): 공식 홈페이지·보도자료로 프로필과 채점용 항목 수집
    # TODO(2번): 플랫폼·파이프라인·팀·투자 이력·선급금·기업가치·관문 확인
    # TODO(2번): 권리 보유 자체 후보물질이면 pipeline, 자체 후보 없이 서비스 주 사업이면 platform
    # TODO(2번): 사업 모델 재검색 후에도 미확인이면 unknown, business_model_basis+출처 기록
    # TODO(2번): 혼합 사업도 자체 후보물질 있으면 pipeline, 제약사 소유 공동개발 물질 제외
    # TODO(2번): pipeline은 최선행 자체 적응증 1개, 동률이면 공식 자료 첫 소개 항목 선택
    # TODO(2번): platform은 최다 공개 계약 서비스 1개, 미확인이면 AI 신약 개발 서비스
    # TODO(2번): 대표 시장은 lead_indication/lead_service에 저장, 비해당 필드는 None
    # TODO(2번): 정보 부족 시 검색어 변경 후 최대 1회 재검색
    # TODO(2번): 확인된 없음과 미확인 구분, missing_fields에 미확인 항목 기록
    # TODO(2번): 미확인은 None, 확인된 없음은 []·False·0으로 구분, 선택 필드 키 유지
    # TODO(2번): docs/data_contracts.md의 MonetaryAmount·날짜·개발 단계 규칙 적용
    # TODO(2번): Phase 1/2·1-2상 → 임상 1/2상, Phase 2/3·2-3상 → 임상 2/3상 보존
    # TODO(2번): 임상 1/2상을 2상 완료로 해석 금지, 원문과 실제 진행 근거 확인
    # TODO(2번): docs/investment_criteria_v4.md의 채점용 프로필 필드 수집
    # TODO(2번): FundingRound/Investor/Partnership/TeamMember 계약과 항목별 references 적용
    # TODO(2번): 선급금 요약은 최신 일자 확인된 양수 계약 선택, 합산 금지·basis 기록
    # TODO(2번): 기업가치는 최신 확인된 pre-money와 valuation_date/references 기록
    raise NotImplementedError("Agent 2 구현 예정")
