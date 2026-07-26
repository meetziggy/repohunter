"""Smoke + unit tests for RepoHunter's pure logic (no network, stdlib only)."""
import unittest
import repohunter as rh


class ApiSurface(unittest.TestCase):
    def test_entry_points_exist(self):
        for name in ("score", "resource_fit", "serve", "refresh", "main"):
            self.assertTrue(callable(getattr(rh, name, None)), f"{name} should be callable")


class ResourceFit(unittest.TestCase):
    SPECS = {"chip": "Apple M4 Max", "cores": 14, "ram_gb": 36, "disk_free": "300G"}

    def test_compiled_language_runs_easily(self):
        r = rh.resource_fit({"language": "Rust", "desc": "a small cli", "topics": []}, self.SPECS)
        self.assertEqual(r["verdict"], "runs easily")
        self.assertFalse(r["gpu"])

    def test_gpu_heavy_is_flagged(self):
        r = rh.resource_fit({"language": "Python", "desc": "train a 70b model on a100 cuda", "topics": []}, self.SPECS)
        self.assertEqual(r["verdict"], "heavy")
        self.assertTrue(r["gpu"])

    def test_local_ml_needs_headroom(self):
        r = rh.resource_fit({"language": "Python", "desc": "pytorch embedding inference", "topics": []}, self.SPECS)
        self.assertEqual(r["ram_need"], "medium")


class Score(unittest.TestCase):
    def setUp(self):
        rh.CFG = {"project": {"relevance_keywords": ["agent", "rag"]}}

    def test_scores_are_bounded_ints(self):
        s = rh.score({"desc": "an agent rag tool", "stars": 5000, "name": "x", "topics": [],
                      "pushed": "2026-07-01T00:00:00Z", "created": "2020-01-01T00:00:00Z",
                      "language": "Python", "license": "MIT", "contributors": 40, "latest_release": "v1"})
        for k in ("relevance", "popularity", "freshness", "health", "maturity", "overall"):
            self.assertIn(k, s)
            self.assertIsInstance(s[k], int)
            self.assertGreaterEqual(s[k], 0)
            self.assertLessEqual(s[k], 100)

    def test_relevance_rewards_keyword_match(self):
        hit = rh.score({"desc": "an agent", "stars": 10, "name": "a", "topics": [], "language": "Go"})
        miss = rh.score({"desc": "a spreadsheet", "stars": 10, "name": "b", "topics": [], "language": "Go"})
        self.assertGreater(hit["relevance"], miss["relevance"])


if __name__ == "__main__":
    unittest.main()
