"""Smoke + unit tests for RepoHunter's pure logic (no network, stdlib only)."""
import unittest
import repohunter as rh


class ApiSurface(unittest.TestCase):
    def test_entry_points_exist(self):
        for name in ("score", "resource_fit", "serve", "refresh", "main"):
            self.assertTrue(callable(getattr(rh, name, None)), f"{name} should be callable")


class ResourceFit(unittest.TestCase):
    SPECS = {"chip": "Generic CPU", "cores": 8, "ram_gb": 16, "disk_free": "100G"}

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


class Cli(unittest.TestCase):
    def test_help_exits_zero(self):
        self.assertEqual(rh.main(["--help"]), 0)
        self.assertEqual(rh.main(["help"]), 0)

    def test_unknown_command_exits_two(self):
        self.assertEqual(rh.main(["definitely-not-a-command"]), 2)

    def test_missing_arg_exits_two(self):
        self.assertEqual(rh.main(["evaluate"]), 2)          # needs 1
        self.assertEqual(rh.main(["decide", "owner/repo"]), 2)  # needs 2


class YoutubeGuard(unittest.TestCase):
    """Locks the yt-dlp argument-injection fix."""
    def test_accepts_real_youtube(self):
        for u in ("https://youtube.com/watch?v=x", "https://www.youtube.com/watch?v=x",
                  "https://m.youtube.com/watch?v=x", "https://youtu.be/x"):
            self.assertTrue(rh._is_youtube_url(u), u)

    def test_rejects_injection_and_lookalikes(self):
        for u in ("--exec=rm -rf /", "https://evil.com/watch?v=x", "https://youtube.com.evil.com/x",
                  "", "file:///etc/passwd", "youtube.com/x"):  # last: no scheme
            self.assertFalse(rh._is_youtube_url(u), u)


class JsonFrom(unittest.TestCase):
    def test_parses_embedded_json(self):
        self.assertEqual(rh._json_from('noise {"a": 1} tail'), {"a": 1})

    def test_none_on_garbage(self):
        self.assertIsNone(rh._json_from("no json here"))


if __name__ == "__main__":
    unittest.main()
