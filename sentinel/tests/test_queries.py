from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class SentinelQueryContractTests(unittest.TestCase):
    def query(self, name: str) -> str:
        return (ROOT / "queries" / name).read_text(encoding="utf-8")

    def fixture(self, name: str) -> list[dict[str, object]]:
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def test_risky_role_fixture_matches_declared_operations(self) -> None:
        query = self.query("risky-role-or-nsg-change.kql").upper()
        records = self.fixture("risky-role-write.json")
        matched = [
            row
            for row in records
            if str(row["ActivityStatusValue"]).upper() == "SUCCESS"
            and str(row["OperationNameValue"]).upper() in query
        ]
        self.assertEqual(1, len(matched))
        self.assertIn("OWNER", str(matched[0]["Properties_d"]).upper())

    def test_diagnostic_delete_fixture_matches_exact_operation(self) -> None:
        query = self.query("diagnostic-setting-deletion.kql").upper()
        records = self.fixture("diagnostic-delete.json")
        matched = [
            row
            for row in records
            if str(row["ActivityStatusValue"]).upper() == "SUCCESS"
            and str(row["OperationNameValue"]).upper() in query
        ]
        self.assertEqual(1, len(matched))

    def test_failed_run_fixture_has_a_failure_status_used_by_query(self) -> None:
        query = self.query("failed-or-stale-assurance-run.kql").upper()
        records = self.fixture("assurance-failure.json")
        self.assertTrue(any(str(row["Status"]).upper() in query for row in records))
        self.assertIn("26H", query)
        self.assertIn("AICAASSURANCE_CL", query)

    def test_three_rejections_cross_tool_escalation_threshold(self) -> None:
        query = self.query("repeated-rejected-ai-tool-escalation.kql").upper()
        records = self.fixture("rejected-tool-events.json")
        rejected = [
            row
            for row in records
            if str(row["EventName"]).lower() == "tool_authorization"
            and (
                str(row["ToolResultStatus"]).upper() == "REJECTED"
                or str(row["AuthorizationDecision"]).upper() == "DENIED"
            )
        ]
        self.assertGreaterEqual(len(rejected), 3)
        self.assertEqual(1, len({row["SessionId"] for row in rejected}))
        self.assertIn("REJECTIONCOUNT >= 3", query)
        self.assertIn("AICATOOLSECURITY_CL", query)
        self.assertIn("TOOLRESULTSTATUS", query)
        self.assertIn("AUTHORIZATIONDECISION", query)
        self.assertIn("EVALUATIONID", query)

    def test_clean_activity_does_not_match_sensitive_operations(self) -> None:
        clean_operation = "MICROSOFT.RESOURCES/SUBSCRIPTIONS/RESOURCEGROUPS/READ"
        combined = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "queries").glob("*.kql"))
        self.assertNotIn(clean_operation, combined.upper())


if __name__ == "__main__":
    unittest.main()
