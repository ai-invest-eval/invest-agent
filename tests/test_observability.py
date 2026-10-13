import json
import threading

from src.orchestration import observability as obs


def test_log_decision_appends_jsonl(tmp_path):
    obs.log_decision("t1", "orchestrator", "plan 2 tasks", "독립 평가", directory=tmp_path, tasks=[1, 2])
    obs.log_decision("t1", "worker", "done", "평가 완료", directory=tmp_path, task_id="t1:0", duration_ms=1200)

    records = obs.read_trace("t1", tmp_path)
    assert [r["node"] for r in records] == ["orchestrator", "worker"]
    assert records[0]["trace_id"] == "t1"
    assert records[0]["tasks"] == [1, 2]
    assert records[1]["duration_ms"] == 1200
    assert "ts" in records[0]


def test_api_keys_are_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-value-123456")
    obs.log_decision(
        "t2", "worker", "excluded", "error with sk-test-secret-value-123456",
        directory=tmp_path, note="tvly-dev-ABCDEFGHIJKLMNOPQRSTUV",
    )
    text = obs.trace_path("t2", tmp_path).read_text(encoding="utf-8")
    assert "sk-test-secret-value-123456" not in text
    assert "tvly-dev-ABCDEFGHIJKLMNOPQRSTUV" not in text
    assert text.count("[REDACTED]") == 2


def test_trace_id_cannot_escape_directory(tmp_path):
    path = obs.trace_path("../../etc/passwd", tmp_path)
    assert path.parent == tmp_path


def test_write_failure_does_not_raise(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    # 디렉터리 자리에 파일이 있어 쓰기 실패 → 예외 없이 무시
    obs.log_decision("t3", "finalize", "done", "ok", directory=blocker)


def test_parallel_writes_keep_lines_intact(tmp_path):
    def write(i):
        obs.log_decision("t4", "worker", "done", "x" * 2000, directory=tmp_path, task_id=f"t4:{i}")

    threads = [threading.Thread(target=write, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = obs.trace_path("t4", tmp_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 20
    assert all(json.loads(line)["node"] == "worker" for line in lines)


def test_summarize_trace_finds_slowest_worker(tmp_path):
    obs.log_decision("t5", "orchestrator", "plan 3 tasks", "", directory=tmp_path)
    obs.log_decision("t5", "worker", "done", "", directory=tmp_path, task_id="t5:0", company="A", attempts=1, duration_ms=1000)
    obs.log_decision("t5", "worker", "excluded", "", directory=tmp_path, task_id="t5:1", company="B", attempts=2, duration_ms=5000)
    obs.log_decision("t5", "worker", "done", "", directory=tmp_path, task_id="t5:2", company="C", attempts=1, duration_ms=3000)

    summary = obs.summarize_trace("t5", tmp_path)
    assert summary["worker_count"] == 3
    assert summary["done"] == 2 and summary["excluded"] == 1
    assert summary["slowest"]["company"] == "B"
    assert [w["company"] for w in summary["workers"]] == ["B", "C", "A"]


def test_summarize_missing_trace(tmp_path):
    assert obs.summarize_trace("none", tmp_path)["worker_count"] == 0
