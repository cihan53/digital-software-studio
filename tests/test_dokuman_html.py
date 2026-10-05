"""HTML dokümanlar yeni sekmede, korumalı başlıklarla sunulur (issue #209)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import studio_web as W


class DokumanHtml(unittest.TestCase):
    def test_html_ham_yalniz_workspace_html(self):
        d = Path(tempfile.mkdtemp())
        eski = W.ROOT
        try:
            W.ROOT = d
            (d / "workspace/docs").mkdir(parents=True)
            (d / "workspace/docs/onizleme.html").write_text("<html>x</html>")
            (d / "workspace/docs/not.md").write_text("# x")
            (d / "gizli.html").write_text("<html>gizli</html>")
            self.assertEqual(W.html_ham("workspace/docs/onizleme.html")[0], b"<html>x</html>")
            for kotu in ("workspace/docs/not.md", "gizli.html", "../etc/passwd", "workspace/docs/yok.html"):
                self.assertIsNone(W.html_ham(kotu)[0], kotu)
        finally:
            W.ROOT = eski

    def test_csp_opak_origin_ve_ag_yok(self):
        self.assertIn("sandbox", W.HTML_CSP)
        self.assertNotIn("allow-same-origin", W.HTML_CSP)           # panel origin'ine/API'sine erişim yok
        self.assertIn("connect-src 'none'", W.HTML_CSP)


if __name__ == "__main__":
    unittest.main()
