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

## 보고서 생성 (Agent 6)

Agent 6은 누적 평가 이력으로 보고서를 만들고 `outputs/investment_report.md`, `outputs/investment_report.pdf`에 저장합니다. PDF는 Markdown → HTML → WeasyPrint로 변환하며, 5쪽을 넘으면 문단 길이와 글자 크기를 줄여 다시 만듭니다.

```bash
# 가상 평가 이력 샘플로 단독 실행 (통과 2곳 / 통과 0곳)
uv run python app.py --agent 6 --state samples/report_state.json
uv run python app.py --agent 6 --state samples/report_state_no_pass.json
```

- `OPENAI_API_KEY`가 없거나 `REPORT_USE_LLM=0`이면 LLM 대신 평가 이력의 근거 문장으로 같은 목차를 채웁니다.
- 저장 위치·파일명은 `REPORT_OUTPUT_DIR`, `REPORT_FILE_STEM` 환경변수로 바꿀 수 있습니다.
- WeasyPrint는 Pango 시스템 라이브러리가 필요합니다. macOS: `brew install pango`, Windows: [MSYS2 설치 안내](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows) 참고. PDF 생성에 실패해도 Markdown 보고서는 반환합니다.
