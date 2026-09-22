from pathlib import Path
import unittest


SITE_DIR = Path(__file__).parent / "site"


class HomepagePositioning(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.homepage = (SITE_DIR / "index.html").read_text(encoding="utf-8")

    def test_explains_general_assistant_comparison_without_unmeasured_claims(self) -> None:
        self.assertIn("Why use RepoHunter instead of ChatGPT or Claude Code?", self.homepage)
        self.assertIn("We do not yet claim RepoHunter is cheaper or faster.", self.homepage)
        self.assertIn("provider-reported tokens", self.homepage)
        self.assertIn("the measured benefit is still an open question", self.homepage)

    def test_preserves_limits_and_maintainer_respect(self) -> None:
        self.assertIn(
            "not a security audit, a guarantee, or a verdict on a maintainer",
            self.homepage,
        )
        self.assertIn("Missing or stale evidence should remain visible", self.homepage)


if __name__ == "__main__":
    unittest.main()
