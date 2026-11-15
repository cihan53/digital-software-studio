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

    def test_web_panel_self_healing_ve_restart_komutlari(self):
        """Issue #343: koşucu aktifken panel başlatma, self-healing ve restart/kill komutları."""
        s = (ROOT / "basla.sh").read_text(encoding="utf-8")
        self.assertIn("web_panel_saglikli_mi()", s)
        self.assertIn("web_panel_durdur()", s)
        self.assertIn("--web-restart", s)
        self.assertIn("--web-kill", s)
        self.assertIn("--restart)", s)
        # calisiyor_mu bloğu içinde de web_panel_baslat çağrılmalı
        calisiyor_idx = s.index("if calisiyor_mu; then")
        exec_ctl_idx = s.index("exec $PY studio_ctl.py", calisiyor_idx)
        panel_in_calisiyor = s.index("web_panel_baslat", calisiyor_idx)
        self.assertLess(panel_in_calisiyor, exec_ctl_idx)


if __name__ == "__main__":
    unittest.main()
