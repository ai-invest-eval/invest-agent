# Contribution Guide

## Branch

최신 `main`에서 작업별 브랜치를 만듭니다. 예: `feat/agent-1-startup-search`, `feat/agent-3a-tech-analysis`.

## Commit

커밋 제목은 `유형: 변경 내용` 형식으로 작성합니다. 한 커밋에는 한 가지 변경 주제를 담습니다.

| 유형 | 용도 |
| --- | --- |
| `Init` | 프로젝트 초기 설정 |
| `Feat` | 기능 추가 |
| `Fix` | 오류 수정 |
| `Docs` | 문서 수정 |
| `Refactor` | 기능 변경 없는 코드 정리 |
| `Chore` | 의존성 및 개발 환경 등 유지보수 |
| `Style` | 동작 변경 없는 코드 형식 수정 |
| `Delete` | 불필요한 파일 또는 코드 삭제 |

예: `Feat: 스타트업 검색 에이전트 구현`

## Code Quality

처음 환경을 설정할 때 프로젝트 루트에서 Git 훅을 설치합니다. 이후 커밋할 때 린트와 포맷 검사가 자동으로 실행됩니다.

```bash
uv sync
uv run pre-commit install
```

전체 Python 파일을 직접 검사하려면 `uv run pre-commit run --all-files`를 실행합니다. 포맷 수정이 필요하면 `uv run ruff format .`을 실행한 뒤 변경 파일을 다시 스테이징합니다.

## PR and Merge

`main`에 직접 푸시하지 않고 작업 브랜치에서 PR을 만듭니다. 로컬 검증과 다른 팀원 1명의 검토를 마친 뒤 **Create a merge commit**으로 합칩니다. `src/state.py`나 `src/graph.py`처럼 여러 에이전트가 사용하는 파일의 변경은 관련 담당자와 함께 확인합니다.

## Agent Contracts

모든 노드는 `InvestmentState`를 입력받고, `src/schemas.py`에 정의한 Update 타입으로 State 변경분만 반환합니다. 아래 입력 필드는 해당 노드 실행 전에 준비되어 있어야 합니다. 3-A와 3-B는 같은 담당자가 구현하되 별도 노드로 유지합니다.

| 담당 | 파일 / 함수 | 읽는 State 필드 | 반환 타입 / 필드 |
| --- | --- | --- | --- |
| 1 | `src/agents/agent1_search.py` / `startup_search` | `input_keyword`, `max_candidates`, `candidate_startups`, `evaluation_history` | `StartupSearchUpdate`: `candidate_startups`, `selected_startup`, `references`, 프로필·분석·판정 초기화 |
| 2 | `src/agents/agent2_profile.py` / `company_profile` | `selected_startup` | `CompanyProfileUpdate`: `startup_profile`, `references` |
| 3-A | `src/agents/agent3a_tech.py` / `tech_analysis` | `selected_startup`, `startup_profile` | `TechAnalysisUpdate`: `tech_analysis`, `references` |
| 3-B | `src/agents/agent3b_market.py` / `market_analysis` | `selected_startup`, `startup_profile` | `MarketAnalysisUpdate`: `market_analysis`, `references` |
| 4 | `src/agents/agent4_competitor.py` / `competitor_analysis` | `selected_startup`, `startup_profile`, `tech_analysis`, `market_analysis` | `CompetitorAnalysisUpdate`: `competitor_analysis`, `references` |
| 5 | `src/agents/agent5_decision.py` / `investment_decision` | `selected_startup`, `startup_profile`, `tech_analysis`, `market_analysis`, `competitor_analysis`, `references` | `InvestmentDecisionUpdate`: `investment_decision`, `evaluation_history` |
| 6 | `src/agents/agent6_report.py` / `report_writer` | `evaluation_history`, `references` | `ReportUpdate`: `final_report` |

### Return Rules

