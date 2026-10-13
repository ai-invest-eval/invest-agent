"""결정 로그: 실행 중 "왜 그렇게 판단했는지"를 State 밖 JSONL 파일에 남긴다.

원칙
- State에는 로그 본문을 넣지 않는다. State에는 판정 결과(eval_result)와 Worker 결과 요약(worker_results)만 두고,
  계획 근거·재시도/제외 사유·소요 시간·품질 판정 사유는 outputs/trace/{trace_id}.jsonl에 한 줄씩 쌓는다.
- trace_id 하나로 State, 이 로그, LangSmith metadata.trace_id, 체크포인트 thread_id를 잇는다.
- 로그 기록은 그래프 실행을 막지 않는다. 파일 쓰기에 실패해도 예외를 올리지 않는다.
- API 키는 파일에 쓰기 전에 [REDACTED]로 가린다.
- LangSmith는 환경변수(LANGSMITH_TRACING, LANGSMITH_API_KEY, LANGSMITH_PROJECT)로만 켠다.
  이 모듈은 LangSmith를 직접 호출하지 않는다.
"""

import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path

from src.config import PROJECT_ROOT

TRACE_DIR = PROJECT_ROOT / "outputs" / "trace"
# 병렬 Worker가 같은 파일에 동시에 append해도 줄이 섞이지 않게 한다.
_LOCK = threading.Lock()
_SECRET_ENV = ("OPENAI_API_KEY", "TAVILY_API_KEY", "LANGSMITH_API_KEY")
# 환경변수에 없더라도 키 형태 문자열은 가린다.
_SECRET_PATTERN = re.compile(r"(sk-[A-Za-z0-9_\-]{16,}|tvly-[A-Za-z0-9_\-]{16,}|lsv2_[A-Za-z0-9_\-]{16,})")
_SAFE_ID = re.compile(r"[^A-Za-z0-9_\-]")


def _redact(text: str) -> str:
    for name in _SECRET_ENV:
        secret = (os.getenv(name) or "").strip().strip('"')
        if len(secret) >= 8:
            text = text.replace(secret, "[REDACTED]")
    return _SECRET_PATTERN.sub("[REDACTED]", text)


def trace_path(trace_id: str, directory: Path | None = None) -> Path:
    """trace_id를 파일명으로 쓸 수 있게 정리한다(경로 조작 방지)."""
    safe = _SAFE_ID.sub("_", trace_id or "") or "no_trace"
    return (directory or TRACE_DIR) / f"{safe}.jsonl"


def log_decision(
    trace_id: str,
    node: str,
    decision: str,
    reason,
    *,
    directory: Path | None = None,
    **extra,
) -> None:
    """결정 한 건을 JSONL 한 줄로 남긴다. extra에는 task_id·attempts·duration_ms 등을 넣는다."""
    record = {
        "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
        "trace_id": trace_id,
        "node": node,
        "decision": decision,
        "reason": reason,
        **extra,
    }
    try:
        line = _redact(json.dumps(record, ensure_ascii=False, default=str))
        path = trace_path(trace_id, directory)
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
    except OSError:
        # 관측성 실패가 평가 실행을 멈추게 하지 않는다.
        return


def read_trace(trace_id: str, directory: Path | None = None) -> list[dict]:
    path = trace_path(trace_id, directory)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def summarize_trace(trace_id: str, directory: Path | None = None) -> dict:
    """Worker별 소요 시간·상태와 가장 느린 Worker(병목 브랜치)를 요약한다(강의 06편 C-3 ⑥)."""
    workers: dict[str, dict] = {}
    for record in read_trace(trace_id, directory):
        if record.get("node") != "worker" or record.get("duration_ms") is None:
            continue
        key = str(record.get("task_id") or record.get("company") or len(workers))
        workers[key] = {
            "task_id": record.get("task_id"),
            "company": record.get("company"),
            "status": record.get("decision"),
            "attempts": record.get("attempts"),
            "duration_ms": record.get("duration_ms"),
        }
    rows = sorted(workers.values(), key=lambda r: r["duration_ms"] or 0, reverse=True)
    return {
        "trace_id": trace_id,
        "worker_count": len(rows),
        "done": sum(1 for r in rows if r["status"] == "done"),
        "excluded": sum(1 for r in rows if r["status"] == "excluded"),
        "slowest": rows[0] if rows else None,
        "workers": rows,
    }
