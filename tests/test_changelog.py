import unittest
from unittest.mock import patch

from backend.app.config import settings
from backend.app.routes.changelog import CHANGELOG_PATH, get_changelog
from backend.app.utils.markdown import render_markdown

class TestChangelog(unittest.TestCase):
    def test_changelog_file_exists(self):
        self.assertTrue(CHANGELOG_PATH.exists())
        self.assertTrue(CHANGELOG_PATH.is_file())
        content = CHANGELOG_PATH.read_text(encoding="utf-8")
        self.assertGreater(len(content), 0)

    def test_markdown_renderer_uses_tailwind(self):
        sample_md = "## 1.0.0\n\n- Initial release\n\n[Link](https://example.com)"
        html = render_markdown(sample_md, heading_color="primary")
        self.assertIn("text-primary", html)
        self.assertIn("list-disc", html)
        self.assertIn("text-primary", html)
        self.assertIn("hover:text-primary-hover", html)

    def test_get_changelog_needs_modal_when_version_mismatch(self):
        import asyncio

        with patch.object(type(settings), "LAST_SEEN_VERSION", property(lambda self: "0.0.1")):
            response = asyncio.run(get_changelog(current_user={"username": "admin"}))
            self.assertTrue(response.needs_modal)
            self.assertIsNotNone(response.html)
            self.assertIn("changelog-version", response.html)
            self.assertIn("text-primary", response.html)

if __name__ == "__main__":
    unittest.main()
