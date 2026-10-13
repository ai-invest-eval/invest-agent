"""품질 평가 노드 (D 담당) — Hybrid: 규칙 검사(결정적) + LLM Judge(내용).

- 평가 항목: Groundedness · 중립성 · 편향 통제 (+ 보고서 형식). 관점 커버리지는 검사하지 않는다.
- 이 노드는 **판정만** 한다. 다음 경로는 routing.py의 route_after_eval이 정한다.
- rule_checks()는 finalize가 최종 Markdown으로 다시 계산할 수 있도록 공개 함수로 둔다.

보고서 형식(실제 생성물 기준):
- 본문 인용은 인라인 번호가 아니라 "(저자·기관명, 연도)" 괄호 표기. 예: (Jayatunga 외, 2024)
- REFERENCE는 유형별 그룹(기관 보고서/학술 논문/웹페이지)이고 번호가 그룹마다 1부터 다시 시작한다.
- 3A/3B 분석 텍스트의 "원문 근거: “…” [ID]" 줄을 파싱한다. A 계약(EvidenceItem.excerpt_verified)에 따라
  quality_eval이 색인의 원문 청크(chunks.json)를 직접 읽어 인용문이 있는지 다시 확인한 것만 source_excerpt로 둔다.
  원문을 확보·확인하지 못하면 analysis_rationale(source_locator에 ID 보존, excerpt_verified=False)로 분류한다.
  비교 방식은 rag_analysis.py와 같다(normalize_text 후 공백 제거·대소문자 무시).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from functools import lru_cache
from typing import Callable

from pydantic import BaseModel, Field

from src.config import LLM_MODEL, LLM_TEMPERATURE

try:  # 뼈대 머지 전에도 import 오류 없이 단독 테스트할 수 있게 한다.
    from src.orchestration.observability import log_decision
except ImportError:  # pragma: no cover
    def log_decision(*args, **kwargs):
        return None


MAX_PAGES_RULE = 10
MIN_REFERENCES = 3
MAX_ISSUER_SHARE = 0.5
JUDGE_PASS_SCORE = 3
EVIDENCE_TEXT_LIMIT = 300

FORBIDDEN_WORDING = re.compile(r"최고의|압도적|반드시 투자|확실한 수익|유일한")
RISK_PATTERN = re.compile(r"핵심 리스크|리스크|보류 사유|추천 없음 사유|판정 사유")
# (이름, 2024) / (이름 외, 2024) — 연도가 없는 괄호는 출처 표기가 아니므로 건너뛴다.
CITATION_PATTERN = re.compile(r"\(([^()]{2,60}?),\s*((?:19|20)\d{2})\)")
EXCERPT_PATTERN = re.compile(r"원문 근거:\s*[“\"](.+?)[”\"]\s*\[([^\]]+)\]")
QUESTION_KEY = re.compile(r"\bQ[A-O]\b")

# 3점 미만 Judge 항목마다 코드가 넣는 기본 피드백 (issues가 비어도 재작성 루프가 끊기지 않게)
DEFAULT_FEEDBACK = {
    "groundedness": "Groundedness 미달: 근거와 다른 주장을 근거에 맞게 고치거나 삭제",
    "neutrality": "중립성 미달: 근거 없는 우열·과장 표현을 사실 서술로 변경",
    "bias": "편향 통제 미달: 누락된 리스크·결측 정보를 해당 문단에 추가",
}

FIXABLE_RULE_FEEDBACK = {
    "grounded_citations": "Groundedness: 본문 출처 표기 중 REFERENCE에 없는 것을 고치거나 삭제",
    "neutral_wording": "중립성: 금지 표현(최고의·압도적·반드시 투자·확실한 수익·유일한)을 사실 서술로 변경",
    "risk_present": "편향 통제: 핵심 리스크 또는 보류 사유 문장을 추가",
    "format_order": "형식: 첫 장 SUMMARY, 마지막 장 REFERENCE 순서 유지",
}


# ─────────────────────────────────────────── 1안: 규칙 검사

def _headings(md: str) -> list[str]:
    return re.findall(r"^## (.+)$", md, flags=re.MULTILINE)


def _body_and_reference(md: str) -> tuple[str, str]:
    parts = md.split("\n## REFERENCE", 1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


def reference_entries(md: str) -> list[dict]:
    """REFERENCE 섹션의 항목을 {label, year, line}으로 읽는다(그룹별 번호 재시작에 영향 없음)."""
    _, ref = _body_and_reference(md)
    entries = []
    for line in ref.splitlines():
        m = re.match(r"^\s*\d+\.\s+(.+)$", line)
        if not m:
            continue
        text = m.group(1)
        year = re.search(r"\(((?:19|20)\d{2})(?:-\d{2}-\d{2})?\)", text)
        label = text.split("(", 1)[0].strip().rstrip(",.")
        entries.append({"label": label, "year": year.group(1) if year else None, "line": text})
    return entries


def _citation_matches(name: str, year: str, entries: list[dict]) -> bool:
    key = re.sub(r"\s*외$", "", name.strip())
    key = key.split(",")[0].split()[0] if key else key
    for e in entries:
        if e["year"] == year and key and key in e["line"]:
            return True
    return False


def rule_checks(md: str, references: list | None = None, pages: int | None = None) -> tuple[dict, list[str], list[str]]:
    """규칙 결과와 (재작성 가능 피드백, 구조적 미달) 목록을 돌려준다.

    references는 받지만 현재는 사용하지 않는다(보고서에 실제 표시된 REFERENCE 기준으로 계산).
    """
    checks: dict[str, bool] = {}
    fixable: list[str] = []
    structural: list[str] = []
    body, _ = _body_and_reference(md)
    entries = reference_entries(md)
    heads = _headings(md)

    # ── 재작성 가능 규칙
    citations = CITATION_PATTERN.findall(body)
    unmatched = [f"{n}, {y}" for n, y in citations if not _citation_matches(n, y, entries)]
    checks["grounded_citations"] = not unmatched
    checks["neutral_wording"] = not FORBIDDEN_WORDING.search(body)
    checks["risk_present"] = bool(RISK_PATTERN.search(body))
    checks["format_order"] = bool(heads) and heads[0] == "SUMMARY" and heads[-1] == "REFERENCE"
    for name in ("grounded_citations", "neutral_wording", "risk_present", "format_order"):
        if not checks[name]:
            detail = f" ({'; '.join(unmatched[:3])})" if name == "grounded_citations" else ""
            fixable.append(FIXABLE_RULE_FEEDBACK[name] + detail)

    if pages is None:
        checks["page_limit"] = False  # 쪽수 미확인 — 재작성으로 고칠 수 없으므로 피드백 없음
    else:
        checks["page_limit"] = pages <= MAX_PAGES_RULE
        if not checks["page_limit"]:
            fixable.append(f"쪽수 초과: {pages}쪽 → {MAX_PAGES_RULE}쪽 이내로 문단 축약")

    # ── 구조적 규칙 (재작성으로 못 고침 → 경고만)
    checks["reference_count"] = len(entries) >= MIN_REFERENCES
    if not checks["reference_count"]:
        structural.append(f"reference_count: REFERENCE {len(entries)}개 (기준 {MIN_REFERENCES}개 이상)")
    labels = [e["label"] for e in entries]
    top_share = max((labels.count(l) for l in set(labels)), default=0) / len(labels) if labels else 0
    checks["issuer_concentration"] = top_share <= MAX_ISSUER_SHARE
    if not checks["issuer_concentration"]:
        structural.append(f"issuer_concentration: 단일 발행처 비중 {top_share:.0%} (기준 {MAX_ISSUER_SHARE:.0%} 이하)")
    return checks, fixable, structural


# ─────────────────────────────────────────── Groundedness 근거 묶음

def _cut(text: str) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= EVIDENCE_TEXT_LIMIT else text[: EVIDENCE_TEXT_LIMIT - 1] + "…"


def _ref_label(ref: dict) -> str:
    authors = ref.get("authors") or []
    name = (authors[0].split(",")[0] + " 외") if authors else (ref.get("issuer") or ref.get("site_name") or ref.get("title") or "출처")
    return f"{name}, {ref.get('year') or '연도 미상'}"


@lru_cache(maxsize=1)
def _index_chunks() -> dict[str, str]:
    """RAG 색인의 원문 청크 {chunk_id: text}. 색인이 없거나 읽기에 실패하면 빈 dict."""
    try:
        from src.rag.documents import DATA_DIR, GROUPS, fingerprint

        texts: dict[str, str] = {}
        for agent, group in GROUPS.items():
            path = DATA_DIR / "index" / group / fingerprint(agent) / "chunks.json"
            if path.exists():
                for chunk in json.loads(path.read_text(encoding="utf-8")):
                    texts[chunk["id"]] = chunk["text"]
        return texts
    except Exception:  # noqa: BLE001 — 원문 미확보는 검증 한계로 기록할 뿐 실패가 아니다
        return {}


def _squash(text: str) -> str:
    try:
        from src.rag.documents import normalize_text

        text = normalize_text(text)
    except Exception:  # noqa: BLE001
        pass
    return re.sub(r"\s+", "", text or "").casefold()


def verify_excerpt(quote: str, source_id: str, chunks: dict[str, str] | None = None) -> bool:
    """인용문이 해당 원문 청크에 있는지 다시 확인한다(rag_analysis.py와 같은 비교 방식)."""
    chunks = _index_chunks() if chunks is None else chunks
    content = chunks.get(source_id)
    q = _squash(quote)
    return bool(content) and len(q) >= 4 and q in _squash(content)


def parse_excerpts(analysis_text: str) -> list[dict]:
    """분석 텍스트의 '원문 근거' 줄을 {question, text, source_ids}로 뽑는다. 직전 '## 섹션'의 질문 키를 붙인다."""
    out, question = [], None
    for line in (analysis_text or "").splitlines():
        if line.startswith("## "):
            q = QUESTION_KEY.search(line)
            question = q.group(0) if q else None
            continue
        m = EXCERPT_PATTERN.search(line)
        if m:
            out.append({"question": question, "text": m.group(1), "source_ids": [s.strip() for s in m.group(2).split(",")]})
    return out


def _task_order(state: dict) -> dict[str, int]:
    order = {}
    for item in state.get("worker_results") or []:
        order.setdefault(item.get("company"), item.get("task_index", 10**6))
    for task in state.get("plan") or []:
        order.setdefault((task.get("company") or {}).get("name"), task.get("task_index", 10**6))
    return order


def build_evidence_bundle(state: dict, chunks: dict[str, str] | None = None) -> tuple[list[dict], str]:
    """보고서에 나오는 모든 기업의 근거 묶음과 source_verification을 돌려준다.

    chunks: 테스트용 원문 청크 주입. None이면 RAG 색인에서 읽는다.
    """
    order = _task_order(state)
    # plan/worker_results가 없으면(단독 테스트 등) evaluation_history의 원래 순서를 유지한다.
    records = [r for _, r in sorted(
        enumerate(state.get("evaluation_history") or []),
        key=lambda pair: (order.get(pair[1].get("name"), 10**6), pair[0]),
    )]
    bundle: list[dict] = []
    for fallback_index, r in enumerate(records):
        company = r.get("name")
        idx = order.get(company, fallback_index)
        base = {"company": company, "task_index": idx}
        for q, ev in sorted((r.get("question_evidence") or {}).items()):
            if ev.get("missing"):
                continue
            bundle.append({**base, "claim_area": "question", "question": q, "evidence_kind": "analysis_rationale",
                           "text": _cut(ev.get("rationale")),
                           "source_ids": [_ref_label(x) for x in ev.get("references") or []],
                           "source_locator": None, "excerpt_verified": False})
        rule_text = f"판정 {r.get('verdict')} · 총점 {r.get('total', 0):.1f} · 결측 비중 {r.get('missing_weight', 0):.0%}"
        if r.get("hold_reason"):
            rule_text += f" · 보류 사유 {r['hold_reason']}"
        if r.get("unconfirmed_gates"):
            rule_text += f" · 미확인 관문 {', '.join(r['unconfirmed_gates'])}"
        bundle.append({**base, "claim_area": "hold_reason" if r.get("hold_reason") else "summary",
                       "question": None, "evidence_kind": "rule_result", "text": _cut(rule_text), "source_ids": [],
                       "source_locator": None, "excerpt_verified": False})
        for field in ("tech_analysis", "market_analysis"):
            for ex in parse_excerpts(r.get(field) or ""):
                verified = all(verify_excerpt(ex["text"], sid, chunks) for sid in ex["source_ids"])
                bundle.append({**base, "claim_area": "question", "question": ex["question"],
                               "evidence_kind": "source_excerpt" if verified else "analysis_rationale",
                               "text": _cut(ex["text"]), "source_ids": ex["source_ids"],
                               "source_locator": ", ".join(ex["source_ids"]), "excerpt_verified": verified})

    kinds = {b["evidence_kind"] for b in bundle if b["evidence_kind"] != "rule_result"}
    if not bundle:
        verification = "none"
    elif kinds == {"source_excerpt"}:
        verification = "excerpt"
    elif "source_excerpt" in kinds:
        verification = "mixed"
    else:
        verification = "consistency_only"
    return bundle, verification


# ─────────────────────────────────────────── 2안: LLM Judge

QUALITY_JUDGE_PROMPT = """[역할] 투자 심사 보고서의 품질 검토자. 투자 판단이 옳은지가 아니라, 보고서가 근거에 충실하고 균형 잡혔는지를 평가한다.

