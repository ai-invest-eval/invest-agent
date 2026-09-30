# 4. 경쟁사 비교 에이전트

공용 `src.state.InvestmentState`, `src.schemas.StartupProfile`·`Reference`를 사용합니다.
`models.py`에는 LLM 구조화 출력용 내부 모델만 둡니다. 공용 파일은 수정하지 않았습니다.

## 입력과 출력

입력: `startup_profile`(선택 기업), `tech_analysis`·`market_analysis`(문자열), `references`.
출력은 State 전체가 아닌 `competitor_analysis`(Markdown 문자열)와 새로 사용한 `references`입니다.
출처에는 대상 기업명을 기록하며, 기존 출처를 다시 반환하지 않아 `operator.add` 중복 누적을 피합니다.
동종 기업·빅테크·전통 대체재, SWOT, QI~QM의 근거와 결측을 정리합니다. 점수와 투자 판정은 5번 책임입니다.

## 실행 (저장소 루트)

```bash
uv sync
uv run python -m examples.competitor.demo
uv run python -m unittest discover -s tests -p 'test_competitor.py' -v
```

데모는 가상 데이터만 사용하며 API 키가 필요 없습니다.
결과는 Git에서 제외되는 `outputs/competitor_demo.json`과 `.md`에 저장됩니다.

실제 검색·분석은 `.env`에 `TAVILY_API_KEY`, `OPENAI_API_KEY`를 설정한 뒤 실행합니다.
아래 호출은 최대 Tavily 검색 3회와 LLM 분석 1회를 사용합니다.

```bash
uv run python -m examples.competitor.run --env .env --input examples/competitor/sample_state.json --output outputs/competitor_live.json
```

## 그래프 연결

```python
from src.agents.competitor import build_live_agent

graph.add_node("competitor", build_live_agent())
graph.add_edge(["tech", "market"], "competitor")
graph.add_edge("competitor", "investment")
```

노드 이름은 실제 그래프에 맞추세요. 기술·시장 분석이 모두 끝난 뒤 한 번 실행해야 합니다.
다음 기업으로 넘어갈 때 상위 그래프가 프로필과 기술·시장 분석을 함께 교체해야 합니다.

## 개발 시 주의

- 기존 v10 구현을 현재 저장소의 공용 계약으로 이전했습니다. v15 전체 요구사항 준수 검증을 의미하지 않습니다.
- TypedDict는 런타임 검증기가 아닙니다. 이 노드는 이름과 분석 문자열 등 필요한 경계를 검증하며, 전체 프로필 검증은 생산 노드 책임입니다.
- 예제의 불명확한 boolean·금액 필드는 `None`과 `missing_fields`로 표현합니다.
- 입력은 수정하지 않으며 추가 프로필 필드도 LLM 입력에 보존합니다.
- 출처 원문이 없으면 상위 분석을 독립적인 원문 근거로 간주하지 않습니다.
- 인용 ID와 발췌문 일치를 검사하지만 주장의 의미적 타당성까지 보증하지는 않습니다.
- 검색/LLM 실패 시 예외 종류와 결측을 기록합니다. 예외 원문과 API 키를 결과에 포함하지 않습니다.
- 실제 API 연동, 검색 품질과 모델의 판단 품질은 별도 검증 대상입니다.
