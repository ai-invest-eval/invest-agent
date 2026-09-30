"""실제 검색 라이브러리 + 가짜 LLM으로 계약·필터·재검색·출처 연결을 검증."""

import copy
import json

import faiss
import numpy as np
import pytest

from src.agents.rag_analysis import (
    AnalysisDraft,
    Citation,
    Claim,
    Query,
    RagAnalysisAgent,
    Relevance,
    SearchPlan,
    Section,
)
from src.rag import documents, retrieval


def hit(agent="tech", doc="T1", text="IND 신청과 IND 승인은 다른 단계입니다."):
    return {
        "id": f"{doc}:p1:t0",
        "doc_id": doc,
        "agent": agent,
        "topics": ["regulation"],
        "text": text,
        "page": 1,
        "metadata": {
            "title": "검증 자료",
            "issuer": "기관",
            "year": 2026,
            "doc_type": "report",
        },
    }


@pytest.fixture
def state():
    return {
        "selected_startup": {"name": "가상 바이오"},
        "startup_profile": {
            "name": "가상 바이오",
            "business_model": "pipeline",
            "lead_indication": "폐암",
            "lead_service": None,
        },
        "references": [],
    }


class FakeAsk:
    def __init__(self, sufficient=(True,), claims=None):
        self.sufficiency = iter(sufficient)
        self.claims = claims or [
            Claim(
                text="IND 신청과 승인을 구분한다.",
                status="supported",
                citations=[
                    Citation(
                        source_id="T1:p1:t0",
                        quote="IND 신청과 IND 승인은 다른 단계입니다.",
                    )
                ],
            )
        ]
        self.calls = []

    def __call__(self, schema, payload):
        self.calls.append((schema, payload))
        if schema is SearchPlan:
            return SearchPlan(queries=[Query(query="임상 규제")])
        if schema is Relevance:
            return Relevance(
                sufficient=next(self.sufficiency),
                reason="근거 점검",
                gaps=["추가 근거 필요"],
                revised_queries=[Query(query="IND 규제 자료")],
            )
        return AnalysisDraft(
            sections=[
                Section(
                    title="QH 실험·개발 성숙도"
                    if payload["agent"] == "tech"
                    else "QD 대표 시장 규모",
                    claims=self.claims,
                )
            ]
        )


def test_analysis_contract_and_input_preserved(state):
    before = copy.deepcopy(state)
    result = RagAnalysisAgent("tech", lambda *a, **kw: [hit()], FakeAsk())(state)
    assert set(result) == {"tech_analysis", "references"}
    assert state == before
    assert result["references"][0]["company"] == "가상 바이오"
    assert result["references"][0]["page"] == 1


def test_retry_once_then_missing(state):
    searches = []
    ask = FakeAsk(sufficient=(False, False))

    def search(query, **kwargs):
        searches.append(query)
        return []

    result = RagAnalysisAgent("tech", search, ask)(state)
    assert len(searches) == 2
    assert "정보 부족" in result["tech_analysis"]
    assert result["references"] == []


def test_wrong_source_quote_rejected(state):
    claims = [
        Claim(
            text="꾸며낸 임상 성공률 99%",
            status="supported",
            citations=[Citation(source_id="T1:p1:t0", quote="99% 성공")],
        )
    ]
    result = RagAnalysisAgent("tech", lambda *a, **kw: [hit()], FakeAsk(claims=claims))(
        state
    )
    assert "99%" not in result["tech_analysis"]
    assert result["references"] == []


def test_no_cross_source_quote_acceptance(state):
    # quote는 T2에 존재하지만 T1을 인용한다. 전체 corpus 검색으로는 잡을 수 없는 오류.
    claims = [
        Claim(
            text="시장은 500억 달러",
            status="supported",
            citations=[Citation(source_id="T1:p1:t0", quote="시장은 500억 달러")],
        )
    ]
    result = RagAnalysisAgent(
        "tech",
        lambda *a, **kw: [hit(), hit(doc="T2", text="시장은 500억 달러")],
        FakeAsk(claims=claims),
    )(state)
    assert result["references"] == []


def test_only_used_new_references(state):
    ref = documents.reference_for(hit(), "가상 바이오")
    state["references"] = [ref]
    result = RagAnalysisAgent(
        "tech", lambda *a, **kw: [hit(), hit(doc="T2")], FakeAsk()
    )(state)
    assert result["references"] == []


