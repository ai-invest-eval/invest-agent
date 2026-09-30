"""GPT-4o-mini 구조화 출력 경계. 클라이언트·모델 호출은 실행 시 생성한다."""

import json
from typing import Any, Protocol, TypeVar

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
            # 숨은 재시도로 검색·추출 호출 예산이 늘지 않도록 자동 재시도를 끈다.
            max_retries=0,
        )

    def generate(
        self, schema: type[Model], system: str, payload: dict[str, Any]
    ) -> Model:
        # JSON 문자열을 자유롭게 생성하게 두지 않고 스키마를 API에 전달한다.
        # 필드 구조와 별개인 업무 규칙(검색 예산, 근거 일치 등)은 호출부가 검사한다.
        try:
            result = self._model.with_structured_output(
                schema, method="json_schema", strict=True
            ).invoke(
                [
                    ("system", system),
                    # 검색 본문은 지시문이 아닌 입력 데이터로 분리한다.
                    # 이 분리 자체가 프롬프트 주입을 완전히 막는 것은 아니다.
                    ("human", json.dumps(payload, ensure_ascii=False)),
                ]
            )
        except Exception:  # noqa: BLE001 -- 외부 API 경계의 인증정보·응답 노출 방지
            raise StructuredLLMError(
                "구조화 모델 호출 실패. 키·연결·사용 한도·응답 형식을 확인하세요."
            ) from None
        if not isinstance(result, schema):
            raise StructuredLLMError("모델이 유효한 구조화 결과를 반환하지 않았습니다.")
        return result
