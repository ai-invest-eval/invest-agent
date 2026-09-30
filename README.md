# AI 신약개발 스타트업 투자 평가 에이전트

AI 신약개발 스타트업 투자 평가를 위한 멀티 에이전트 프로젝트입니다.

## 개발 환경 설정

[uv](https://docs.astral.sh/uv/getting-started/installation/)를 설치하고, 저장소를 clone 또는 pull한 뒤 프로젝트 폴더에서 실행합니다.

```bash
uv python install 3.11.11
uv venv --python 3.11.11
uv sync
cp .env.example .env
uv run python --version
```

마지막 명령에서 `Python 3.11.11`이 출력되면 환경 설정이 완료된 것입니다. API를 사용할 때는 `.env`에 키를 입력합니다.

## Project Structure

```text
.
├── app.py
├── src/
│   ├── agents/
│   ├── rag/              # build_index.py: 색인 구현 TODO
│   ├── tools/
│   ├── config.py         # 공통 기본값과 실행 한도 계산
│   ├── graph.py          # 그래프 연결 TODO
│   ├── schemas.py
│   └── state.py
├── data/
│   ├── technology/       # 기술요약 PDF
│   └── market/           # 시장성 평가 PDF
├── docs/                 # 투자평가기준 및 공통 데이터 계약
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── pyproject.toml
├── uv.lock
├── CONTRIBUTING.md
└── README.md
```

## Directory Guide

| 경로 | 용도 |
| --- | --- |
| `app.py` | 전체 실행 TODO 및 개별 에이전트 실행 진입점 |
| `src/` | 공통 State 및 Graph 코드 |
| `src/state.py` | 에이전트가 공유하는 State |
| `src/schemas.py` | 에이전트 간 데이터 형식 |
| `src/agents/` | 에이전트별 구현 |
| `src/rag/` | 문서 색인 및 검색 |
| `src/tools/` | 에이전트가 사용하는 도구 |
| `data/` | RAG 원본 자료 |
| `outputs/` | 생성된 결과물. 필요할 때 생성하며 Git에서 제외합니다. |

구현 파일과 하위 디렉터리는 필요할 때 추가합니다.

커밋과 머지 규칙은 [CONTRIBUTING.md](CONTRIBUTING.md)를 참고합니다.
공통 데이터 형식은 [데이터 계약](docs/data_contracts.md), 채점 기준은 [투자평가기준 v4](docs/investment_criteria_v4.md)를 참고합니다.

## 개별 에이전트 개발

`app.py`는 선택한 에이전트만 import합니다. 다른 에이전트나 RAG 구현 없이 담당 노드를 개발할 수 있습니다.

```bash
uv run python app.py --agent 1 --keyword "AI 신약개발 스타트업"
```

Agent 2 이후는 담당 노드의 입력 계약에 맞는 샘플 State JSON을 준비합니다.
이전 에이전트의 실행 결과 대신 이 샘플로 독립 개발할 수 있습니다.

```bash
uv run python app.py --agent 3a --state samples/tech_state.json
```

`--agent` 값은 `1`, `2`, `3a`, `3b`, `4`, `5`, `6`입니다.
샘플 파일은 담당자가 작성하며 위 경로는 예시입니다.
현재 에이전트는 미구현 골격이므로 호출 시 미구현 안내로 종료합니다.
각 함수 구현 후에는 해당 노드의 반환 데이터만 JSON으로 출력합니다.

## Agent 1 원본 검색 수집

`.env`의 `TAVILY_API_KEY`로 설계서의 지정 소스를 먼저 검색합니다.
스타트업레시피 3개·Cure Funding Tracker 1개·YC 2개 검색어를 각각 해당 도메인으로 제한합니다.
현재는 Tavily 수집 단계이며 OpenAI 호출·후보 추출·중복 제거·자격 검증은 하지 않습니다.

```bash
uv run python collect_candidates.py
uv run python collect_candidates.py --query "AI 신약 투자" --include-domain startuprecipe.co.kr
uv run python collect_candidates.py --query "AI drug discovery Series B startups" --max-results 5
uv run python -m unittest discover -s tests -v
```

- 기본 검색은 advanced, 검색어당 최대 10건, 요청 타임아웃 30초입니다.
- `--keyword`는 국내 검색어, `--english-keyword`는 해외 소스 검색어에 반영됩니다.
- `--query`를 반복하면 기본 검색 대신 실행합니다. `--include-domain`을 함께 지정하면 해당 도메인으로 제한하고, 생략하면 일반 검색입니다. 기본 실행은 소스가 비었다고 자동 일반 검색으로 우회하지 않습니다.
- 검색 계획은 `src/agents/agent1_sources.py`에 있어 최종 Agent 1에서도 재사용할 수 있습니다. `collect_candidates.py`는 원본 점검용 실행 파일입니다.
- 각 검색에 source_key/source_scope/source_url/include_domains를 기록합니다. 해외 탐색 소스에도 한국 기업이 있을 수 있으므로 소스 범위로 기업 국적·투자 시장을 추정하지 않습니다.
- 지정 소스 URL·수집 한계는 [Agent 1 탐색 소스](docs/agent1_sources.md)를 참고합니다. 공개 페이지 검색이며 각 사이트 자체 API나 전체 DB 다운로드가 아닙니다.

### LLM 검색 계획 및 미검증 후보 추출

```bash
uv run python discover_candidates.py --plan-only
uv run python discover_candidates.py --max-search-requests 12
uv run python discover_candidates.py --input outputs/discovery/discovery_실제파일명.json
```

- `discover_candidates.py`는 가변 검색 계획 → Tavily 수집 → 후보 추출 → 근거 검사 → 동일 기업 병합을 수행합니다. 다른 에이전트나 그래프 없이 실행할 수 있습니다.
- 검색 호출 상한은 `MAX_DISCOVERY_SEARCH_REQUESTS` 또는 `--max-search-requests`로 지정합니다. 기본 12, 최소 3이며 **최종 후보 수 기본 15와 별개**입니다. 상한만큼 반드시 검색하지 않습니다.
- `collect_candidates.py`의 기존 고정 6개 검색은 원본 점검용으로 유지합니다. 가변 검색 계획은 새 실행 파일을 사용하세요.
- `--plan-only`는 OpenAI만 호출하며, `--input`은 기존 원본을 재사용해 Tavily를 호출하지 않습니다. 기본 실행에는 두 API 키가 필요합니다.
- 검색 계획(`search_plan_*`), 수집 원본(`discovery_*`), 추출 결과(`candidate_leads_*`)를 각각 JSON으로 저장합니다. 추출 결과에는 원문 조각과 근거 발췌를 보존합니다.
- 결과는 `extracted_unverified` 상태입니다. 상장·인수·투자 단계·대기업 자회사 여부 검증과 공통 State 연결은 아직 구현하지 않았습니다. 국가·라운드가 충돌하면 임의 선택하지 않고 `None`으로 남깁니다.
- 검색 원문에 없는 문서 ID·발췌는 제외하고, 원문에서 확인되지 않는 공식 사이트는 `None`으로 둡니다. 이 검사는 원문의 사실성이나 기업 자격까지 보증하지 않습니다.

### 기업별 자격 검증

```bash
uv run python qualify_candidates.py --input outputs/discovery/candidate_leads_실제파일명.json --limit 2
uv run python qualify_candidates.py --input outputs/discovery/candidate_leads_실제파일명.json --company "기업명"
```

- `--limit`은 이번 개발 실행의 검증 기업 수이며, 최종 후보 수 설정이 아닙니다. 지정하지 않으면 모든 입력 후보를 검증합니다.
- 기업당 기본 검색 2회, 조건 미확인 시 보완 검색 최대 1회로 제한합니다. 공식 사이트가 확인된 후보는 첫 검색에 해당 도메인을 적용하고, 외부 검색은 제한하지 않습니다. 사이트 미확인 시 첫 검색도 일반 검색입니다.
- AI 신약개발·비상장·Exit 미완료·대기업 자회사 아님과 최신 확인 라운드를 근거로 판단합니다. 결과는 `eligible`(조건 확인), `excluded`(불충족 확인), `unconfirmed`(자격 미확인)입니다. 투자 추천 판정이 아닙니다.
- Seed~Series C 및 프리 시리즈 A는 범위 내입니다. 프리시드는 Seed 미만으로 제외하며, 기본 단계 불명의 브리지는 미확인입니다. 국내/해외 접미사 정규화와 최종 후보 선택은 후속 단계입니다.
- 검색 발췌를 우선 사용하고 문서당 최대 6,000자를 전달합니다. `excerpt_only`·`truncated`로 범위를 표시하며, 전체 문서나 모든 최신 사실을 검증했다고 보장하지 않습니다. 검색에서 사건을 찾지 못한 것만으로 해당 사건이 없다고 단정하지 않습니다.
- 모델은 원문의 문서·문단 ID만 선택하고 발췌 문자열은 코드가 원문에서 복사합니다. 근거가 없거나 입력에 없는 ID면 해당 조건을 `None`으로 되돌립니다. 이 검사는 원문의 사실성이나 판단의 의미적 정확성까지 보증하지 않습니다. API 실패와 검색 성공 후 결과 없음은 별도로 기록하고, 기업별 결과를 즉시 `outputs/qualification/qualification_*.json`에 저장합니다.
- 문단 ID 검사 뒤 별도 LLM 호출로 각 판단의 근거 충분성을 검증합니다. 충분하지 않으면 해당 항목은 `None`입니다. 검색 없는 사건을 없음으로 단정하거나 펀딩 기사로 독립성·인수 미완료를 증명하지 않도록 점검합니다. LLM 검증도 오류 가능성이 있으며 모든 기업 사실을 보증하지 않습니다.
- 공통 State·스키마는 변경하지 않았으며 `startup_search()` 연결은 아직 구현 전입니다.
- 원본 응답의 제목·URL·검색 발췌·본문·점수와 검색어를 `outputs/discovery/` JSON에 보존합니다. 외부 페이지 내용은 데이터로 취급하며 그 안의 지시문을 실행하지 않습니다.
- 동일 페이지가 여러 검색어에 잡혀도 원본에는 그대로 남깁니다. 본문을 Tavily가 제공하지 못하면 없는 그대로 보존하며 내용을 생성하지 않습니다.
- 일부 실패는 성공한 결과와 함께 저장하고, 전부 실패하면 종료 코드 1을 반환합니다. 실패를 후보 없음으로 처리하지 않습니다.
- 생성 결과는 Git에서 제외됩니다. API 키와 인증 필드는 출력·저장하지 않습니다.

## 통합 및 RAG 구현 TODO

- `src/graph.py`: 노드 import·등록, 기술/시장 병렬 합류, 후보 반복과 종료 분기를 연결합니다.
- `src/rag/build_index.py`: Agent 3-A/3-B 담당자가 PDF 로딩 → 토큰 청킹 → BGE-M3 Dense(FAISS) + Kiwi BM25 색인 → RRF 검색 결과 병합을 구현합니다.
- `app.py`: 색인 준비 → 초기 State → 그래프 실행 → 보고서 출력 순서로 통합합니다.

현재 `uv run python app.py`는 골격 안내만 출력하며 전체 평가나 색인을 실행하지 않습니다.
색인용 라이브러리와 청킹·재사용 정책은 RAG 담당자가 구현하면서 확정합니다.

## 실행 설정

최대 후보 수는 기본 15개입니다. `.env`의 `MAX_CANDIDATES`로 변경하거나 실행 옵션을 지정합니다.
실행 옵션이 환경변수보다 우선하고, 샘플 State의 후보 상한도 이번 실행 설정을 따릅니다.

```bash
uv run python app.py --agent 1 --max-candidates 10
```

전체 그래프 실행 한도는 최대 후보 수 × 8 + 10으로 계산합니다(기본 130).
계산식은 통합 담당자가 실제 연결 단계와 재시도 예산에 맞춰 조정합니다.
Agent 1은 최초 탐색 후 후보를 확정하고, `5 → 1` 재진입에서는 평가 이력을 보고 다음 후보를 선택합니다.
