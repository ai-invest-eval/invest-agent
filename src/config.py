from datetime import timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    KST = ZoneInfo("Asia/Seoul")
except (ImportError, ZoneInfoNotFoundError):
    KST = timezone(timedelta(hours=9))

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAX_CANDIDATES = 15
LLM_MODEL = "gpt-4o-mini"
LLM_TEMPERATURE = 0
EMBEDDING_MODEL = "BAAI/bge-m3"


MAX_REPORT_ATTEMPTS = 3
MAX_REPORT_PAGES = 10
MAX_WORKER_ATTEMPTS = 2
DEFAULT_WORKER_CONCURRENCY = 3
MAX_FINAL_RENDER_PASSES = 8
QUALITY_ITEM_MAX_CHARS = 120


def max_steps(n: int) -> int:
    # Parent updates: orchestrator + N workers + 3*(writer+judge) + finalize.
    return n * 2 + 10


def calculate_recursion_limit(max_candidates: int) -> int:
    if max_candidates < 1:
        raise ValueError("최대 후보 수는 1 이상이어야 합니다.")
    # N parallel workers share a superstep; child graphs need 6, parent needs <= 9.
    return 24
