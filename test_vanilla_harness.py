"""Tests for examples/harness/vanilla_harness.py against a stub MCP server (no network)."""
import contextlib
import io
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / "examples" / "harness"))
import vanilla_harness as harness  # noqa: E402

# A stand-in MCP server: reads JSON-RPC lines and answers the tools/call per its first argument.
STUB = r'''
import json, sys
mode = sys.argv[1]
if mode == "crash":
    sys.stderr.write("stub exploded")
    sys.exit(3)
REPO = {"repo": "o/r", "verdict": mode.upper(), "scores": {"overall": 50}, "archived": False,
        "last_push": "2026-10-01", "license": None, "resource_fit": {"verdict": "runs easily"}}
for line in sys.stdin:
    msg = json.loads(line)
    mid = msg.get("id")
    if mid is None:
        continue
    if msg["method"] == "tools/list":
        out = {"tools": [{"name": "evaluate_repo"}]}
    elif msg["method"] == "tools/call" and mode == "rpcerror":
        print(json.dumps({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "nope"}}))
        continue
    elif msg["method"] == "tools/call":
        if mode == "iserror":
            out = {"content": [{"type": "text", "text": "error: rate limited"}], "isError": True}
        elif mode == "nonjson":
            out = {"content": [{"type": "text", "text": "<html>"}]}
        elif mode == "weird":
            out = {"content": [{"type": "text", "text": json.dumps(dict(REPO, verdict="???"))}]}
        else:
            out = {"content": [{"type": "text", "text": json.dumps(REPO)}]}
    else:
        out = {}
    print(json.dumps({"jsonrpc": "2.0", "id": mid, "result": out}))
    sys.stdout.flush()
'''


class HarnessGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        stub = Path(cls.tmp.name) / "stub_server.py"
        stub.write_text(STUB)
        cls.stub_cmd = "%s %s" % (shlex.quote(sys.executable), shlex.quote(str(stub)))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_harness(self, server, *args):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(harness, "SERVER", server), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = harness.main(["o/r", *args])
        return code, out.getvalue(), err.getvalue()

    def stub(self, mode, *args):
        return self.run_harness("%s %s" % (self.stub_cmd, mode), *args)

    def test_go_is_allowed(self):
        code, out, _ = self.stub("go")
        self.assertEqual(code, 0)
        self.assertIn("ALLOWED", out)
        self.assertIn("evaluate_repo", out)

    def test_skip_is_blocked_by_default(self):
        code, out, _ = self.stub("skip")
        self.assertEqual(code, 2)
        self.assertIn("BLOCKED", out)

    def test_maybe_passes_by_default_but_blocks_with_flag(self):
        self.assertEqual(self.stub("maybe")[0], 0)
        self.assertEqual(self.stub("maybe", "--block-on", "MAYBE")[0], 2)

    def test_missing_license_is_reported_but_not_gated(self):
        code, out, _ = self.stub("go")
        self.assertEqual(code, 0)
        self.assertIn("none found", out)

    def test_jsonrpc_error_is_shown(self):
        code, _, err = self.stub("rpcerror")
        self.assertEqual(code, 1)
        self.assertIn("nope", err)

    def test_tool_error_text_is_shown(self):
        code, _, err = self.stub("iserror")
        self.assertEqual(code, 1)
        self.assertIn("rate limited", err)

    def test_non_json_reply_exits_1(self):
        code, _, err = self.stub("nonjson")
        self.assertEqual(code, 1)
        self.assertIn("not JSON", err)

    def test_unknown_verdict_exits_1(self):
        self.assertEqual(self.stub("weird")[0], 1)

    def test_server_crash_shows_stderr(self):
        code, _, err = self.stub("crash")
        self.assertEqual(code, 1)
        self.assertIn("stub exploded", err)

    def test_missing_server_binary_exits_1(self):
        code, _, err = self.run_harness("no-such-binary-for-harness-test")
        self.assertEqual(code, 1)
        self.assertIn("cannot start server", err)

    def test_timeout_exits_1(self):
        def timeout(*a, **k):
            raise harness.subprocess.TimeoutExpired("x", 300)
        with patch.object(harness.subprocess, "run", side_effect=timeout):
            code, _, err = self.run_harness("anything")
        self.assertEqual(code, 1)
        self.assertIn("300s", err)


if __name__ == "__main__":
    unittest.main()
