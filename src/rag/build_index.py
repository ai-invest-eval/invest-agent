"""Agent 3-A/3-B 담당자의 FAISS 색인 구현 골격."""

from pathlib import Path

from src.config import EMBEDDING_MODEL  # noqa: F401

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
TECHNOLOGY_DIR = DATA_DIR / "technology"
MARKET_DIR = DATA_DIR / "market"
INDEX_DIR = DATA_DIR / "index"
CHUNK_SIZE_TOKENS = 1000
CHUNK_OVERLAP_TOKENS = 200
TOP_K = 5


def build_indexes() -> None:
    # TODO(3-A/3-B 담당): 필요한 PDF/임베딩/FAISS 의존성 추가
    # TODO(3-A/3-B 담당): TECHNOLOGY_DIR, MARKET_DIR에서 PDF 로딩
    # TODO(3-A/3-B 담당): DOC_META에 제목·발행기관·연도·유형·URL·원문 쪽수 정의
    # TODO(3-A/3-B 담당): 논문 저자·학술지·권/호·수록 페이지, 웹 발행일·사이트명 보존
    # TODO(3-A/3-B 담당): 파일명 NFC 정규화·추출 공백 정리·agent/topic 태그 추가
    # TODO(3-A/3-B 담당): 1000토큰 청킹·200토큰 겹침, 임베딩 모델 토크나이저 사용
    # TODO(3-A/3-B 담당): EMBEDDING_MODEL Dense 벡터 생성 후 FAISS 저장
    # TODO(3-A/3-B 담당): 같은 청크에 Kiwi 형태소 분석+BM25 키워드 인덱스 생성
    # TODO(3-A/3-B 담당): Dense/BM25 각각 top-5를 RRF로 합쳐 최종 top-5 반환
    # TODO(3-A/3-B 담당): RRF 상수·영문/전문용어 토큰화·필터 인터페이스 확정
    # TODO(3-A/3-B 담당): 검색 결과의 근거 적합성·재검색 판단은 3-A/3-B의 LLM 담당
    # TODO(3-A/3-B 담당): INDEX_DIR/technology, INDEX_DIR/market에 색인 저장
    # TODO(3-A/3-B 담당): 기존 인덱스 재사용 및 문서 변경 시 재생성 정책 구현
    # TODO(3-A/3-B 담당): 20~30개 검색 평가셋으로 dense 후보 4개+하이브리드 비교
    raise NotImplementedError("Agent 3-A/3-B 담당자: RAG 색인 구현 예정")


if __name__ == "__main__":
    build_indexes()