- 입력 State를 직접 수정하거나 `{**state, ...}`로 전체 State를 반환하지 않습니다.
- `references`와 `evaluation_history`는 reducer가 누적합니다. 새 항목만 반환하고, 추가 항목이 없으면 빈 목록을 반환합니다. 기존 목록을 함께 반환하면 중복 누적됩니다.
- Agent 1은 최초 탐색에서 자격 검증된 후보를 `max_candidates` 이내로 확정하고 첫 평가 대상을 반환합니다. 후보가 없으면 `candidate_startups=[]`, `selected_startup=None`을 반환합니다.
- `5 → 1` 재진입 시 Agent 1은 재검색하지 않고 `evaluation_history`에 없는 후보를 선택합니다. 이름 비교 시 공백·대소문자 등 표기를 일관되게 정규화합니다.
- Agent 1은 후보를 선택할 때 `startup_profile=None`, 각 분석 글 `""`, `investment_decision=None`을 반환해 현재 기업의 분석값을 초기화합니다. `references`에는 새 출처만 반환하고 `evaluation_history`는 반환하지 않아 기존 이력을 보존합니다.
- Agent 2~5는 유효한 `selected_startup`을 전제로 실행합니다. Agent 3-A~5는 기업 프로필도 준비되어 있어야 합니다. 후보가 없는 경우와 실행 종료는 그래프에서 분기합니다.
- Agent 4는 3-A와 3-B가 모두 완료된 뒤 실행합니다. 병렬 노드는 자신의 분석 필드와 새 출처만 반환합니다.
- 출처의 `agent` 값은 각각 `discovery`, `profile`, `tech`, `market`, `competitor`를 사용합니다. 기업별 분석과 보고서는 `company`가 해당 기업 이름과 일치하는 출처를 사용합니다.
- Agent 5는 현재 기업의 `investment_decision`과 현재 기업만 담은 `evaluation_history=[record]`를 반환합니다. `record`는 현재 `EvaluationRecord` 정의대로 점수 필드를 펼쳐 저장합니다.
- `question_evidence`는 QA~QO 질문별 `score`, `rationale`, `references`, `missing`을 저장합니다. `question_scores`와 같은 점수를 사용하고, 평가 이력에도 함께 저장합니다. `missing=True`이면 결측 기본점과 결측 사유를 기록합니다.
- 통과/보류와 관계없이 평가를 기록합니다. 그래프 조건 함수는 후보 목록과 평가 이력을 비교해 미평가 후보가 남으면 Agent 1로, 없으면 Agent 6으로 이동합니다. 별도 후보 선택 노드는 추가하지 않습니다.
- Agent 6은 현재 후보 필드 대신 누적 평가 이력을 입력으로 사용합니다. 이력이 비어 있는 경우의 보고서 정책은 Agent 6과 그래프 담당자가 합의합니다.

반환 예시:

```python
def tech_analysis(state: InvestmentState) -> TechAnalysisUpdate:
    return {
        "tech_analysis": analysis_text,
        "references": new_references,
    }
```

현재 노드 파일은 `NotImplementedError`를 발생시키는 구현 골격입니다. 담당자는 함수명과 반환 계약을 유지하며 구현합니다. 테스트용 샘플 반환은 별도 mock/fixture로 작성합니다.

Update 타입과 `InvestmentState`는 `TypedDict`이므로 런타임 검증을 수행하지 않습니다. LLM 응답 검증은 담당 구현에서 Pydantic 등의 검증 수단을 사용합니다. 분석 결과 세부 구조, 점수 범위 및 결측값 표현 등 기존 스키마 TODO는 관련 담당자와 합의 후 변경합니다.

## Shared Defaults

