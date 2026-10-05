"""Tasarım önizlemesi gibi .html hedefleri başka içerik (JSON, düz metin) ile yazılmamalı (issue #187)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import studio_engine as E


class HtmlDogrulama(unittest.TestCase):
    def test_gecerli(self):
        for t in ("<!DOCTYPE html><html><body>x</body></html>", "```html\n<html lang='en'>", "  <div class='a'>x</div>"):
            self.assertTrue(E._html_gecerli(t), t)

    def test_gecersiz(self):
        for t in ('{"soru": "x <div>", "bitti": false}', "", "Merhaba, işte önizleme.", "[1, 2]"):
            self.assertFalse(E._html_gecerli(t), t)


if __name__ == "__main__":
    unittest.main()
