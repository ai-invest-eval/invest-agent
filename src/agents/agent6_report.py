"""Agent 6 node contract; implementation belongs to its assigned developer."""

from src.schemas import ReportUpdate
from src.state import InvestmentState


def report_writer(state: InvestmentState) -> ReportUpdate:
    """입력: evaluation_history, references.

    출력: final_report (State 변경분만 반환).
    """
    # TODO(6번): 코드로 총점 → 창업자 영역 → 시장성 영역 순 정렬
    # TODO(6번): 통과 기업 중 1위만 상세 분석, 나머지 판정 사유와 순위표 작성
    # TODO(6번): 전 후보 총점·판정 표시, 영역별 6개 점수는 통과 기업만 표시
    # TODO(6번): 통과 없음/후보 없음 보고서 정책 구현
    # TODO(6번): 상세 분석은 선택 기업의 평가 이력과 실제 사용 출처에서 작성
    # TODO(6번): question_evidence로 질문별 점수 설명과 정보 부족 표시
    # TODO(6번): 리스크 관문 None과 공개 정보 대리 지표의 한계 명시
    # TODO(6번): SUMMARY 첫 섹션, REFERENCE 마지막, PDF 5장 이내 검증
    # TODO(6번): Markdown → HTML → WeasyPrint PDF 출력과 한글 폰트 설정
    raise NotImplementedError("Agent 6 구현 예정")
