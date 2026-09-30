"""Agent 5 채점 설정값. 투자평가기준 v4 7장과 같은 값이다.

판정에 쓰는 숫자는 모두 여기서 관리한다. LLM은 이 값을 모르고 코드만 사용한다.
"""

WEIGHTS = {
    "founder": 0.30,
    "market": 0.25,
    "product": 0.15,
    "moat": 0.10,
    "traction": 0.10,
    "deal": 0.10,
}

QUESTIONS = {
    "founder": ["QA", "QB", "QC"],
    "market": ["QD", "QE", "QF"],
    "product": ["QG", "QH"],
    "moat": ["QI", "QJ"],
    "traction": ["QK", "QL", "QM"],
    "deal": ["QN", "QO"],
}
ALL_QUESTIONS = [q for qs in QUESTIONS.values() for q in qs]

AREA_NAMES = {
    "founder": "창업자",
    "market": "시장성",
    "product": "제품·기술력",
    "moat": "경쟁우위",
    "traction": "실적",
    "deal": "투자조건",
}

# 관문: 자격 관문은 None이어도 보류, 리스크 관문은 True일 때만 보류
ELIGIBILITY_GATES = ["not_eligible", "subsidiary_of_large_corp"]
RISK_GATES = [
    "clinical_failure",
    "founder_exit_or_dispute",
    "patent_loss",
    "funding_gap_restructuring",
]
GATE_LABELS = {
    "not_eligible": "상장 완료 또는 시리즈 D 이상",
    "subsidiary_of_large_corp": "대기업 자회사",
    "clinical_failure": "주력 파이프라인 임상 중단·실패",
    "founder_exit_or_dispute": "창업자·CEO 이탈 또는 경영권 분쟁",
    "patent_loss": "핵심 특허 분쟁 패소",
    "funding_gap_restructuring": "24개월 이상 투자 공백 + 구조조정 보도",
}

PASS_SCORE = 75
FOUNDER_MIN = 60
MISSING_SCORE = 2  # 정보 없음 → 2점
MISSING_SCORE_DEAL = 3  # QN·QO 정보 없음 → 3점 (결측 비중에는 포함)
DEAL_QUESTIONS = ["QN", "QO"]
MAX_MISSING_WEIGHT = 0.30  # 결측 비중 30% 이상 → 보류(근거 부족)

BUSINESS_MODELS = ["pipeline", "platform", "unknown"]  # unknown → QD 결측

# 영역별로 LLM에 보여줄 State 칸 (v4 2장 "채점 근거 State" + 보조 자료)
AREA_CONTEXT = {
    "founder": ["startup_profile"],
    "market": ["market_analysis", "startup_profile"],
    "product": ["tech_analysis", "startup_profile"],
    "moat": ["competitor_analysis", "tech_analysis"],
    "traction": ["startup_profile", "competitor_analysis"],
    "deal": ["startup_profile", "competitor_analysis"],
}

# LLM 호출 실패 시 재시도 횟수 (API 오류를 결측으로 위장하지 않고, 재시도 후에도 실패하면 예외)
LLM_RETRIES = 1
