"""저장된 미검증 후보의 자격을 기업별로 확인하는 개발 실행 파일.

TODO(에이전트 1): 검증 통과 후보의 단계 표기 정규화·최대 후보 수·State 연결.
미확인·제외 기업도 기록하며 이 파일에서 최종 후보 15개를 확정하지 않는다.
"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from pydantic import ValidationError

from collect_candidates import redact_secrets, save_collection
from src.agents.agent1_discovery import CandidateLead, normalize_name
from src.agents.agent1_qualification import qualify_candidate
from src.config import PROJECT_ROOT
from src.tools.structured_llm import GPTStructuredGenerator
from src.tools.web_search import TavilySearch


def load_leads(path: Path) -> tuple[dict, list[CandidateLead]]:
    """원본 검색 JSON과 후보 JSON을 혼동하거나 깨진 후보를 넘기지 않게 검사한다."""
    with path.open(encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict) or data.get("status") != "extracted_unverified":
        raise ValueError("candidate_leads JSON이 필요합니다.")
    leads = data.get("leads")
    if not isinstance(leads, list):
        raise ValueError("미검증 후보 목록 형식이 올바르지 않습니다.")  # noqa: TRY004 -- 입력 파일 계약
    try:
        candidates = [CandidateLead.model_validate(lead) for lead in leads]
    except ValidationError:
        raise ValueError(
            "후보 필드가 CandidateLead 계약과 일치하지 않습니다."
        ) from None
    return data, candidates


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description="Agent 1 기업별 자격 검증")
    parser.add_argument(
        "--input", type=Path, required=True, help="candidate_leads JSON"
    )
    parser.add_argument(
        "--company", action="append", help="검증할 기업명. 여러 번 지정 가능"
    )
    parser.add_argument("--limit", type=int, help="이번 개발 실행에서 검증할 기업 수")
    parser.add_argument("--max-results", type=int, default=4)
    parser.add_argument(
        "--timeout", type=int, default=90, help="모델 호출 제한 시간(초)"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=PROJECT_ROOT / "outputs" / "qualification"
    )
    args = parser.parse_args()
    if (
        (args.limit is not None and args.limit < 1)
        or not 1 <= args.max_results <= 20
        or args.timeout < 1
    ):
        parser.error("limit·timeout은 양수, max-results는 1~20이어야 합니다.")
    secrets = [os.getenv("OPENAI_API_KEY", ""), os.getenv("TAVILY_API_KEY", "")]
    try:
        data, leads = load_leads(args.input)
        if args.company:
            requested = {normalize_name(name) for name in args.company}
            leads = [lead for lead in leads if normalize_name(lead.name) in requested]
            if requested - {normalize_name(lead.name) for lead in leads}:
                raise ValueError("지정한 기업명이 후보 목록에 없습니다.")
        if args.limit is not None:
            leads = leads[: args.limit]
        if not leads:
            raise ValueError("검증할 미검증 후보가 없습니다.")
        generator = GPTStructuredGenerator(secrets[0], timeout=args.timeout)
        search = TavilySearch(secrets[1])
        # 날짜는 클라이언트 기준 시간대와 맞춘다. 자료 발행일/이벤트 일자는 별도다.
        as_of = datetime.now(ZoneInfo("Asia/Seoul")).date()
        counts = {"eligible": 0, "excluded": 0, "unconfirmed": 0}
        for index, lead in enumerate(leads, start=1):
            print(f"기업 {index}/{len(leads)}: {lead.name}", flush=True)
            result = qualify_candidate(
                generator,
                search,
                lead,
                as_of=as_of,
                max_results=args.max_results,
                progress=lambda text: print(text, flush=True),
            )
            result["source_leads"] = str(args.input)
            result["smoke_test_subset"] = bool(data.get("smoke_test_subset", False))
            # 기업 한 곳을 마칠 때마다 저장해 뒤 기업의 실패로 앞 결과를 잃지 않는다.
            target = save_collection(
                redact_secrets(result, secrets), args.output_dir, prefix="qualification"
            )
            counts[result["status"]] += 1
            print(
                f"판정 {result['status']} / 검색 {result['search_status']} / 모델 {result['model_status']}"
            )
            print(f"저장: {target}", flush=True)
        print(
            f"완료: 조건 확인 {counts['eligible']}, 제외 {counts['excluded']}, 미확인 {counts['unconfirmed']}"
        )
    except ValueError as exc:
        parser.exit(1, f"실행 중단: {redact_secrets(str(exc), secrets)}\n")
    except OSError:
        parser.exit(1, "파일 읽기·저장 실패. 경로와 접근 권한을 확인하세요.\n")


if __name__ == "__main__":
    main()
