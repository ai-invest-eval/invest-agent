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
│   ├── rag/
│   ├── tools/
│   ├── schemas.py
│   └── state.py
├── data/
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
| `app.py` | 실행 진입점. 실행 코드는 추후 추가합니다. |
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
