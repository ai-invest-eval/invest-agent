# 태우 담당 구현 · 실행 가이드

작업 위치: `/Users/taewoo/Documents/ai-service/capstone-v1/invest-agent`

브랜치: `feat/taewoo-rag-tech-market`. 이 문서는 RAG와 3-A·3-B를 독립 개발하고 팀 전체 그래프에 연결하는 방법을 설명합니다.

## 1. ai-service 분석과 재사용한 흐름

| 수업 자료 | 참고한 내용 | 과제 구현에서 바꾼 부분 |
| --- | --- | --- |
| `langgraph-v1/20-RAG/rag/base.py` | 문서 내용에 따른 FAISS 캐시 재사용 | OpenAI 임베딩 → BGE-M3 Dense, PDF·설정·서지정보 SHA-256으로 색인 버전 관리 |
| `langgraph-v1/20-RAG/rag/pdf.py` | PDF 로딩·분할 | 문자 수 → BGE-M3 토큰 1,000개·겹침 200개, 페이지 경계와 발췌본 원문 쪽수 보존 |
| `langchain-v1/14-Retriever/04b-BGE-M3.ipynb` | Dense/키워드 검색 결합 | 과제 계약대로 BGE-M3 Dense + Kiwi BM25, 자체 Sparse는 사용하지 않음 |
| `langchain-v1/14-Retriever/10-Retriever-Evaluation.ipynb` | Kiwi·Hit Rate·MRR | 정답 문서·원문 쪽수·정답 인용문으로 판정, 기술적 오류는 miss로 숨기지 않음 |
| `langgraph-v1/20-RAG/14-AgenticRAG-advanced.ipynb` | 근거 판단 → 제한된 재검색 | SQL 부분은 제외, 질문 계획 → RAG → LLM 판단 → 최대 1회 재검색 → 시장 웹 보완 |

수업 파일은 참고용으로 유지하고 실행 가능한 과제 코드는 이 저장소에 작성했습니다. 공통 기준은 `src/schemas.py`, `docs/data_contracts.md`, `docs/investment_criteria_v4.md`, `CONTRIBUTING.md`입니다.

## 2. 환경 설정

```bash
cd /Users/taewoo/Documents/ai-service/capstone-v1/invest-agent
uv sync --extra rag
uv run --extra rag pre-commit install
```

`uv.lock`으로 설치 버전을 재현합니다. `--extra rag`를 붙여야 PDF·FAISS·Kiwi·임베딩 라이브러리가 설치된 상태로 실행됩니다.

`.env`는 `.env.example`을 복사한 설정 파일입니다. 로컬 편집기에서 `OPENAI_API_KEY`, `TAVILY_API_KEY`를 입력하세요. 기존 환경변수에 있는 키도 사용할 수 있습니다.

- PDF 색인·검색·검색 평가는 API 키 없이 실행합니다.
- LLM 기술·시장 분석은 OpenAI 키가 필요합니다.
- 시장 분석에서 부족한 자료를 웹으로 보완하려면 Tavily 키가 필요합니다. 키가 없으면 웹 보완 미실행을 분석 결과에 표시합니다.
- 실행 결과는 Git에서 제외되는 `outputs/`, 색인은 `data/index/`에 저장합니다.

## 3. PDF 색인 생성

```bash
uv run --extra rag python -m src.rag.build_index
```

기술 5개 PDF·115쪽은 122개 청크, 시장 10개 PDF·82쪽은 85개 청크로 생성됐습니다. 페이지별로 나눠 원문 쪽수를 보존하므로 각 청크 길이는 1,000토큰 이하입니다. 1,000토큰이 넘는 페이지에서 200토큰을 겹칩니다.

처음에는 BGE-M3 모델을 다운로드합니다. 현재 이 Mac에서는 다운로드와 색인 생성을 완료했습니다. 다시 실행하면 같은 PDF·메타데이터·설정의 색인을 재사용합니다. 새 PDF가 추가되면 `data/doc_metadata.json`에 서지정보와 원문 쪽수 매핑을 먼저 추가하세요.

```bash
# 기술만 강제 재생성
uv run --extra rag python -m src.rag.build_index --agent tech --force
```

macOS CPU 안정성을 위해 기본 배치 크기와 PyTorch 스레드 수를 1로 설정했습니다. 기기에 맞게 `RAG_BATCH_SIZE`, `RAG_TORCH_THREADS`, `RAG_DEVICE`를 조정할 수 있습니다. 높은 값의 성능·안정성은 별도 확인이 필요합니다.

## 4. 검색 결과부터 확인

```bash
uv run --extra rag python -m src.rag.retrieval \
  --agent tech --query "AI 신약 후보의 실험 검증과 IND 승인"

uv run --extra rag python -m src.rag.retrieval \
  --agent market --query "AI 신약 시장 성장률과 제약사 수요"
```

각 결과에 `doc_id`, 청크 `id`, 원문 `page`, 발췌본 `local_page`, 본문, 서지정보가 있습니다. Dense와 BM25 각각 top-5를 RRF(k=60)로 합쳐 최종 top-5를 반환합니다. 호출할 때 `topic`, `doc_ids`를 지정해 필터링할 수 있습니다. 필터를 적용한 뒤 top-k를 선택합니다.

## 5. API 없는 병렬 배선 점검

```bash
uv run --extra rag python -m src.taewoo_pipeline \
  --mode extract --output-dir outputs/taewoo_extract
```

실제 검색과 LangGraph 병렬 실행을 사용하며 LLM 대신 원문 발췌만 출력합니다. 이 결과는 기업 평가·투자 판단이 아닙니다.

## 6. 3-A·3-B 실제 분석 실행

