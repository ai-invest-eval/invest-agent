import copy
import unittest
from typing import get_type_hints

from examples.competitor.demo import fixture_analysis, fixture_search, fixture_state
from src.agents.competitor import CompetitorAgent
from src.state import InvestmentState


class AgentTests(unittest.TestCase):
    def run_agent(self, state=None, analyze=fixture_analysis, search=fixture_search):
        return CompetitorAgent(search, analyze)(state or fixture_state())

    def test_v10_types_and_no_mutation(self):
        state = fixture_state()
        before = copy.deepcopy(state)
        result = self.run_agent(state)
        self.assertEqual(state, before)
        self.assertEqual(set(result), {"competitor_analysis", "references"})
        self.assertIsInstance(result["competitor_analysis"], str)
        for key in ("QI", "QJ", "QK", "QL", "QM", "SWOT"):
            self.assertIn(key, result["competitor_analysis"])
        ref = result["references"][0]
        self.assertEqual(ref["company"], state["startup_profile"]["name"])
        self.assertEqual(ref["agent"], "competitor")
        self.assertEqual(ref["source"], "web")
        self.assertIsNone(ref["year"])  # 발행연도 미제공 ≠ 현재 연도
        self.assertEqual(get_type_hints(InvestmentState)["tech_analysis"], str)

    def test_missing_profile_rejected_before_search(self):
        for profile in (None, {}, {"name": 123}):
            state = fixture_state()
            state["startup_profile"] = profile
            with self.assertRaises(TypeError):
                self.run_agent(state, search=lambda q: self.fail("search must not run"))

    def test_profile_fields_survive(self):
        state = fixture_state()
        state["startup_profile"]["custom_validation"] = {"prospective": False}

        def analyze(payload):
            for key, value in state["startup_profile"].items():
                self.assertEqual(payload["startup_profile"][key], value)
            return fixture_analysis(payload)

        self.run_agent(state, analyze)

    def test_legacy_dict_analysis_rejected_before_search(self):
        state = fixture_state()
        state["tech_analysis"] = {"claims": []}
        with self.assertRaises(TypeError):
            self.run_agent(state, search=lambda q: self.fail("search must not run"))

    def test_other_company_references_filtered(self):
        state = fixture_state()
        state["references"].append(
            dict(state["references"][0], company="이전 기업", title="OLD")
        )

        def analyze(payload):
            self.assertNotIn("OLD", str(payload))
            return fixture_analysis(payload)

        self.run_agent(state, analyze)

    def test_bad_id_and_quote_cannot_support_scoring(self):
        for bad in ("id", "quote"):

            def analyze(payload, bad=bad):
                d = fixture_analysis(payload)
                c = d["competitors"][0]["relevance"]
                c["status"] = "supported"
                c["citations"][0]["source_id" if bad == "id" else "quote"] = "invented"
                d["criterion_evidence"]["QJ"] = {"availability": "found", "claims": [c]}
                return d

            result = self.run_agent(analyze=analyze)
            self.assertIn("정보 없음: 근거 인용", result["competitor_analysis"])
            self.assertEqual(result["references"], [])

    def test_upstream_is_not_primary_evidence(self):
        def analyze(payload):
            return {
                "criterion_evidence": {
                    "QK": {
                        "availability": "confirmed_absent",
                        "claims": [
                            {
                                "text": "계약이 없다",
                                "status": "supported",
                                "citations": [
                                    {
                                        "source_id": "market_analysis",
                                        "quote": payload["market_analysis"],
                                    }
                                ],
                            }
                        ],
                    }
                }
            }

        result = self.run_agent(analyze=analyze)
        self.assertIn("[추론]", result["competitor_analysis"])
        self.assertNotIn("자료 상태: 확인된 없음", result["competitor_analysis"])

    def test_confirmed_absent_kept_with_source(self):
        def analyze(payload):
            d = fixture_analysis(payload)
            source = next(s for s in payload["sources"] if s["kind"] == "web")
            d["criterion_evidence"]["QK"] = {
                "availability": "confirmed_absent",
                "claims": [
                    {
                        "text": "[가상] 계약 없음",
                        "status": "supported",
                        "citations": [
                            {
                                "source_id": source["source_id"],
                                "quote": "유료 계약이 없다.",
                            }
                        ],
                    }
                ],
            }
            return d

        result = self.run_agent(
            analyze=analyze,
            search=lambda q: {
                "results": [
                    {
                        "url": "https://example.org/absence",
                        "content": "유료 계약이 없다. 가상신약 B는 제약사의 항체 설계 업무를 지원한다.",
                    }
                ]
            },
        )
        self.assertIn("자료 상태: 확인된 없음", result["competitor_analysis"])

    def test_no_fixed_quota_and_self_duplicate_removed(self):
        def analyze(payload):
            d = fixture_analysis(payload)
            c = d["competitors"][0]
            d["competitors"] += [copy.deepcopy(c), dict(c, name="가상신약 A")]
            return d

        text = self.run_agent(analyze=analyze)["competitor_analysis"]
        self.assertEqual(text.count("### 가상신약 B"), 1)
        self.assertNotIn("### 가상신약 A", text)
        self.assertNotIn("1/2", text)

    def test_missing_sources_skip_llm(self):
        state = fixture_state()
        state["tech_analysis"] = ""
        state["market_analysis"] = ""
        result = self.run_agent(
            state, lambda p: self.fail("no evidence"), lambda q: {"results": []}
        )
        self.assertIn("분석 가능한 근거 없음", result["competitor_analysis"])

    def test_failure_is_bounded_and_redacted(self):
        calls = []

        def search(q):
            calls.append(q)
            raise RuntimeError("secret-key")

        def analyze(p):
            raise RuntimeError("secret-key")

        result = CompetitorAgent(search, analyze, max_searches=99)(fixture_state())
        self.assertEqual(len(calls), 3)
        self.assertNotIn("secret-key", str(result))
        self.assertIn("구조화 분석 생성 실패", result["competitor_analysis"])

    def test_only_new_used_references_returned(self):
        state = fixture_state()
        first = self.run_agent(state)
        state["references"] += first["references"]
        self.assertEqual(self.run_agent(state)["references"], [])

    def test_null_content_and_page_only_reference(self):
        state = fixture_state()
        state["references"][0]["content"] = None
        result = self.run_agent(state)
        self.assertIsInstance(result["competitor_analysis"], str)

    def test_no_unused_search_reference_leak(self):
        result = self.run_agent(analyze=lambda p: {})
        self.assertEqual(result["references"], [])
        self.assertIn("자료 상태: 정보 없음", result["competitor_analysis"])

    def test_parallel_graph_v10(self):
        from langgraph.graph import END, START, StateGraph

        graph = StateGraph(InvestmentState)
        graph.add_node(
            "tech",
            lambda s: {
                "tech_analysis": "가상 기술 분석",
                "references": [
                    {
                        "company": "가상신약 A",
                        "agent": "tech",
                        "title": "T",
                        "source": "RAG",
                        "page": 1,
                        "issuer": "기관",
                        "year": 2026,
                        "doc_type": "report",
                    }
                ],
            },
        )
        graph.add_node(
            "market",
            lambda s: {
                "market_analysis": "가상 시장 분석",
                "references": [
                    {
                        "company": "가상신약 A",
                        "agent": "market",
                        "title": "M",
                        "source": "RAG",
                        "page": 2,
                        "issuer": "기관",
                        "year": 2026,
                        "doc_type": "report",
                    }
                ],
            },
        )
        calls = []

        def node(state):
            calls.append(1)
            self.assertEqual(state["tech_analysis"], "가상 기술 분석")
            self.assertEqual(state["market_analysis"], "가상 시장 분석")
            return self.run_agent(state)

        graph.add_node("competitor", node)
        graph.add_edge(START, "tech")
        graph.add_edge(START, "market")
        graph.add_edge(["tech", "market"], "competitor")
        graph.add_edge("competitor", END)
        state = fixture_state()
        state["references"] = []
        result = graph.compile().invoke(state)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(result["references"]), 3)
        self.assertIsInstance(result["competitor_analysis"], str)


if __name__ == "__main__":
    unittest.main()
