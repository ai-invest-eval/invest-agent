"""GPT-4o-mini 구조화 출력 경계. 클라이언트·모델 호출은 실행 시 생성한다."""

import json
import sys
from time import sleep
from typing import Any, Protocol, TypeVar

from openai import APIConnectionError, APIStatusError
from pydantic import BaseModel

from src.config import LLM_MODEL, LLM_TEMPERATURE

Model = TypeVar("Model", bound=BaseModel)


class StructuredGenerator(Protocol):
    """실제 API와 테스트용 가짜 생성기가 공유하는 호출 계약."""

    def generate(
        self, schema: type[Model], system: str, payload: dict[str, Any]
    ) -> Model: ...


class StructuredLLMError(RuntimeError):
    """인증 정보나 외부 응답 본문을 포함하지 않는 모델 호출 오류."""


def safe_error_details(exc: Exception, schema: type[BaseModel]) -> str:
    """오류 원문 대신 종류·상태 코드·허용된 오류 코드만 표시한다."""
    kind = type(exc).__name__
    status = getattr(exc, "status_code", None)
    hints = {
        "APITimeoutError": "요청 시간 초과",
        "APIConnectionError": "연결 실패",
        "AuthenticationError": "인증 실패",
        "PermissionDeniedError": "접근 권한 없음",
        "RateLimitError": "요청 속도 또는 사용 한도 초과",
        "BadRequestError": "요청 형식·입력 크기·출력 스키마 확인 필요",
        "NotFoundError": "모델 또는 요청 리소스 확인 필요",
        "InternalServerError": "API 서버 오류",
        "LengthFinishReasonError": "출력 길이 한도 도달",
        "ContentFilterFinishReasonError": "콘텐츠 필터로 응답 중단",
        "ValidationError": "응답 스키마 검증 실패",
        "OutputParserException": "구조화 응답 해석 실패",
    }
    # body/message/request에는 키나 본문이 들어갈 수 있어 읽거나 출력하지 않는다.
    # error.code도 외부 문자열이므로 알려진 값만 표시한다.
    codes = {
        "insufficient_quota": "잔액 또는 사용 한도 확인 필요",
        "credit_balance_exhausted": "선불 크레딧 소진",
        "rate_limit_exceeded": "요청 속도 제한",
        "slow_down": "요청 증가 속도 제한",
        "server_is_overloaded": "모델 서버 과부하",
        "invalid_api_key": "API 키 인증 실패",
        "invalid_json_schema": "구조화 출력 스키마 오류",
        "context_length_exceeded": "입력 컨텍스트 한도 초과",
        "model_not_found": "모델 접근 가능 여부 확인 필요",
    }
    code = getattr(exc, "code", None)
    reason = (
        codes.get(code, hints.get(kind, "모델 호출 또는 응답 처리 실패"))
        if isinstance(code, str)
        else hints.get(kind, "모델 호출 또는 응답 처리 실패")
    )
    parts = [kind, f"출력계약={schema.__name__}"]
    if isinstance(status, int) and not isinstance(status, bool):
        parts.append(f"HTTP={status}")
    if isinstance(code, str) and code in codes:
        parts.append(f"code={code}")
    return f"구조화 모델 호출 실패 [{', '.join(parts)}]: {reason}"


def retry_delay(exc: Exception) -> float | None:
    """일시 장애만 한 번 재시도한다. 긴 서버 대기 요구는 빠른 재시도 대신 중단한다."""
    if getattr(exc, "code", None) in ("insufficient_quota", "credit_balance_exhausted"):
        return None
    transient = isinstance(exc, APIConnectionError) or (
        isinstance(exc, APIStatusError)
        and (exc.status_code in (408, 409, 429) or exc.status_code >= 500)
    )
    if not transient:
        return None
    headers = getattr(getattr(exc, "response", None), "headers", {})
    delay = headers.get("retry-after")
    if delay is None:
        milliseconds = headers.get("retry-after-ms")
        if milliseconds is None:
            return 1.0
        try:
            seconds = float(milliseconds) / 1000
        except (ValueError, TypeError):
            return None
    else:
        try:
            seconds = float(delay)
        except (ValueError, TypeError):
            # HTTP 날짜 형식은 짧은 대기임을 확정할 수 없으므로 재시도하지 않는다.
            return None
    return max(1.0, seconds) if 0 <= seconds <= 5 else None


class GPTStructuredGenerator:
    """프로젝트 모델 설정을 사용해 Pydantic 계약에 맞는 결과를 받는다."""

    def __init__(self, api_key: str, *, timeout: int = 60) -> None:
        if not api_key.strip():
            raise ValueError("OPENAI_API_KEY를 설정하세요.")
        # import만으로 클라이언트를 만들지 않는다. 키를 주입받은 실행 시점에
        # 생성해야 다른 담당자가 API 키 없이 모듈을 읽거나 테스트할 수 있다.
        from langchain_openai import ChatOpenAI

        self._model = ChatOpenAI(
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            api_key=api_key.strip(),
            timeout=timeout,
            # SDK 자동 재시도는 끄고 아래에서 일시 장애만 최대 1회 재시도한다.
            max_retries=0,
        )

    def generate(
        self, schema: type[Model], system: str, payload: dict[str, Any]
    ) -> Model:
        # JSON 문자열을 자유롭게 생성하게 두지 않고 스키마를 API에 전달한다.
        # 필드 구조와 별개인 업무 규칙(검색 예산, 근거 일치 등)은 호출부가 검사한다.
        for attempt in range(2):
            try:
                result = self._model.with_structured_output(
                    schema, method="json_schema", strict=True
                ).invoke(
                    [
                        ("system", system),
                        # 검색 본문은 지시문이 아닌 입력 데이터로 분리한다.
                        ("human", json.dumps(payload, ensure_ascii=False)),
                    ]
                )
                break
            except Exception as exc:  # noqa: BLE001 -- 안전한 진단 정보만 반환
                delay = retry_delay(exc) if attempt == 0 else None
                if delay is None:
                    raise StructuredLLMError(safe_error_details(exc, schema)) from None
                print(
                    f"[llm] {schema.__name__}: 일시 장애, {delay:g}초 후 재시도 1/1",
                    file=sys.stderr,
                    flush=True,
                )
                sleep(delay)
        if not isinstance(result, schema):
            raise StructuredLLMError("모델이 유효한 구조화 결과를 반환하지 않았습니다.")
        return result
