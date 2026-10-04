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


class ResearchTools(unittest.TestCase):
    def test_research_module_loads_and_dataclasses_work(self):
        from dataclasses import asdict
        mod = mcp._rh()
        cite = mod.Cite(id="x", title="t", type="paper", url="u", year=None, authors=[], source="s")
        self.assertEqual(asdict(cite)["title"], "t")

    def test_limit_is_clamped(self):
        self.assertEqual(mcp._limit({"limit": "9999"}, 30), 50)
        self.assertEqual(mcp._limit({"limit": 0}, 30), 30)
        self.assertEqual(mcp._limit({"limit": "x"}, 30), 30)

    def test_cache_key_separates_source_sets(self):
        mod = mcp._rh()
        self.assertNotEqual(mod._cache_key("q", "wide", 20, "110"), mod._cache_key("q", "wide", 20, "010"))

    def test_results_marked_untrusted(self):
        out = mcp._research(lambda: {"success": True})
        self.assertIn("UNTRUSTED", out["_untrusted"])


class UnidentifiedLicense(unittest.TestCase):
    def _repo(self, spdx):
        return {"stargazers_count": 250000, "pushed_at": "2099-01-01T00:00:00Z",
                "created_at": "2015-01-01T00:00:00Z", "archived": False,
                "license": {"spdx_id": spdx} if spdx is not None else None}

    def test_noassertion_or_missing_license_is_never_go(self):
        for spdx in ("NOASSERTION", None):
            self.assertEqual(mcp.score(self._repo(spdx))["verdict"], "MAYBE", spdx)

    def test_identified_license_can_be_go(self):
        self.assertEqual(mcp.score(self._repo("MIT"))["verdict"], "GO")


if __name__ == "__main__":
    unittest.main()
