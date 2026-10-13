# B 역할 통합 안내 (v3.2)

`feat/orch-a`의 공용 뼈대(08c7555)를 B 브랜치에 병합해 실제 A 그래프로 검증했다.
A의 교체용 orchestrator stub은 B 실제 구현으로 유지했다. 공용 State/Schema,
graph.py, observability.py의 내부 구현은 A/F 전달본을 그대로 사용한다.

- A: InvestmentState/SubTask/OrchestratorUpdate 타입과 MAX_WORKER_ATTEMPTS 상수를 연결했다.
  build_graph(nodes=...)에서 실제 B 노드를 사용해 Send·reducer·fan-in을 검증했다.
- C: Send 입력은 task, trace_id, selected_startup, analysis_focus, references다.
  references는 해당 기업의 discovery 출처만 포함한다.
- F: 현재 전달본의 observability.log_decision은 빈 stub이므로 실제 로그 저장은 아직 안 된다.
  F 실제 구현이 통합되면 B는 같은 시그니처로 자동 사용한다.
- 빈 후보는 색인·모델·Planner 없이 synthesizer로 이동한다.
- 색인 준비 오류는 실행 실패로 전달한다. Planner 장애/누락/추가/중복/형식 오류만 focus=[]로 대체한다.
- focus는 초기 검색 계획 입력과 첫 계획 질의에 반영한다. 고정 근거 검색, 필터,
  top-k, 최대 1회 재검색, 근거·출처 검증은 기존 동작을 유지한다.

검증: `uv run --extra rag python -m pytest -q`.
실제 API/모델 다운로드 시연과 전체 v3.2 그래프 실행은 다른 담당 모듈 통합 후 수행한다.

## 검증 결과

- B 관련 테스트에 A 실제 그래프와의 통합 테스트 12개 및 빈 계획 테스트 1개를 추가했다.
  empty/two/three/partial_fail/all_fail/quality_loop 각각 정상 Planner·fallback을 검증했다.
  Worker는 A fixture의 실제 WorkerState 서브그래프를 사용한다(API·PDF·Judge는 가짜).
- 전체 테스트: 200개 통과, 1개 실패, 14개 subtest 통과.
- 실패: `test_pdf_metadata_original_page_map`이 기술 PDF 115쪽을 기대하지만
  최신 main 자료는 98쪽이다. HEAD의 수정 전 테스트로도 같은 실패를 재현했다.
  B 범위 밖의 자료/기대값은 변경하지 않았다.
- 변경 파일의 Ruff 검사 및 포맷 검사 통과.

## A 전달본에서 남은 타 파트 통합 사항

- origin/agent/orchestrator-workers는 확인 시 main과 같고 A 변경은 feat/orch-a에만 있다.
- C/D/finalize는 live stub이고 agent6는 기존 구현이다. 실제 전체 실행 완료를 주장하지 않는다.
- A ReportDraft 계약은 payload/section_char_limit/reference_map이며 설계 문서의
  draft/char_level/layout_level과 다르다. E가 A 실제 계약을 기준으로 맞춰야 한다.
- A EvalVerdict의 judge_status에는 stale이 아직 없다. E/D의 finalize 축약 정책 통합 때
  A와 계약을 확정해야 한다. B 계획/분배 동작에는 영향이 없다.
