from datetime import timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo

    KST = ZoneInfo("Asia/Seoul")
except Exception:
    KST = timezone(timedelta(hours=9))

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAX_CANDIDATES = 15
LLM_MODEL = "gpt-4o-mini"
LLM_TEMPERATURE = 0
EMBEDDING_MODEL = "BAAI/bge-m3"

# 후보당 1→2→(3a·3b)→4→5의 5 superstep. 8로 여유를 두고 종료 비용은 별도 확보.
STEPS_PER_CANDIDATE = 8
EXTRA_STEPS = 10


def calculate_recursion_limit(max_candidates: int) -> int:
    """최대 후보 수에 비례한 전체 그래프 실행 상한."""
    if max_candidates < 1:
        raise ValueError("최대 후보 수는 1 이상이어야 합니다.")
    return max_candidates * STEPS_PER_CANDIDATE + EXTRA_STEPS
