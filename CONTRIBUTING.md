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
| 1 | `src/agents/agent1_search.py` / `startup_search` | `input_keyword` | `StartupSearchUpdate`: `candidate_startups`, `selected_startup`, `references` |
| 2 | `src/agents/agent2_profile.py` / `company_profile` | `selected_startup` | `CompanyProfileUpdate`: `startup_profile`, `references` |
| 3-A | `src/agents/agent3a_tech.py` / `tech_analysis` | `selected_startup`, `startup_profile` | `TechAnalysisUpdate`: `tech_analysis`, `references` |
| 3-B | `src/agents/agent3b_market.py` / `market_analysis` | `selected_startup`, `startup_profile` | `MarketAnalysisUpdate`: `market_analysis`, `references` |
| 4 | `src/agents/agent4_competitor.py` / `competitor_analysis` | `selected_startup`, `startup_profile`, `tech_analysis`, `market_analysis` | `CompetitorAnalysisUpdate`: `competitor_analysis`, `references` |
| 5 | `src/agents/agent5_decision.py` / `investment_decision` | `selected_startup`, `startup_profile`, `tech_analysis`, `market_analysis`, `competitor_analysis`, `references` | `InvestmentDecisionUpdate`: `investment_decision`, `evaluation_history` |
| 6 | `src/agents/agent6_report.py` / `report_writer` | `evaluation_history`, `references` | `ReportUpdate`: `final_report` |

### Return Rules

- 입력 State를 직접 수정하거나 `{**state, ...}`로 전체 State를 반환하지 않습니다.
- `references`와 `evaluation_history`는 reducer가 누적합니다. 새 항목만 반환하고, 추가 항목이 없으면 빈 목록을 반환합니다. 기존 목록을 함께 반환하면 중복 누적됩니다.
- Agent 1은 최초 탐색에서 후보 목록과 첫 평가 대상을 반환합니다. 후보가 없으면 `candidate_startups=[]`, `selected_startup=None`을 반환합니다. 다음 후보 선택과 분석값 초기화는 추후 그래프 제어 노드에서 처리합니다.
- Agent 2~5는 유효한 `selected_startup`을 전제로 실행합니다. Agent 3-A~5는 기업 프로필도 준비되어 있어야 합니다. 후보가 없는 경우와 실행 종료는 그래프에서 분기합니다.
- Agent 4는 3-A와 3-B가 모두 완료된 뒤 실행합니다. 병렬 노드는 자신의 분석 필드와 새 출처만 반환합니다.
- 출처의 `agent` 값은 각각 `discovery`, `profile`, `tech`, `market`, `competitor`를 사용합니다. 기업별 분석과 보고서는 `company`가 해당 기업 이름과 일치하는 출처를 사용합니다.
- Agent 5는 현재 기업의 `investment_decision`과 현재 기업만 담은 `evaluation_history=[record]`를 반환합니다. `record`는 현재 `EvaluationRecord` 정의대로 점수 필드를 펼쳐 저장합니다.
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
