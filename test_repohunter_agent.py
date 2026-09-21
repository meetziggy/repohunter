"""Contract tests for RepoHunter's authenticated SpookyJuice peer adapter."""

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import repohunter_agent as agent


TOKEN = "test-only-token-that-is-longer-than-32-chars"


class AgentContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            agent.make_handler(TOKEN, "https://repohunter.test/a2a"),
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, *, token=TOKEN, payload=None):
        headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, headers=headers)
        with urllib.request.urlopen(request) as response:
            self.assertNotIn("Python", response.headers.get("Server", ""))
            return response.status, json.load(response)

    def test_discovery_requires_auth_and_advertises_read_only_custom_binding(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/.well-known/agent-card.json", token=None)
        self.assertEqual(caught.exception.code, 401)

        status, card = self.request("/a2a/.well-known/agent-card.json")
        self.assertEqual(status, 200)
        self.assertEqual(card["protocolVersion"], "0.1-spooky")
        self.assertEqual({skill["trust"] for skill in card["skills"]}, {"OBSERVE"})
        self.assertTrue(any("not Linux Foundation A2A 1.0" in item for item in card["limits"]))

    def test_health_supports_head_without_runtime_disclosure(self):
        request = urllib.request.Request(self.base + "/health", method="HEAD")
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 200)
            self.assertNotIn("Python", response.headers.get("Server", ""))

    @patch("repohunter_agent.SKILLS")
    def test_executes_allowlisted_skill_without_exposing_token(self, skills):
        skills.get.return_value = (lambda value: {"echo": value}, "test", {})
        status, body = self.request(
            "/a2a/tasks",
            payload={"id": "task-1", "skill": "evaluate_repo", "input": {"repo": "owner/name"}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "completed")
        self.assertEqual(body["granted_trust"], "OBSERVE")
        self.assertNotIn(TOKEN, json.dumps(body))

    @patch("repohunter_agent.time.time", return_value=1_800_000_000)
    @patch("repohunter_agent.SKILLS")
    def test_refreshes_evidence_clock_for_persistent_runtime(self, skills, _time):
        skills.get.return_value = (
            lambda _value: {"clock": agent.repohunter_mcp.NOW},
            "test",
            {},
        )
        _status, body = self.request(
            "/tasks",
            payload={"id": "task-clock", "skill": "evaluate_repo", "input": {}},
        )
        self.assertEqual(body["result"]["clock"], 1_800_000_000)

    def test_rejects_unknown_skill_and_bad_input(self):
        with self.assertRaises(urllib.error.HTTPError) as unknown:
            self.request("/tasks", payload={"skill": "shell.exec", "input": {}})
        self.assertEqual(unknown.exception.code, 404)

        with self.assertRaises(urllib.error.HTTPError) as bad_input:
            self.request("/tasks", payload={"skill": "evaluate_repo", "input": []})
        self.assertEqual(bad_input.exception.code, 400)

    def test_rejects_oversized_body_before_reading_it(self):
        request = urllib.request.Request(
            self.base + "/tasks",
            data=b"{}",
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Content-Type": "application/json",
                "Content-Length": str(agent.MAX_BODY_BYTES + 1),
            },
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 413)


class Configuration(unittest.TestCase):
    def test_refuses_to_start_with_short_token(self):
        with patch.dict("os.environ", {"REPOHUNTER_AGENT_TOKEN": "short"}, clear=True):
            self.assertEqual(agent.main([]), 2)


if __name__ == "__main__":
    unittest.main()
