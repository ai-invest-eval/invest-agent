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

`.env`의 `TAVILY_API_KEY`를 사용해 국내 3개·해외 3개 검색어로 원본을 수집합니다.
현재는 Tavily 수집 단계이며 OpenAI 호출·후보 추출·중복 제거·자격 검증은 하지 않습니다.

```bash
uv run python collect_candidates.py
uv run python collect_candidates.py --query "AI drug discovery Series B startups" --max-results 5
uv run python -m unittest discover -s tests -v
```

- 기본 검색은 advanced, 검색어당 최대 10건, 요청 타임아웃 30초입니다.
- `--query`를 반복해서 지정하면 기본 검색어 대신 사용합니다. `--keyword`는 기본 국내 검색어에 반영되며 해외 검색어는 현재 AI 신약개발 분야로 고정됩니다.
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
