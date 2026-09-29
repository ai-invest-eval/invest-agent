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
