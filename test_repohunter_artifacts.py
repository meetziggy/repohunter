#!/usr/bin/env python3
"""Unit tests for the artifact evaluator. Pure functions only — no network.

  python3 -m unittest test_repohunter_artifacts -v
"""
import unittest

import repohunter_artifacts as RA


class TestFrontmatter(unittest.TestCase):
    def test_plain_scalars(self):
        fm, body = RA.parse_frontmatter(
            "---\nname: thing\ndescription: Use when the user asks for a thing.\n---\nbody here")
        self.assertEqual(fm["name"], "thing")
        self.assertTrue(fm["description"].startswith("Use when"))
        self.assertIn("body here", body)

    def test_block_scalar_description(self):
        """A folded description must not read as its own '>-' marker."""
        text = ("---\nname: big\ndescription: >-\n  Use when the user wants a long\n"
                "  explanation spread over lines.\nmodel: opus\n---\nbody")
        fm, _ = RA.parse_frontmatter(text)
        self.assertNotIn(">", fm["description"])
        self.assertIn("spread over lines", fm["description"])
        self.assertEqual(fm["model"], "opus")

    def test_wrapped_plain_scalar(self):
        fm, _ = RA.parse_frontmatter(
            "---\ndescription: Use when the caller needs\n  a continuation line kept.\n---\nx")
        self.assertIn("continuation line kept", fm["description"])

    def test_list_forms(self):
        inline, _ = RA.parse_frontmatter("---\nallowed-tools: [Read, Bash(git:*)]\n---\nx")
        block, _ = RA.parse_frontmatter("---\nallowed-tools:\n  - Read\n  - Bash(git:*)\n---\nx")
        self.assertEqual(inline["allowed-tools"], ["Read", "Bash(git:*)"])
        self.assertEqual(block["allowed-tools"], ["Read", "Bash(git:*)"])

    def test_no_frontmatter(self):
        fm, body = RA.parse_frontmatter("# just a heading\n")
        self.assertEqual(fm, {})
        self.assertTrue(body.startswith("# just"))


class TestToolSurface(unittest.TestCase):
    def test_undeclared_is_widest(self):
        s = RA.tool_surface({})
        self.assertFalse(s["declared"])
        self.assertIn("inherits-all", s["categories"])

    def test_wildcard_is_widest(self):
        self.assertIn("inherits-all", RA.tool_surface({"allowed-tools": ["*"]})["categories"])

    def test_categories(self):
        s = RA.tool_surface({"allowed-tools": ["Read", "Bash(git:*)", "WebFetch", "mcp__linear__x"]})
        self.assertEqual(set(s["categories"]), {"read", "shell", "network", "mcp"})
        self.assertEqual(s["breadth"], 4)

    def test_comma_string(self):
        self.assertEqual(RA.tool_surface({"tools": "Read, Write"})["breadth"], 2)


class TestVerdict(unittest.TestCase):
    @staticmethod
    def rec(**kw):
        base = {"kind": "skill", "max_severity": "none", "safety": [], "capabilities": [],
                "surface": {"declared": True, "tools": ["Read"], "categories": ["read"],
                            "breadth": 1},
                "context": {"est_tokens_on_load": 500},
                "trigger": {"grade": "good", "notes": []}}
        base.update(kw)
        return base

    def test_clean_is_go(self):
        self.assertEqual(RA.verdict_for(self.rec())[0], "GO")

    def test_high_severity_quarantines(self):
        r = self.rec(max_severity="high",
                     safety=[{"severity": "high", "kind": "hidden exfiltration instruction"}])
        self.assertEqual(RA.verdict_for(r)[0], "QUARANTINE")

    def test_undeclared_surface_alone_is_not_a_reason(self):
        """Nearly every published skill omits allowed-tools; on its own it separates nothing."""
        r = self.rec(surface={"declared": False, "tools": [], "categories": ["inherits-all"],
                              "breadth": 99})
        self.assertEqual(RA.verdict_for(r)[0], "GO")

    def test_undeclared_surface_plus_capability_downgrades(self):
        r = self.rec(surface={"declared": False, "tools": [], "categories": ["inherits-all"],
                              "breadth": 99},
                     capabilities=[{"capability": "credential-read", "excerpt": "os.environ"}])
        verdict, why = RA.verdict_for(r)
        self.assertEqual(verdict, "MAYBE")
        self.assertIn("credential-read", why)

    def test_expensive_skill_downgrades(self):
        r = self.rec(context={"est_tokens_on_load": 18000})
        verdict, why = RA.verdict_for(r)
        self.assertEqual(verdict, "MAYBE")
        self.assertIn("18k tokens", why)

    def test_missing_description_skips(self):
        r = self.rec(trigger={"grade": "missing", "notes": ["no description"]})
        self.assertEqual(RA.verdict_for(r)[0], "SKIP")


class TestClassify(unittest.TestCase):
    def test_kinds(self):
        paths = [("skills/foo/SKILL.md", 10), (".claude/agents/reviewer.md", 10),
                 (".claude/commands/ship.md", 10), (".claude-plugin/plugin.json", 10),
                 (".mcp.json", 10), ("src/index.ts", 10)]
        got = {a["kind"] for a in RA.classify(paths)}
        self.assertEqual(got, {"skill", "agent", "command", "plugin", "mcp-config"})

    def test_vendor_paths_are_skipped(self):
        self.assertEqual(RA.classify([("node_modules/x/SKILL.md", 10)]), [])

    def test_bundle_size_charges_the_whole_directory(self):
        paths = [("skills/foo/SKILL.md", 100), ("skills/foo/references/big.md", 900),
                 ("skills/bar/SKILL.md", 50)]
        arts = RA.classify(paths)
        sizes = RA.bundle_sizes(paths, arts)
        self.assertEqual(sizes["skills/foo"], 1000)
        self.assertEqual(sizes["skills/bar"], 50)


class TestCapabilities(unittest.TestCase):
    def test_detects_credential_and_network(self):
        found = {c["capability"] for c in RA.capability_findings(
            "run curl https://x.example and read os.environ['API_KEY']")}
        self.assertIn("outbound-network", found)
        self.assertIn("credential-read", found)

    def test_quiet_text_finds_nothing(self):
        self.assertEqual(RA.capability_findings("Write a haiku about autumn."), [])


class TestDescribeQuality(unittest.TestCase):
    def test_missing(self):
        self.assertEqual(RA.describe_quality({}, "skill")[0], "missing")

    def test_good_trigger(self):
        grade, notes = RA.describe_quality(
            {"description": "Use when the user asks to convert a spreadsheet into a chart deck."},
            "skill")
        self.assertEqual(grade, "good")
        self.assertEqual(notes, [])

    def test_overbroad(self):
        grade, notes = RA.describe_quality(
            {"description": "Use when handling any task at all, always, for every request made."},
            "skill")
        self.assertNotEqual(grade, "good")
        self.assertTrue(any("over-broad" in n for n in notes))


if __name__ == "__main__":
    unittest.main()
