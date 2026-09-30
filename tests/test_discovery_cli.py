"""실행 진입점의 파일 검증·모드 분리·안전한 저장을 확인한다."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collect_candidates import save_collection
from discover_candidates import load_collection, main
from tests.test_agent1_discovery import collection


class DiscoveryCLITests(unittest.TestCase):
    def test_load_valid_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = save_collection(collection(), Path(directory))
            self.assertEqual(load_collection(path)["status"], "ok")

    def test_wrong_input_shapes_rejected(self):
        for data in ([], {"status": "error"}, {"status": "ok", "searches": [{}]}):
            with self.subTest(data=data), tempfile.TemporaryDirectory() as directory:
                path = save_collection({"data": data}, Path(directory))
                # 임시 테스트 JSON도 공통 저장 도구를 사용한다.
                with (
                    patch("discover_candidates.json.load", return_value=data),
                    self.assertRaises(ValueError),
                ):
                    load_collection(path)

    def test_distinct_artifact_prefixes(self):
        with tempfile.TemporaryDirectory() as directory:
            target = save_collection(
                {"leads": []}, Path(directory), prefix="candidate_leads"
            )
            self.assertTrue(target.name.startswith("candidate_leads_"))
            self.assertEqual(json.loads(target.read_text())["leads"], [])
            with self.assertRaises(ValueError):
                save_collection({}, Path(directory), prefix="../outside")

    def test_plan_only_does_not_search_or_extract(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch(
                "sys.argv",
                ["discover_candidates.py", "--plan-only", "--output-dir", directory],
            ),
            patch("discover_candidates.GPTStructuredGenerator"),
            patch("discover_candidates.plan_searches", return_value=[]),
            patch("discover_candidates.collect_searches") as search,
            patch("discover_candidates.extract_candidate_leads") as extract,
        ):
            main()
            search.assert_not_called()
            extract.assert_not_called()

    def test_reuse_does_not_search(self):
        with tempfile.TemporaryDirectory() as directory:
            path = save_collection(collection(), Path(directory))
            with (
                patch(
                    "sys.argv",
                    [
                        "discover_candidates.py",
                        "--input",
                        str(path),
                        "--output-dir",
                        directory,
                    ],
                ),
                patch("discover_candidates.GPTStructuredGenerator"),
                patch("discover_candidates.collect_searches") as search,
                patch("discover_candidates.plan_searches") as plan,
                patch(
                    "discover_candidates.extract_candidate_leads",
                    return_value={
                        "lead_count": 0,
                        "rejected_leads": [],
                        "status": "extracted_unverified",
                    },
                ),
            ):
                main()
                search.assert_not_called()
                plan.assert_not_called()
