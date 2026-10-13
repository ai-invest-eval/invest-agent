# B 역할 통합 안내 (v3.2)

`src/orchestration/orchestrator.py`는 main에서 독립 구현했다. 공용 State/Schema,
graph.py, observability.py는 각각 A/F 담당이므로 수정하지 않았다.

- A: 초기 State에 trace_id와 plan을 추가하고 orchestrator/dispatch를 그래프에 연결한다.
- A: SubTask 필드는 task_id, task_index, company, focus, discovery_refs, max_attempts다.
  B 반환은 이 계약의 dict이며 공용 타입을 추가하면 타입 표기를 연결할 수 있다.
- C: Send 입력은 task, trace_id, selected_startup, analysis_focus, references다.
  references는 해당 기업의 discovery 출처만 포함한다.
- F: observability.log_decision이 통합되면 자동 사용한다. 현재 단독 실행은 표준 로거를 사용한다.
- 빈 후보는 색인·모델·Planner 없이 synthesizer로 이동한다.
- 색인 준비 오류는 실행 실패로 전달한다. Planner 장애/누락/추가/중복/형식 오류만 focus=[]로 대체한다.
- focus는 초기 검색 계획 입력과 첫 계획 질의에 반영한다. 고정 근거 검색, 필터,
  top-k, 최대 1회 재검색, 근거·출처 검증은 기존 동작을 유지한다.

검증: `uv run --extra rag python -m pytest -q`.
실제 API/모델 다운로드 시연과 전체 v3.2 그래프 실행은 다른 담당 모듈 통합 후 수행한다.

## 검증 결과

- B 관련 테스트: 34개 통과 (기존 PDF 페이지 수 테스트 제외).
- 전체 테스트: 167개 통과, 1개 실패, 14개 subtest 통과.
- 실패: `test_pdf_metadata_original_page_map`이 기술 PDF 115쪽을 기대하지만
  최신 main 자료는 98쪽이다. HEAD의 수정 전 테스트로도 같은 실패를 재현했다.
  B 범위 밖의 자료/기대값은 변경하지 않았다.
- 변경 파일의 Ruff 검사 및 포맷 검사 통과.
