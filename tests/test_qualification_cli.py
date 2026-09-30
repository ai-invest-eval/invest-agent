"""자격 검증 실행 파일의 입력 계약·기업 선택·중간 저장을 확인한다."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collect_candidates import save_collection
from qualify_candidates import load_leads, main
from tests.test_agent1_qualification import candidate


class QualificationCLITests(unittest.TestCase):
    def test_load_leads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = save_collection(
                {"status": "extracted_unverified", "leads": [candidate().model_dump()]},
                Path(directory),
                prefix="candidate_leads",
            )
            _, leads = load_leads(path)
            self.assertEqual(leads[0].name, "Alpha")

    def test_invalid_contracts_rejected(self):
        for data in (
            {"status": "ok", "leads": []},
            {"status": "extracted_unverified", "leads": [{}]},
        ):
            with tempfile.TemporaryDirectory() as directory:
                path = save_collection(data, Path(directory))
                with self.assertRaises(ValueError):
                    load_leads(path)

    def test_company_selection_and_save(self):
        with tempfile.TemporaryDirectory() as directory:
            second = candidate().model_copy(update={"name": "Beta"})
            path = save_collection(
                {
                    "status": "extracted_unverified",
                    "leads": [candidate().model_dump(), second.model_dump()],
                    "smoke_test_subset": True,
                },
                Path(directory),
                prefix="candidate_leads",
            )
            with (
                patch(
                    "sys.argv",
                    [
                        "qualify_candidates.py",
                        "--input",
                        str(path),
                        "--company",
                        "Beta",
                        "--output-dir",
                        directory,
                    ],
                ),
                patch("qualify_candidates.GPTStructuredGenerator"),
                patch("qualify_candidates.TavilySearch"),
                patch(
                    "qualify_candidates.qualify_candidate",
                    return_value={
                        "status": "unconfirmed",
                        "search_status": "ok",
                        "model_status": "ok",
                    },
                ) as qualify,
                patch("builtins.print"),
            ):
                main()
                self.assertEqual(qualify.call_args.args[2].name, "Beta")
                files = list(Path(directory).glob("qualification_*.json"))
                self.assertEqual(len(files), 1)

    def test_unknown_requested_company_fails_before_api(self):
        with tempfile.TemporaryDirectory() as directory:
            path = save_collection(
                {"status": "extracted_unverified", "leads": [candidate().model_dump()]},
                Path(directory),
            )
            with (
                patch(
                    "sys.argv",
                    [
                        "qualify_candidates.py",
                        "--input",
                        str(path),
                        "--company",
                        "missing",
                    ],
                ),
                patch("qualify_candidates.GPTStructuredGenerator") as generator,
                self.assertRaises(SystemExit),
            ):
                main()
            generator.assert_not_called()
