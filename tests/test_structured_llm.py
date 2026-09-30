"""실제 과금 없이 구조화 호출 계약과 오류 경계를 확인한다."""

import unittest
from unittest.mock import Mock

from pydantic import BaseModel

from src.tools.structured_llm import GPTStructuredGenerator, StructuredLLMError


class Reply(BaseModel):
    value: str


class StructuredLLMTests(unittest.TestCase):
    def setUp(self):
        # 생성자를 건너뛰어 테스트에서 키나 네트워크가 필요하지 않게 한다.
        self.generator = GPTStructuredGenerator.__new__(GPTStructuredGenerator)
        self.generator._model = Mock()

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

    def test_empty_key_rejected(self):
        with self.assertRaises(ValueError):
            GPTStructuredGenerator(" ")
