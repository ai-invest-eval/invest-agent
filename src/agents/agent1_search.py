"""Agent 1 node contract; implementation belongs to its assigned developer."""

from src.schemas import StartupSearchUpdate
from src.state import InvestmentState


def startup_search(state: InvestmentState) -> StartupSearchUpdate:
    """입력: input_keyword, max_candidates, candidate_startups, evaluation_history.

    출력: 후보 목록·선택 기업·새 출처 및 현재 분석값 초기화 (State 변경분).
    """
    # TODO(1번): Tavily로 AI 신약개발 기업 탐색, 자격 검증·중복 제거
    # TODO(1번): LLM이 출처 근거로 한영 별칭·동일 기업 여부 판단, 대표 이름 유지
    # TODO(1번): 후보 0개 원인을 근거로 판단해 남기고 selected_startup=None 반환
    # TODO(1번): 비상장·Seed~Series C·Exit 전·대기업 자회사 제외 조건 확인
    # TODO(1번): docs/data_contracts.md의 국내/해외 단계 표기·원문·투자 시장 저장
    # TODO(1번): F 접미사는 단계 순위에서 제외, 단계/자격 미확인 기업을 적격으로 추정 금지
    # TODO(1번): 최초 실행에서 max_candidates 이내로 후보 목록 확정
    # TODO(1번): 5 → 1 재진입은 새 검색 없이 evaluation_history에 없는 후보 선택
    # TODO(1번): 후보가 없으면 selected_startup=None 반환
    # TODO(1번): 후보 선택 시 프로필·분석·현재 판정만 초기화, 누적값은 보존
    # TODO(1번): API 오류와 검색 결과 없음 구분, 재탐색 시 별도 횟수 제한
    raise NotImplementedError("Agent 1 구현 예정")