[입력]
- 보고서 Markdown
- evidence_bundle: 기업별 근거 {company, claim_area, question, evidence_kind, text, source_ids}
  · source_excerpt: 원문 대조를 통과한 인용문 → 주장과 원문 연결을 엄격히 평가
  · analysis_rationale: 앞 단계 분석 근거 → 보고서 서술과의 일관성만 평가
  · rule_result: 코드가 계산한 점수·판정 → 보고서 숫자·판정과 일치하는지만 확인

[평가 항목] 각 1~5점, 3점 미만이면 issues에 고칠 위치와 이유를 적는다.
1. groundedness: 보고서의 주요 주장을 evidence_bundle과 대조. 근거에 없는 수치·사실, 근거와 다른 해석, 근거보다 과장된 서술이 있으면 감점.
2. neutrality: 점수·규칙으로 정해진 순위·판정 외에, 근거 없는 우열 판정, 과장·홍보성 표현, 단정적 수익 전망이 있으면 감점.
3. bias: 유리한 근거만 제시하고 리스크·결측을 숨기거나, 근거를 한쪽 출처에만 기대어 서술하면 감점.

[규칙]
- 보고서와 evidence_bundle에 없는 정보를 상상해 평가하지 않는다.
- 순위표와 통과/보류 판정은 코드 규칙의 결과이므로 그 자체로 중립성 감점 대상이 아니다.
- "정보 부족"이라고 명시한 부분은 결측을 숨기지 않은 것으로 보고 감점하지 않는다.
- issues는 "섹션명: 문제 → 수정 방향" 형식, 최대 6개. 문장 재작성으로 고칠 수 있는 문제만 적는다."""


class JudgeOutput(BaseModel):
    groundedness: int = Field(ge=1, le=5)
    neutrality: int = Field(ge=1, le=5)
    bias: int = Field(ge=1, le=5)
    issues: list[str] = Field(default_factory=list, max_length=6)


JudgeFn = Callable[[str, list[dict]], "JudgeOutput | None"]


def llm_judge(md: str, bundle: list[dict]) -> JudgeOutput | None:
    """기본 Judge. 키가 없거나 호출이 실패하면 None (→ judge_status='unavailable')."""
    if not os.getenv("OPENAI_API_KEY"):
        return None
    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model=LLM_MODEL, temperature=LLM_TEMPERATURE, timeout=60, max_retries=1)
        payload = json.dumps({"report_markdown": md, "evidence_bundle": bundle}, ensure_ascii=False)
        return llm.with_structured_output(JudgeOutput).invoke(
            [("system", QUALITY_JUDGE_PROMPT), ("human", payload)]
        )
    except Exception:  # noqa: BLE001 — Judge 장애는 판정 불가로 기록하고 그래프는 계속 진행
        return None


# ─────────────────────────────────────────── 노드

def evaluate(state: dict, judge_fn: JudgeFn | None = None,
             chunks: dict[str, str] | None = None) -> tuple[dict, list[str], str | None]:
    """매 평가마다 checks·issues·can_rewrite·passed를 처음부터 새로 계산한다(이전 판정 재사용 없음)."""
    md = state.get("final_report") or ""
    pages = state.get("report_pages")
    checks, fixable, structural = rule_checks(md, state.get("references"), pages)
    bundle, verification = build_evidence_bundle(state, chunks)

    judge = (judge_fn or llm_judge)(md, bundle)
    judge_status = "completed" if judge is not None else "unavailable"
    scores = None
    if judge is not None:
        scores = {"groundedness": judge.groundedness, "neutrality": judge.neutrality, "bias": judge.bias}
        low = [k for k, v in scores.items() if v < JUDGE_PASS_SCORE]
        for k in low:
            fixable.append(DEFAULT_FEEDBACK[k])
        if low:
            fixable.extend(judge.issues)

    passed = (
        all(checks.values())
        and judge_status == "completed"
        and all(v >= JUDGE_PASS_SCORE for v in (scores or {}).values())
        and pages is not None
    )
    verdict = {
        "passed": passed,
        "can_rewrite": bool(fixable),
        "judge_status": judge_status,
        "source_verification": verification,
        # 평가한 본문 식별용. finalize가 본문을 바꾸면 hash가 달라져 Judge 결과가 최종 본문과 다름을 알 수 있다.
        "evaluated_body_hash": hashlib.sha256(md.encode("utf-8")).hexdigest(),
        "termination_reason": None,  # finalize가 기록
        "rule_checks": checks,
        "judge_scores": scores,
        "fixable_issues": fixable,
        "structural_issues": structural,
        "attempt": state.get("report_attempts", 0),
    }
    error = None if judge is not None else "quality_eval: LLM Judge 미실행(키 없음 또는 호출 실패)"
    return verdict, fixable, error


def build_quality_eval(judge_fn: JudgeFn | None = None, chunks: dict[str, str] | None = None):
    """Judge·원문 청크를 바꿔 끼운 노드를 만든다(테스트·fixture용). 그래프 노드 시그니처는 (state)."""

    def node(state: dict) -> dict:
        return _run(state, judge_fn, chunks)

    return node


def quality_eval(state: dict) -> dict:
    """판정만 한다(분기는 routing.py). QualityEvalUpdate 키를 돌려준다."""
    return _run(state, None, None)


def _run(state: dict, judge_fn: JudgeFn | None, chunks: dict[str, str] | None) -> dict:
    verdict, feedback, error = evaluate(state, judge_fn, chunks)
    log_decision(
        state.get("trace_id"), "quality_eval",
        decision="pass" if verdict["passed"] else "fail",
        reason=f"can_rewrite={verdict['can_rewrite']} judge={verdict['judge_status']} "
               f"fixable={len(verdict['fixable_issues'])} structural={len(verdict['structural_issues'])}",
        attempt=verdict["attempt"], source_verification=verdict["source_verification"],
    )
    update = {
        "eval_result": verdict,
        "eval_feedback": feedback,
        "step_count": 1,
        "node_status": {"quality_eval": "pass" if verdict["passed"] else "fail"},
    }
    if error:
        update["last_error"] = error
    return update
