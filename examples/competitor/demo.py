"""v10 오프라인 데모. 가상 AI 신약 기업/문장만 사용하며 API 호출은 없다."""

import json
from pathlib import Path

from src.agents.competitor import CompetitorAgent


def fixture_state():
    return {
        "input_keyword": "AI 신약개발 스타트업",
        "startup_profile": {
            "name": "가상신약 A",
            "founded_year": 2023,
            "platform": "항체 설계 AI",
            "pipeline": [{"indication": "가상 적응증", "stage": "전임상"}],
            "lead_indication": "가상 적응증",
            "funding_history": [],
            "partnerships": [],
            "team": [],
            "founder_degree_career": "정보 없음",
            "ceo_full_time": None,
            "upfront_payment": None,
            "pre_money_valuation": None,
            "gates": {
                "not_eligible": None,
                "subsidiary_of_large_corp": None,
                "clinical_failure": None,
                "founder_exit_or_dispute": None,
                "patent_loss": None,
                "funding_gap_restructuring": None,
            },
            "missing_fields": [
                "ceo_full_time",
                "upfront_payment",
                "pre_money_valuation",
            ],
        },
        "tech_analysis": "[가상 테스트] 가상신약 A는 항체 설계 AI를 개발한다. 전향적 비교 실험은 정보 없음.",
        "market_analysis": "[가상 테스트] 제약사의 항체 설계 업무를 지원한다. 시장 수치와 유료 계약은 정보 없음.",
        "references": [
            {
                "company": "가상신약 A",
                "agent": "tech",
                "title": "가상 기술 자료",
                "source": "RAG",
                "page": 12,
                "issuer": "가상기관",
                "year": 2026,
                "doc_type": "report",
            }
        ],
        "evaluation_history": [],
    }


def fixture_search(query):
    return {
        "results": [
            {
                "url": "https://example.org/drug-discovery-fixture",
                "title": "가상 비교 자료",
                "content": "가상신약 B는 제약사의 항체 설계 업무를 지원한다. A와 B의 직접 비교 결과는 공개되지 않았다.",
            }
        ]
    }


def fixture_analysis(payload):
    source = next(s for s in payload["sources"] if s["kind"] == "web")
    claim = {
        "text": "[더미] 같은 고객의 항체 설계 업무가 겹칠 수 있다.",
        "status": "inference",
        "citations": [
            {
                "source_id": source["source_id"],
                "quote": "가상신약 B는 제약사의 항체 설계 업무를 지원한다.",
            }
        ],
    }
    return {
        "competitors": [
            {
                "name": "가상신약 B",
                "product": "항체 설계 AI",
                "category": "peer",
                "relevance": claim,
                "comparison": [],
            }
        ],
        "criterion_evidence": {
            "QI": {
                "availability": "unknown",
                "claims": [],
                "missing_information": ["동일 조건의 성능 비교 자료 없음"],
            }
        },
        "swot": {"threats": [claim]},
        "missing_information": [
            "가상 데이터로 형식만 검증한 예제. 실제 투자 분석 아님."
        ],
    }


if __name__ == "__main__":
    result = CompetitorAgent(fixture_search, fixture_analysis)(fixture_state())
    output = Path(__file__).resolve().parents[2] / "outputs" / "competitor_demo.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    output.with_suffix(".md").write_text(
        result["competitor_analysis"] + "\n", encoding="utf-8"
    )
    print(result["competitor_analysis"])
    print("Saved:", output)