@pytest.mark.parametrize(
    "model,expected", [("pipeline", ["M7"]), ("platform", ["M1", "M6"])]
)
def test_market_model_and_target_preserved(state, model, expected):
    state["startup_profile"]["business_model"] = model
    state["startup_profile"]["lead_service"] = "항체 설계"
    calls = []

    def search(q, **kwargs):
        calls.append((q, kwargs))
        return []

    before = copy.deepcopy(state)
    result = RagAnalysisAgent("market", search, FakeAsk())(state)
    assert calls[0][1]["doc_ids"] == expected
    assert state == before
    assert model in result["market_analysis"]


def test_unknown_market_and_no_web_reported(state):
    state["startup_profile"]["business_model"] = "unknown"
    result = RagAnalysisAgent("market", lambda *a, **kw: [], FakeAsk((False, False)))(
        state
    )
    assert "사업 모델 또는 대표 시장 미확인" in result["market_analysis"]
    assert "웹 보완 미실행" in result["market_analysis"]


def test_web_used_only_after_two_rag_rounds(state):
    calls = []
    claims = [
        Claim(
            text="서비스 시장 근거",
            status="supported",
            citations=[
                Citation(
                    source_id="WEB:https://example.invalid/report",
                    quote="AI 서비스 시장 자료",
                )
            ],
        )
    ]
    ask = FakeAsk((False, False, True), claims)

    def web(q):
        calls.append(q)
        return {
            "results": [
                {
                    "url": "https://example.invalid/report",
                    "content": "AI 서비스 시장 자료",
                    "title": "시장 자료",
                }
            ]
        }

    result = RagAnalysisAgent("market", lambda *a, **kw: [], ask, web)(state)
    assert len(calls) <= 2
    assert result["references"][0]["published_date"] is None
    assert result["references"][0]["year"] is None


def test_web_api_failure_is_not_missing(state):
    def web(q):
        raise RuntimeError("API 오류")

    with pytest.raises(RuntimeError, match="API 오류"):
        RagAnalysisAgent("market", lambda *a, **kw: [], FakeAsk((False, False)), web)(
            state
        )


def test_llm_failure_is_not_missing(state):
    def ask(*args):
        raise RuntimeError("LLM 실패")

    with pytest.raises(RuntimeError, match="LLM 실패"):
        RagAnalysisAgent("tech", lambda *a, **kw: [], ask)(state)


def test_wrong_company_and_corpus_rejected(state):
    state["startup_profile"]["name"] = "다른 회사"
    with pytest.raises(ValueError, match="name"):
        RagAnalysisAgent("tech", lambda *a, **kw: [], FakeAsk())(state)
    state["startup_profile"]["name"] = "가상 바이오"
    with pytest.raises(ValueError, match="코퍼스"):
        RagAnalysisAgent("tech", lambda *a, **kw: [hit("market")], FakeAsk())(state)


def test_token_chunk_overlap_and_page_boundaries():
    class Tokenizer:
        def __call__(self, text, **kw):
            return {"offset_mapping": [(i, i + 1) for i in range(len(text))]}

    pages = [
        {"doc_id": "T1", "page": p, "text": "가나다라마바사아자차타파하"}
        for p in [1, 2]
    ]
    chunks = documents.chunk_pages(pages, Tokenizer(), size=5, overlap=2)
    assert chunks[0]["text"][-2:] == chunks[1]["text"][:2]
    assert all(c["token_count"] <= 5 for c in chunks)
    assert {c["page"] for c in chunks} == {1, 2}
    assert len({c["id"] for c in chunks}) == len(chunks)


def test_rrf_ranks_and_dedup():
    ranking = retrieval.rrf([[0, 1], [1, 2]])
    assert ranking[0][0] == 1
    assert len(ranking) == 3


def test_lexical_preserves_terms():
    tokens = retrieval.lexical_tokens("IND-enabling 임상시험 Phase 1/2 CAGR 18.5")
    assert {"ind-enabling", "phase", "cagr", "18.5"} <= set(tokens)
    assert any("임상" in token for token in tokens)


