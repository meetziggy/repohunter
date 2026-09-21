#!/usr/bin/env python3
"""Authenticated HTTP peer adapter for RepoHunter's read-only evidence skills.

This implements SpookyJuice's current ``0.1-spooky`` custom A2A binding. It does
not claim conformance with the Linux Foundation A2A 1.0 wire protocol.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import repohunter_mcp


SKILLS = repohunter_mcp.SKILLS


MAX_BODY_BYTES = 64 * 1024
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def agent_card(base_url: str) -> dict[str, Any]:
    """Return the authenticated capability card used by the SpookyJuice hub."""
    return {
        "protocolVersion": "0.1-spooky",
        "name": "repohunter",
        "description": (
            "Read-only open-source adoption evidence: repository evaluation, "
            "candidate discovery, and factual public-work summaries."
        ),
        "url": base_url.rstrip("/"),
        "version": "0.1.0",
        "provider": {"organization": "RepoHunter", "url": "https://repohunter.dev"},
        "capabilities": {"streaming": False, "pushNotifications": False},
        "auth": {"schemes": ["bearer"]},
        "limits": [
            "Read-only public repository evidence; no repository or Home Base mutations.",
            "Custom SpookyJuice binding; not Linux Foundation A2A 1.0 conformance.",
        ],
        "skills": [
            {
                "id": name,
                "name": name.replace("_", " ").title(),
                "trust": "OBSERVE",
                "description": description,
                "inputSchema": schema,
            }
            for name, (_handler, description, schema) in SKILLS.items()
        ],
    }


def make_handler(token: str, base_url: str) -> type[BaseHTTPRequestHandler]:
    """Create a request handler closed over a dedicated peer bearer token."""
    expected = f"Bearer {token}".encode()

    class RepoHunterAgentHandler(BaseHTTPRequestHandler):
        server_version = "RepoHunter-Agent/0.1"

        def version_string(self) -> str:
            """Avoid disclosing the host Python version in response headers."""
            return self.server_version

        def log_message(self, message: str, *args: object) -> None:
            sys.stderr.write("repohunter-agent: " + (message % args) + "\n")

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            supplied = self.headers.get("Authorization", "").encode()
            return hmac.compare_digest(supplied, expected)

        def _require_auth(self) -> bool:
            if self._authorized():
                return True
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("WWW-Authenticate", 'Bearer realm="repohunter"')
            self.send_header("Cache-Control", "no-store")
            body = b'{"status":"rejected","error":"unauthorized"}'
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return False

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if self.path == "/health":
                self._json(200, {"ok": True, "service": "repohunter-agent"})
                return
            if self.path not in (
                "/.well-known/agent-card.json",
                "/a2a/.well-known/agent-card.json",
            ):
                self._json(404, {"status": "rejected", "error": "not found"})
                return
            if self._require_auth():
                self._json(200, agent_card(base_url))

        def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if self.path != "/health":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if self.path not in ("/tasks", "/a2a/tasks"):
                self._json(404, {"status": "rejected", "error": "not found"})
                return
            if not self._require_auth():
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json(400, {"status": "rejected", "error": "invalid content length"})
                return
            if length <= 0 or length > MAX_BODY_BYTES:
                self._json(413, {"status": "rejected", "error": "request body size rejected"})
                return

            try:
                body = json.loads(self.rfile.read(length))
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._json(400, {"status": "rejected", "error": "invalid JSON"})
                return
            if not isinstance(body, dict):
                self._json(400, {"status": "rejected", "error": "request must be an object"})
                return

            task_id = body.get("id") if isinstance(body.get("id"), str) else "rh-task"
            skill_id = body.get("skill") if isinstance(body.get("skill"), str) else ""
            skill = SKILLS.get(skill_id)
            if skill is None:
                self._json(
                    404,
                    {"id": task_id, "status": "rejected", "error": f"unknown skill '{skill_id}'"},
                )
                return
            skill_input = body.get("input", {})
            if not isinstance(skill_input, dict):
                self._json(400, {"id": task_id, "status": "rejected", "error": "input must be an object"})
                return

            try:
                # The MCP process was originally short-lived and captured its clock at
                # import. This peer is persistent, so refresh the observation clock for
                # every task rather than publishing its process-start time forever.
                repohunter_mcp.NOW = int(time.time())
                result = skill[0](skill_input)
            except Exception:
                self._json(502, {"id": task_id, "status": "rejected", "error": "evidence provider failed"})
                return
            self._json(
                200,
                {
                    "id": task_id,
                    "skill": skill_id,
                    "status": "completed",
                    "granted_trust": "OBSERVE",
                    "result": result,
                },
            )

    return RepoHunterAgentHandler


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RepoHunter as an authenticated SpookyJuice peer")
    parser.add_argument("--host", default=os.environ.get("REPOHUNTER_AGENT_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("REPOHUNTER_AGENT_PORT", DEFAULT_PORT)))
    parser.add_argument(
        "--base-url",
        default=os.environ.get("REPOHUNTER_AGENT_URL", f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    token = os.environ.get("REPOHUNTER_AGENT_TOKEN", "")
    if len(token) < 32:
        print("REPOHUNTER_AGENT_TOKEN must contain at least 32 characters", file=sys.stderr)
        return 2
    server = ThreadingHTTPServer((args.host, args.port), make_handler(token, args.base_url))
    print(f"RepoHunter agent listening on http://{args.host}:{args.port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
