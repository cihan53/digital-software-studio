"""Koşucu hemen düşse bile panel açık kalmalı: panel koşucudan önce başlatılır (issue #213)."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class BaslaPanel(unittest.TestCase):
    def test_sozdizimi(self):
        self.assertEqual(subprocess.run(["bash", "-n", str(ROOT / "basla.sh")], capture_output=True).returncode, 0)

    def test_panel_kosucudan_once_baslar(self):
        s = (ROOT / "basla.sh").read_text(encoding="utf-8")
        cagri = s.index("\nweb_panel_baslat\n")
        kosucu = s.index("nohup $PY studio_engine.py --full")
        self.assertLess(cagri, kosucu)
        self.assertIn("Panel açık kaldı", s)              # koşucu düşünce kullanıcıya panel adresi gösterilir


if __name__ == "__main__":
    unittest.main()
