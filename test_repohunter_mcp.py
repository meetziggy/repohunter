"""Contract tests for RepoHunter's agent-facing evidence output (no network)."""
import unittest
from unittest.mock import patch

import repohunter_mcp as mcp


REPO = {
    "full_name": "example/project",
    "html_url": "https://github.com/example/project",
    "description": "A useful public project",
    "name": "project",
    "language": "Python",
    "topics": ["example"],
    "license": {"spdx_id": "MIT"},
    "stargazers_count": 42,
    "pushed_at": "2026-08-01T00:00:00Z",
    "created_at": "2024-01-01T00:00:00Z",
    "archived": False,
    "fork": False,
}


class EvidenceContract(unittest.TestCase):
    def assert_evidence(self, evidence, endpoint):
        self.assertEqual(evidence["schema"], "repohunter.evidence.v1")
        self.assertRegex(evidence["observed_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(evidence["sources"][0]["endpoint"], "https://api.github.com" + endpoint)
        self.assertEqual(evidence["review"]["decision_owner"], "user")
        self.assertTrue(any("bias" in limit for limit in evidence["limits"]))
        self.assertTrue(any("not checked" in limit for limit in evidence["limits"]))

    @patch.object(mcp, "gh", return_value=REPO)
    def test_evaluate_repo_includes_reviewable_provenance(self, _gh):
        out = mcp.skill_evaluate_repo({"repo": "example/project", "project": "Python service"})
        self.assert_evidence(out["evidence"], "/repos/example/project")
        self.assertEqual(out["url"], REPO["html_url"])

    @patch.object(mcp, "gh", return_value={"items": [REPO]})
    def test_find_repos_records_search_route_and_limits(self, _gh):
        out = mcp.skill_find_repos({"query": "accessible documentation"})
        self.assert_evidence(out["evidence"],
                             "/search/repositories?sort=stars&per_page=8&q=accessible%20documentation")
        self.assertEqual(out["candidates"][0]["repo"], "example/project")

    @patch.object(mcp, "gh", return_value=[REPO])
    def test_public_work_summary_rejects_person_judgment(self, _gh):
        out = mcp.skill_portfolio_scan({"user": "example"})
        self.assert_evidence(out["evidence"],
                             "/users/example/repos?per_page=100&sort=updated&type=owner")
        self.assertIn("not an assessment of a person", out["_note"].lower())
        self.assertIn("does not imply", out["_note"].lower())


if __name__ == "__main__":
    unittest.main()
