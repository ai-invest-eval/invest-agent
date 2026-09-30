"""실제 과금 없이 구조화 호출 계약과 오류 경계를 확인한다."""

import unittest
from unittest.mock import Mock, patch

import httpx
from openai import APITimeoutError, AuthenticationError, BadRequestError, RateLimitError
from pydantic import BaseModel

from src.tools.structured_llm import GPTStructuredGenerator, StructuredLLMError


class Reply(BaseModel):
    value: str


class StructuredLLMTests(unittest.TestCase):
    def setUp(self):
        # 생성자를 건너뛰어 테스트에서 키나 네트워크가 필요하지 않게 한다.
        self.generator = GPTStructuredGenerator.__new__(GPTStructuredGenerator)
        self.generator._model = Mock()
        sleeper = patch("src.tools.structured_llm.sleep")
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_schema_and_strict_mode(self):
        expected = Reply(value="후보")
        self.generator._model.with_structured_output.return_value.invoke.return_value = expected
        self.assertEqual(
            self.generator.generate(Reply, "규칙", {"내용": "자료"}), expected
        )
        self.generator._model.with_structured_output.assert_called_once_with(
            Reply, method="json_schema", strict=True
        )

    def test_external_error_is_not_exposed(self):
        self.generator._model.with_structured_output.side_effect = RuntimeError(
            "secret-key"
        )
        with self.assertRaises(StructuredLLMError) as caught:
            self.generator.generate(Reply, "규칙", {})
        self.assertNotIn("secret-key", str(caught.exception))

    def test_non_model_response_rejected(self):
        self.generator._model.with_structured_output.return_value.invoke.return_value = None
        with self.assertRaises(StructuredLLMError):
            self.generator.generate(Reply, "규칙", {})

    def test_api_status_and_known_codes_without_private_body(self):
        for error_type, status, code, expected in (
            (AuthenticationError, 401, "invalid_api_key", "인증"),
            (RateLimitError, 429, "insufficient_quota", "잔액"),
            (BadRequestError, 400, "invalid_json_schema", "스키마"),
        ):
            with self.subTest(status=status):
                response = httpx.Response(
                    status,
                    request=httpx.Request(
                        "POST", "https://api.openai.com/v1/chat/completions"
                    ),
                )
                error = error_type(
                    "secret-key private search text",
                    response=response,
                    body={"code": code, "message": "private"},
                )
                self.generator._model.with_structured_output.side_effect = error
                with self.assertRaises(StructuredLLMError) as caught:
                    self.generator.generate(Reply, "규칙", {})
                message = str(caught.exception)
                self.assertIn(f"HTTP={status}", message)
                self.assertIn(f"code={code}", message)
                self.assertIn("출력계약=Reply", message)
                self.assertIn(expected, message)
                self.assertNotIn("secret-key", message)
                self.assertNotIn("private", message)

    def test_timeout_is_distinguished(self):
        self.generator._model.with_structured_output.side_effect = APITimeoutError(
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        )
        with self.assertRaisesRegex(StructuredLLMError, "APITimeoutError.*시간 초과"):
            self.generator.generate(Reply, "규칙", {})
        self.assertEqual(self.generator._model.with_structured_output.call_count, 2)

    def test_transient_timeout_recovers_once(self):
        error = APITimeoutError(request=httpx.Request("POST", "https://api.openai.com"))
        expected = Reply(value="후보")
        invoke = self.generator._model.with_structured_output.return_value.invoke
        invoke.side_effect = [error, expected]
        self.assertEqual(self.generator.generate(Reply, "규칙", {}), expected)
        self.assertEqual(invoke.call_count, 2)
        self.sleep.assert_called_once_with(1.0)

    def test_auth_and_quota_are_not_retried(self):
        for cls, status, code in (
            (AuthenticationError, 401, "invalid_api_key"),
            (RateLimitError, 429, "insufficient_quota"),
        ):
            with self.subTest(code=code):
                self.generator._model.reset_mock()
                response = httpx.Response(
                    status, request=httpx.Request("POST", "https://api.openai.com")
                )
                self.generator._model.with_structured_output.side_effect = cls(
                    "private", response=response, body={"code": code}
                )
                with self.assertRaises(StructuredLLMError):
                    self.generator.generate(Reply, "규칙", {})
                self.assertEqual(
                    self.generator._model.with_structured_output.call_count, 1
                )
        self.sleep.assert_not_called()

    def test_retry_after_is_respected_and_long_wait_is_not_retried(self):
        for delay in ("2", "60"):
            with self.subTest(delay=delay):
                self.generator._model.reset_mock()
                self.sleep.reset_mock()
                response = httpx.Response(
                    429,
                    headers={"retry-after": delay},
                    request=httpx.Request("POST", "https://api.openai.com"),
                )
                error = RateLimitError(
                    "private", response=response, body={"code": "rate_limit_exceeded"}
                )
                self.generator._model.with_structured_output.side_effect = error
                with self.assertRaises(StructuredLLMError):
                    self.generator.generate(Reply, "규칙", {})
                self.assertEqual(
                    self.generator._model.with_structured_output.call_count,
                    2 if delay == "2" else 1,
                )
                if delay == "2":
                    self.sleep.assert_called_once_with(2.0)
                else:
                    self.sleep.assert_not_called()

    def test_unknown_external_code_is_not_exposed(self):
        response = httpx.Response(
            400, request=httpx.Request("POST", "https://api.openai.com")
        )
        self.generator._model.with_structured_output.side_effect = BadRequestError(
            "private", response=response, body={"code": "secret-key"}
        )
        with self.assertRaises(StructuredLLMError) as caught:
            self.generator.generate(Reply, "규칙", {})
        self.assertNotIn("secret-key", str(caught.exception))

    def test_empty_key_rejected(self):
        with self.assertRaises(ValueError):
            GPTStructuredGenerator(" ")