- 최대 후보 수는 실행 옵션 `--max-candidates` > 환경변수(`.env` 포함)의 `MAX_CANDIDATES` > 기본값 `15` 순서로 결정합니다. 1 이상만 허용합니다.
- 모든 노드는 `state["max_candidates"]`를 사용합니다. 개별 파일에 후보 상한을 중복 선언하지 않습니다.
- 전체 실행의 `recursion_limit`은 `src/config.py`에서 최대 후보 수 × 8 + 10으로 계산합니다. 기본값 15개일 때 130이며, 통합 담당자가 실제 그래프 단계 수에 맞춰 조정합니다.
- 재탐색/재검색은 담당 에이전트에서 횟수를 제한합니다. `recursion_limit`은 전체 실행의 마지막 안전장치입니다.
- LLM은 GPT-4o-mini, temperature=0을 공통으로 사용합니다. 키와 모델 설정 로딩은 앱 진입점에서 처리하고, 모듈 import 시 API 호출·모델 다운로드·파일 생성을 실행하지 않습니다.
- 각 담당자는 자신의 샘플 State로 독립 검증합니다. 에이전트 함수 안에서 다른 에이전트를 직접 호출하지 않습니다.
- RAG는 BGE-M3 Dense(FAISS) + Kiwi BM25의 하이브리드 검색을 사용합니다. 각각 top-5를 RRF로 결합해 최종 top-5를 반환합니다. BGE-M3 자체 Sparse 출력은 사용하지 않습니다.
- RAG 기본값은 1,000토큰 청킹·200토큰 겹침입니다. agent/topic 필터와 원문 쪽수·문서 메타데이터를 보존합니다.
- 자격 관문이 미확인이면 보류(자격 미확인), 리스크 관문이 미확인이면 평가 진행 후 보고서에 미확인으로 표시합니다. 원본 GateChecks의 None은 유지합니다.
- 결측 질문은 2점(QN/QO는 3점)을 적용하며 QN/QO도 결측 비중에 포함합니다. missing_weight는 0~1 비율, 영역·총점은 0~100입니다.
- 사업 모델은 pipeline/platform으로 기록하며 QD 시장 기준을 구분합니다. 혼합 사업·미확인 분류는 2·3-B·5번 담당자가 합의합니다.

## Pending Agreements

최종 설계서에서 정한 판정·검색 정책은 그대로 구현합니다. 아래는 구현 전에 맞춰야 할 데이터 계약입니다.

| 합의 항목 | 담당 | 결정할 내용 |
| --- | --- | --- |
| 결측 직렬화 | 2·3-A·3-B·4·5번 | 키 생략/None/빈 목록의 의미, 확인된 없음과 미확인, missing_fields 경로 표기. 숫자·bool에 문자열 사용 금지 |
| 프로필 세부 구조 | 2·5번 | funding_history, partnerships, team, upfront_payment, pre_money_valuation 내부 필드와 필수 항목 |
| 단위·날짜·단계 | 1·2·3-B·5번 | 금액 통화/단위/환율 기준일, 투자·개발 단계 표기, QN 동일 단계 중앙값 출처와 비교 조건 |
| 사업 모델 분류 | 2·3-B·5번 | pipeline/platform 혼합 기업과 미확인 처리, 주력 적응증/서비스 시장 선택 근거 |
| 출처와 RAG 메타데이터 | 2·3-A·3-B·4·6번 | DOC_META 키와 topic 목록, 발췌 원문 쪽수 매핑, URL/발행연도 누락 처리, 출처 중복 식별 |
| 점수 전달·표시 | 5·6번 | area_scores 6개 키, hold_reason 코드+상세 사유, 반올림 시점, 총점·창업자·시장성이 모두 동점일 때 정렬 |
| 후보 식별·빈 결과 | 1·통합·6번 | 한/영 기업명 별칭·중복 기준, 후보 0개 처리. 이름 식별이 불충분하면 candidate_id 추가 여부 합의 |
| 검색 인터페이스·실패 | 3-A·3-B·통합 | Retriever 입력/출력, RRF 상수, 필터·전문용어 토큰화, API 오류와 근거 부족 구분 및 재시도 처리 |
