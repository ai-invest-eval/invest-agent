# 확정 프로필 계약과 QN 계산 샘플

모든 기업·사람·금액·사건·URL은 가상이다. 실제 투자 평가 자료로 쓰지 않는다. example.invalid는 실출처가 아니다. JSON은 Agent 2 반환형(startup_profile, references) 예시이지 앱 입력용 전체 State가 아니다.

## 1. 확정 프로필 구조: 2번 → 5번

| 예시 | 특징 | 파일 |
| --- | --- | --- |
| 가상 바이오 A | 해외 시리즈 BF, 임상 1/2상, USD 투자금·선급금·기업가치 확인 | [파이프라인형 JSON](../samples/profile_pipeline_proposal.json) |
| 가상 플랫폼 B | 국내 시리즈 A, 자체 파이프라인 없음 확인, 기업가치 비공개 | [플랫폼형 JSON](../samples/profile_platform_proposal.json) |

파일명의 proposal은 최초 생성 시 이름이며 현재 내용은 확정 계약 예시다. schemas.py의 FundingRound/Investor/Partnership/TeamMember를 따른다. 항목별 references는 Reference 객체 목록이며 웹·RAG를 같은 형식으로 연결한다. 실제 근거 없는 데이터는 만들지 않는다.

- 금액은 MonetaryAmount를 재사용한다. A의 기업가치 144,000,000달러는 고정 가정으로 201,600,000,000원이다.
- pipeline=[]는 확인된 자체 파이프라인 없음이다. 미확인이면 null이다.
- B의 선급금 0은 확인된 없음이다. 비공개면 null이다.
- upfront_payment_basis는 대표 선급금의 계약·날짜·근거를 연결한다. 여러 계약의 선급금을 합산하지 않는다.
- valuation_date·valuation_references는 pre-money 기준일·근거다. 투자 유치 금액을 기업가치로 대체하지 않는다.
- 임상 1/2상은 그대로 보존하며 임상 2상 완료로 취급하지 않는다.
- 두 예시는 QA~QO 전 질문의 충분한 근거를 보장하지 않는다. 팀 유지·계획 달성 등은 추가 출처를 수집해 분석하고 부족하면 결측 처리한다.

상세 집계·결측 규칙은 [공통 데이터 계약](data_contracts.md)을 따른다. 내부 필드 정의를 다시 합의할 필요는 없다.

## 2. QN: 투자평가기준 v4 그대로

QN의 같은 단계 중앙값 대비 구간과 정보 미확인 시 결측 3점 규칙은 이미 확정됐다. 이전 제안인 기간 24개월·최소 3개 표본 조건은 채택하지 않는다. 구현 담당자가 비교 출처·기준시점·단계·조건을 검증하고 question_evidence에 남긴다. 출처 없는 중앙값은 만들지 않는다.

아래 세 기업은 계산 설명을 위한 가상 숫자이며 최소 표본 수 규칙을 뜻하지 않는다.

| 가상 비교기업 | 같은 단계 pre-money (USD) | 가상 출처 |
| --- | ---: | --- |
| 비교 A | 100,000,000 | https://example.invalid/peer-a/round |
| 비교 B | 120,000,000 | https://example.invalid/peer-b/round |
| 비교 C | 140,000,000 | https://example.invalid/peer-c/round |

중앙값 120,000,000 USD → 대상 A 144,000,000 ÷ 중앙값 = 1.2배 → QN **3점, missing=False**.

대상 B는 기업가치가 null → QN **3점, missing=True**. 점수는 같아도 B만 결측 비중에 QN 몫 0.10 × 1/2 = 0.05가 들어간다. 중앙값을 확보하지 못한 경우도 결측 3점 처리다.

QN 추가 사전 합의는 요구하지 않는다. 실제 수집·검증·채점 구현은 담당자가 진행한다.
