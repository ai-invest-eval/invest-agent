# A파트 뼈대 전달 — v3.2

## 현재 상태

- 브랜치: `agent/orchestrator-workers`. 원격 push/merge는 이 전달본에 포함하지 않는다.
- A 공용 계약·라우팅·그래프·CLI·fixture 구현. B~F 자리는 교체용 stub이다.
- 실제 에이전트 코드(agent1~6, RAG)의 내부 로직은 수정하지 않았다.
- fixture는 실제 StateGraph의 Send·reducer·하위 병렬 합류·체크포인트를 실행한다. 웹·LLM·원문 검증·PDF는 가짜이며 실제 투자 결과가 아니다.

## 공용 계약

- 기준: `src/schemas.py`와 `src/state.py` (v3.2). Input/Working/Eval/Loop 구역.
- 부모 단일값에 selected_startup/profile/analysis/decision을 두지 않는다. 해당 값은 WorkerState에서만 사용한다.
- 병렬 반환은 history/references/worker_results/step_count/node_status reducer로 병합한다. Worker는 last_error를 쓰지 않는다.
- Send 키: task, trace_id, selected_startup, analysis_focus, references.
- quality_eval은 판정만 반환. `src/orchestration/routing.py`가 다음 경로를 정한다.
- 모든 품질 종료 경로는 finalize를 거친다. finalize에서 graph를 import하지 않는다.
- report_draft, evaluated_body_hash, source_locator, excerpt_verified 계약 포함.
- 원문을 확보·확인하지 못하면 analysis_rationale로 분류하고 검증 한계를 기록한다.
- 새 품질 평가마다 checks/issues/can_rewrite/passed를 전부 새로 계산한다.

## 교체 위치

| 담당 | 교체할 함수/파일 | 주의 |
|---|---|---|
| B | orchestration/orchestrator.py: orchestrator, dispatch | dispatch는 현재 동적 Send 계약 구현. 탐색·계획·워밍업을 채운다 |
| C | orchestration/worker.py: run_worker(state, config) | 새 상태로 재시도, child config 전달, 새 refs만 반환 |
| D | orchestration/quality_eval.py: quality_eval | QualityEvalUpdate, 새 평가 본문 hash, 원문 분류 |
| E | agents/agent6_report.py: report_writer; orchestration/finalize.py: finalize | SynthesizerUpdate/FinalizeUpdate. 기존 report_writer는 아직 구버전이다 |
| F | orchestration/observability.py: log_decision | 기존 시그니처 유지, redaction·JSONL 구현 |

stub은 live 실행에서 NotImplementedError로 명확하게 멈춘다. 실제 에이전트 대신 fixture 결과를 몰래 사용하는 fallback은 없다.
`build_graph(nodes=...)`로 같은 그래프에 테스트 노드를 주입할 수 있다. fixture와 nodes를 동시에 지정할 수 없다.

## A 테스트·실행

```bash
uv sync --extra rag
uv run --extra rag python -m pytest -q tests/test_pipeline.py tests/test_routing.py tests/test_agent1_execution.py
uv run --extra rag python app.py --fixture empty
uv run --extra rag python app.py --fixture two
uv run --extra rag python app.py --fixture three
uv run --extra rag python app.py --fixture partial_fail
uv run --extra rag python app.py --fixture all_fail
uv run --extra rag python app.py --fixture quality_loop
```

fixture 결과는 outputs/fixture_<name>_<trace_id>_state.json 및 .md에 저장한다. fixture Judge 통과는 실제 내용 품질 통과를 뜻하지 않는다. 최종 report_pages=None, PDF 미생성을 명시한다.
전체 테스트 결과와 기존 원문 데이터 테스트 이슈는 `docs/a_part_validation.md`에 기록한다.

## 통합 순서

A 뼈대 → F 관측성 stub → C Worker → B Planner → 중간 실제 실행 → E 보고서·최종화 → D 품질 평가 → A 통합 → F 제출 준비.
현재 live 기본 그래프는 B/C/D/E stub과 기존 E report_writer를 연결한 형태다. E의 report_writer를 v3.2 계약으로 변경한 뒤 live 최종 통합을 검증한다. 실제 API 중간 실행은 미구현 D/E에 테스트 노드를 명시 주입해 기능 점검하며, 그 결과를 최종 보고서로 제출하지 않는다.

## Git 적용

전달 zip의 패치는 기준 commit에 대한 변경만 포함한다. 기존 미커밋 변경이 있으면 별도 작업 폴더에서 적용한다.

```bash
git switch -c agent/orchestrator-workers d708ba6659b4bb6a09f74f0bd9c46124c4c4a1b9
git apply --check a_part_v3.2.patch
git apply a_part_v3.2.patch
uv run --extra rag python -m pytest -q tests/test_pipeline.py tests/test_routing.py tests/test_agent1_execution.py
git add app.py src/config.py src/graph.py src/schemas.py src/state.py src/orchestration tests/test_pipeline.py tests/test_routing.py tests/test_agent1_execution.py docs/a_part_handoff.md docs/a_part_validation.md
git commit -m "Feat: A파트 orchestrator-workers 공용 뼈대와 fixture"
```

패치에는 agent1~6 분석 로직 변경과 API 키/.env/outputs/.venv가 없다. tests/test_agent1_execution.py는 단독 Agent1 반복 테스트의 기존 의도를 유지하면서 테스트 전용 StandaloneSearchState를 사용하도록 변경했다. 새 부모 State에 회사 단일값을 다시 넣지 않기 위한 변경이다.
원격 협업 브랜치가 이미 있으면 새로 만들지 말고 최신 브랜치를 받아 충돌 여부를 확인한 뒤 적용한다.
