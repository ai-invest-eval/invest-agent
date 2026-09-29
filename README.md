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