def test_real_faiss_bm25_filter_before_topk(tmp_path, monkeypatch):
    monkeypatch.setattr(retrieval, "fingerprint", lambda *a: "test")
    path = tmp_path / "technology" / "test"
    path.mkdir(parents=True)
    chunks = [
        hit(doc="T1"),
        hit(doc="T2", text="항체 설계 특허 데이터"),
        hit(doc="T3", text="임상 규제 IND"),
    ]
    (path / "manifest.json").write_text("{}")
    (path / "chunks.json").write_text(json.dumps(chunks))
    (path / "tokens.json").write_text(
        json.dumps([retrieval.lexical_tokens(c["text"]) for c in chunks])
    )
    index = faiss.IndexFlatIP(2)
    index.add(np.array([[1, 0], [0.8, 0.2], [0, 1]], dtype="float32"))
    faiss.write_index(index, str(path / "dense.faiss"))
    monkeypatch.setattr(
        retrieval, "encode", lambda *a, **kw: np.array([[1, 0]], dtype="float32")
    )
    retriever = retrieval.HybridRetriever("tech", tmp_path)
    result = retriever.search("IND", doc_ids=["T3"], top_k=1)
    assert result[0]["doc_id"] == "T3"
    assert retriever.search("no_matching_term_z", mode="bm25") == []


def test_pdf_metadata_original_page_map():
    pages = list(documents.iter_pages("tech"))
    assert len(pages) == 115
    assert {p["page"] for p in pages if p["doc_id"] == "T4"} == {
        257,
        258,
        259,
        260,
        261,
        262,
        263,
        264,
        265,
        268,
    }


def test_evaluation_metrics_and_errors():
    from src.rag.evaluate import evaluate

    class Retriever:
        def __init__(self):
            self.chunks = [{"doc_id": "T1", "page": 1, "text": "원문 정답"}]

        def search(self, query, **kwargs):
            return [
                {"id": "x", "doc_id": "T2", "page": 1, "text": "오답"},
                {"id": "y", **self.chunks[0]},
            ]

    rows = [
        {
            "id": "e1",
            "agent": "tech",
            "question": "질문",
            "relevant": [{"doc_id": "T1", "page": 1, "quote": "원문 정답"}],
        }
    ]
    metrics = evaluate(rows, {"tech": Retriever()}, "dense")
    assert metrics["Hit@1"] == 0 and metrics["Hit@3"] == 1 and metrics["MRR@5"] == 0.5
    with pytest.raises(ValueError):
        evaluate([], {}, "dense")


def test_agent_import_does_not_load_model():
    import subprocess
    import sys

    command = 'import sys; import src.agents.agent3a_tech, src.agents.agent3b_market; assert "torch" not in sys.modules'
    subprocess.run([sys.executable, "-c", command], check=True)


def test_unknown_business_cannot_create_qd_numeric_claim(state):
    state["startup_profile"]["business_model"] = "unknown"
    claims = [
        Claim(
            text="기업 대표 시장 500억 달러",
            status="supported",
            citations=[Citation(source_id="M1:p1:t0", quote="500억 달러 시장")],
        )
    ]
    result = RagAnalysisAgent(
        "market",
        lambda *a, **kw: [hit("market", "M1", "500억 달러 시장")],
        FakeAsk(claims=claims),
    )(state)
    assert "기업 대표 시장 500억" not in result["market_analysis"]
    assert result["references"] == []


def test_missing_required_sections_are_explicit(state):
    result = RagAnalysisAgent("tech", lambda *a, **kw: [hit()], FakeAsk())(state)
    assert "## QG 기술 독창성·AI 진위" in result["tech_analysis"]
    assert "## 규제 리스크" in result["tech_analysis"]


def test_citation_repair_is_one_bounded_llm_call(state):
    calls = []
    base = FakeAsk()

    def ask(schema, payload):
        if schema is AnalysisDraft:
            calls.append(payload)
            if len(calls) == 1:
                return AnalysisDraft(
                    sections=[
                        Section(
                            title="QH 실험·개발 성숙도",
                            claims=[
                                Claim(
                                    text="검증 오류",
                                    status="supported",
                                    citations=[
                                        Citation(
                                            source_id="T2:p1:t0",
                                            quote="IND 신청과 IND 승인은 다른 단계입니다.",
                                        )
                                    ],
                                )
                            ],
                        )
                    ]
                )
        return base(schema, payload)

    result = RagAnalysisAgent("tech", lambda *a, **kw: [hit()], ask)(state)
    assert len(calls) == 2
    assert "citation_errors" in calls[1]
    assert result["references"][0]["title"] == "검증 자료"
