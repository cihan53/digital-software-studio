"""Yeniden üretilebilir test çıktı dizinleri hijyen alarmı değil, otomatik temizliktir (issue #239)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import kalite_kapilari as K


class HijyenTestCiktisi(unittest.TestCase):
    def test_playwright_report_temizlenir_diger_artefakt_bulgu_olur(self):
        d = Path(tempfile.mkdtemp()).resolve()
        for rel in ("workspace/src/web/playwright-report/index.html", "workspace/src/web/test-results/a.txt", "workspace/src/web/app/x.vue"):
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text("x")
        (d / "workspace/package.json").write_text("{}")          # yabancı artefakt: silinmez, bulgu
        eski = (K.ROOT, K.WORKSPACE)
        try:
            K.ROOT, K.WORKSPACE = d, d / "workspace"
            temizlenen, bulgular = K.calisma_alani_hijyeni(["workspace/src/web/playwright-report/index.html", "workspace/src/web/test-results/a.txt"])
            self.assertIn("workspace/src/web/playwright-report", temizlenen)
            self.assertIn("workspace/src/web/test-results", temizlenen)
            self.assertFalse((d / "workspace/src/web/playwright-report").exists())
            self.assertTrue((d / "workspace/src/web/app/x.vue").exists())           # kaynak dosyalara dokunulmaz
            self.assertTrue(any("package.json" in b for b in bulgular))               # diğer sızıntılar hâlâ bulgu
            self.assertFalse(any("playwright-report" in b or "test-results" in b for b in bulgular))
        finally:
            K.ROOT, K.WORKSPACE = eski

    def test_uat_betigi_port_kapaliysa_acik_mesaj(self):
        d = Path(tempfile.mkdtemp())
        (d / "workspace").mkdir()
        (d / "workspace/studio.config.json").write_text('{"live": {"ports": [1]}}')
        node = shutil.which("node")
        if not node:
            self.skipTest("node yok")
        r = subprocess.run([node, str(ROOT / "scripts/uat_live_audit.mjs")], env={**os.environ, "STUDIO_KOK": str(d)}, capture_output=True, text=True, timeout=60, cwd=ROOT)
        self.assertEqual(r.returncode, 1)
        self.assertIn("bağlanılamadı", r.stdout)
        self.assertNotIn("ENOTFOUND", r.stdout)


if __name__ == "__main__":
    unittest.main()