```bash
# 기술만 실행
uv run --extra rag python app.py \
  --agent 3a --state samples/state_agent3_pipeline.json

# 시장만 실행
uv run --extra rag python app.py \
  --agent 3b --state samples/state_agent3_platform.json

# 기술·시장 병렬 실행과 파일 저장
uv run --extra rag python -m src.taewoo_pipeline \
  --mode live --state samples/state_agent3_platform.json \
  --output-dir outputs/taewoo_live
```

출력 파일:

- `outputs/taewoo_live/tech_analysis.md`
- `outputs/taewoo_live/market_analysis.md`
- `outputs/taewoo_live/state.json`

두 샘플은 팀 공통 샘플에서 가져온 **가상 기업**입니다. 실제 기업을 분석하려면 2번 에이전트의 결과를 입력 JSON에 넣고 `selected_startup.name`과 `startup_profile.name`을 맞추세요.

2026-09-30 검증: 자동 테스트 43개, ruff 린트·포맷, pre-commit, 실제 색인·검색·병렬 실행과 LLM 호출을 확인했습니다. Tavily 웹검색은 키가 없어 주입한 가짜 검색 응답으로 계약·출처·오류 처리를 검증했습니다.

기술 에이전트는 QG 기술 진위·독창성, QH 검증·성숙도, 규제 리스크를 분석합니다. 시장 에이전트는 QD 규모, QE 미충족 수요, QF 확장 가능성, 제약사 수요·파트너십·Exit를 분석합니다. 부족한 근거는 한 번 재검색하고 계속 없으면 정보 부족으로 표시합니다.

시장 에이전트는 `business_model`을 바꾸지 않습니다. `pipeline`은 `lead_indication`과 M7, `platform`은 `lead_service`와 M1·M6를 우선 검색합니다. `unknown`이면 QD를 미확인으로 표시하고 나머지 시장 분석을 계속합니다.

주장의 인용문이 **지정한 출처 본문**에 존재하는지 검증합니다. 잘못된 인용이 있으면 같은 자료로 초안을 1회 수정 요청합니다. 수정 후에도 맞지 않는 주장은 정보 부족으로 바꾸고 해당 출처를 사용 목록에 넣지 않습니다. 원문 존재 검사는 주장과 출처 사이의 의미적 타당성까지 보장하지 않습니다. 산업 보고서를 특정 기업의 실적 증명으로 사용하면 안 됩니다.

## 7. 검색 평가

```bash
uv run --extra rag python -m src.rag.evaluate
```

`24개 질문`의 소규모 개발셋을 한국어·영어·교차 언어로 구성했습니다. 정답은 문서 ID·원문 쪽수·인용문입니다. 다른 쪽에 동일한 답이 있더라도 현재 정답 목록에 없으면 miss가 될 수 있으므로 결과를 검토하고 정답 출처를 보완하세요.

| 검색 방식 | Hit@1 | Hit@3 | Hit@5 | MRR@5 |
| --- | --- | --- | --- | --- |
| BGE-M3 Dense | 0.417 | 0.750 | 0.833 | 0.588 |
| Kiwi BM25 | 0.333 | 0.542 | 0.708 | 0.470 |
| Dense + Kiwi BM25 RRF | 0.542 | 0.667 | 0.792 | 0.619 |

하이브리드는 이 개발셋에서 Hit@1·MRR을 높였지만 Hit@3·5는 Dense보다 낮았습니다. 전체 성능이 항상 개선된다고 주장하지 않습니다. 질문·정답은 문서를 보며 작성한 개발용 초안이며, 독립적인 대규모 평가나 투자 기준의 타당성 검증이 아닙니다.

상세 결과는 `outputs/retrieval_metrics.json`에 저장합니다. 후보 임베딩 모델 비교에는 `build_index --model`과 `evaluate --model`을 사용합니다. 모든 모델에 같은 BGE-M3 기준 청크를 사용하며 multilingual-e5는 query/passage 접두사를 붙입니다. E5처럼 입력 길이 제한이 짧은 모델은 일부 청크가 잘리는 조건임을 비교 결과에 밝혀야 합니다. **다른 후보 모델들의 다운로드·비교 실험은 아직 실행하지 않았습니다.**

## 8. 테스트·팀 통합

```bash
uv run --extra rag python -m pytest -q
uv run --extra rag ruff check .
uv run --extra rag ruff format --check .
uv run --extra rag pre-commit run --all-files
```

반환 계약:

```python
# 3-A
{"tech_analysis": "분석 Markdown", "references": [사용한 새 Reference]}
# 3-B
{"market_analysis": "분석 Markdown", "references": [사용한 새 Reference]}
```

입력 State를 수정하지 않습니다. 누적 목록 전체를 반환하지 않습니다. 두 노드는 자신의 분석 필드만 쓰고 `references`에는 실제 사용한 새 자료만 추가합니다.

통합 담당자는 기존 `src/graph.py`에 두 노드를 연결하고 다음처럼 합류시킵니다.

```python
graph.add_edge("company_profile", "tech_analysis")
graph.add_edge("company_profile", "market_analysis")
graph.add_edge(["tech_analysis", "market_analysis"], "competitor_analysis")
```

`src/taewoo_pipeline.py`는 태우 담당 부분만 실행하는 점검용 그래프입니다. 팀 전체 `app.py` 실행은 아직 다른 노드와 그래프 통합 구현이 필요합니다.

코드를 확인한 뒤 커밋·푸시·PR을 진행할 수 있습니다. `main` 직접 푸시는 하지 않고, 다른 팀원 1명의 검토 후 merge commit으로 합치는 팀 규칙을 따릅니다.
