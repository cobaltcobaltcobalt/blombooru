import asyncio
import unittest

from backend.app.config import settings
from backend.app.routes.search import (
    _render_syntax_guide,
    _resolve_syntax_guide_lang,
    get_syntax_guide,
)

class TestSearchSyntaxGuide(unittest.TestCase):
    def setUp(self):
        self.guide_dir = settings.BASE_DIR / "docs" / "Search Syntax Guide"
        self.languages = ["en", "sv", "ru", "zh-cn"]

    def test_markdown_files_exist(self):
        self.assertTrue(self.guide_dir.exists())
        self.assertTrue(self.guide_dir.is_dir())
        for lang in self.languages:
            file_path = self.guide_dir / f"syntax_guide-{lang}.md"
            self.assertTrue(file_path.exists(), f"Missing file: {file_path}")
            self.assertTrue(file_path.is_file(), f"Not a file: {file_path}")
            content = file_path.read_text(encoding="utf-8").strip()
            self.assertGreater(len(content), 0, f"Empty file: {file_path}")

    def test_no_emojis_or_em_dashes_in_markdown(self):
        for lang in self.languages:
            file_path = self.guide_dir / f"syntax_guide-{lang}.md"
            content = file_path.read_text(encoding="utf-8")
            self.assertNotIn("\u2014", content, f"Em dash found in {file_path}")
            self.assertNotIn("\u2013", content, f"En dash found in {file_path}")
            for ch in content:
                self.assertLess(ord(ch), 0x1F000, f"Emoji character found in {file_path}: {ch}")

    def test_resolve_syntax_guide_lang(self):
        self.assertEqual(_resolve_syntax_guide_lang("en"), "en")
        self.assertEqual(_resolve_syntax_guide_lang("sv"), "sv")
        self.assertEqual(_resolve_syntax_guide_lang("ru"), "ru")
        self.assertEqual(_resolve_syntax_guide_lang("zh-cn"), "zh-cn")
        self.assertEqual(_resolve_syntax_guide_lang("zh_CN"), "zh-cn")
        self.assertEqual(_resolve_syntax_guide_lang("unknown"), "en")
        self.assertEqual(_resolve_syntax_guide_lang(""), "en")
        self.assertEqual(_resolve_syntax_guide_lang(None), "en")

    def test_render_syntax_guide_en(self):
        html = _render_syntax_guide("en")
        self.assertIsNotNone(html)
        self.assertIn("border-info", html)
        self.assertIn("text-info", html)
        self.assertIn("list-disc", html)
        self.assertIn("bg-surface", html)
        self.assertIn("Basic Tags", html)
        self.assertIn("Ranges &amp; Operators", html)
        self.assertIn("Meta Qualifiers", html)
        self.assertIn("Sorting", html)
        self.assertIn("Example Searches", html)
        self.assertIn("parent", html)
        self.assertIn("album_tree", html)

    def test_render_syntax_guide_sv(self):
        html = _render_syntax_guide("sv")
        self.assertIsNotNone(html)
        self.assertIn("border-info", html)
        self.assertIn("Grundläggande taggar", html)
        self.assertIn("Intervall och operatorer", html)
        self.assertIn("Metaqualifiers", html)
        self.assertIn("Sortering", html)
        self.assertIn("Exempelsökningar", html)

    def test_render_syntax_guide_ru(self):
        html = _render_syntax_guide("ru")
        self.assertIsNotNone(html)
        self.assertIn("border-info", html)
        self.assertIn("Базовые теги", html)
        self.assertIn("Диапазоны", html)
        self.assertIn("Сортировка", html)
        self.assertIn("Примеры поиска", html)

    def test_render_syntax_guide_zh_cn(self):
        html = _render_syntax_guide("zh-cn")
        self.assertIsNotNone(html)
        self.assertIn("border-info", html)
        self.assertIn("基础标签", html)
        self.assertIn("范围", html)
        self.assertIn("排序", html)
        self.assertIn("搜索示例", html)

    def test_api_async_endpoint(self):
        res_en = asyncio.run(get_syntax_guide("en"))
        self.assertEqual(res_en.lang, "en")
        self.assertIsNotNone(res_en.html)
        self.assertIn("border-info", res_en.html)

        res_zh = asyncio.run(get_syntax_guide("zh-cn"))
        self.assertEqual(res_zh.lang, "zh-cn")
        self.assertIsNotNone(res_zh.html)
        self.assertIn("border-info", res_zh.html)

if __name__ == "__main__":
    unittest.main()
