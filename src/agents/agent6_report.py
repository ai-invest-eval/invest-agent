"""Agent 6 node contract; implementation belongs to its assigned developer."""

from src.schemas import ReportUpdate
from src.state import InvestmentState


def report_writer(state: InvestmentState) -> ReportUpdate:
    """입력: evaluation_history, references.

    출력: final_report (State 변경분만 반환).
    """
    # TODO(6번): 코드로 총점 → 창업자 영역 → 시장성 영역 순 정렬
    # TODO(6번): v4에 없는 추가 동점 기준 금지, 판정·정렬은 반올림 전 값 사용
    # TODO(6번): 통과 기업 중 1위만 상세 분석, 나머지 판정 사유와 순위표 작성
    # TODO(6번): 전 후보 총점·판정 표시, 영역별 6개 점수는 통과 기업만 표시
    # TODO(6번): 후보 없음/통과 없음은 LLM이 실제 탐색·평가 근거로 설명, 추천 기업 생성 금지
    # TODO(6번): 상세 분석은 선택 기업의 평가 이력과 실제 사용 출처에서 작성
    # TODO(6번): question_evidence로 질문별 점수 설명과 정보 부족 표시
    # TODO(6번): business_model unknown은 사업 모델 미확인으로 정보 부족 표시
    # TODO(6번): 리스크 관문 None과 공개 정보 대리 지표의 한계 명시
    # TODO(6번): unconfirmed_gates 사용, 결측 None은 보고서에서 정보 부족으로 표시
    # TODO(6번): 해외 금액 N원/M달러·국내 N원, 환율 가정/미환산 표시는 공통 계약 적용
    # TODO(6번): SUMMARY 첫 섹션, REFERENCE 마지막, PDF 5장 이내 검증
    # TODO(6번): 실제 보고서에 사용한 자료만 기관 보고서/학술 논문/웹페이지로 구분
    # TODO(6번): docs/data_contracts.md의 REFERENCE 형식 적용, 조회만 한 자료 제외
    # TODO(6번): 저자·발행일·학술지·URL 미확인은 생성하지 말고 미확인으로 표시
    # TODO(6번): Markdown → HTML → WeasyPrint PDF 출력과 한글 폰트 설정
    raise NotImplementedError("Agent 6 구현 예정")
