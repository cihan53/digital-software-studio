"""Araçsız rol, düzenleyeceği mevcut çıktı dosyasını görmeli (issue #227)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import studio_engine as E


class MevcutCikti(unittest.TestCase):
    def setUp(self):
        self.k = Path(tempfile.mkdtemp()).resolve()
        (self.k / "workspace/src/web").mkdir(parents=True)
        (self.k / "workspace/src/web/nuxt.config.ts").write_text("export default defineNuxtConfig({ css: ['~/assets/css/main.css'] })")
        (self.k / "workspace/src/web/yeni.ts").parent.mkdir(exist_ok=True)

    def test_var_olan_cikti_girdiye_eklenir(self):
        m = E.gorev_girdileri("Çözüm", self.k, ciktilar=["workspace/src/web/nuxt.config.ts", "workspace/src/web/yeni.ts", "workspace/src/web/"])
        self.assertIn("MEVCUT ÇIKTI DOSYASI: workspace/src/web/nuxt.config.ts", m)
        self.assertIn("css: ['~/assets/css/main.css']", m)                  # mevcut içerik modele gösterilir
        self.assertIn("SIFIRDAN YAZMA", m)
        self.assertNotIn("yeni.ts", m)                                       # henüz olmayan dosya ve dizin eklenmez

    def test_ciktisiz_gorev_degismez(self):
        self.assertEqual(E.gorev_girdileri("Girdi yok", self.k, ciktilar=["workspace/src/web/"]), "")
        self.assertEqual(E.gorev_girdileri("Girdi yok", self.k), "")

    def test_workspace_disi_ve_buyuk_dosya(self):
        (self.k / "disari.ts").write_text("x")
        self.assertEqual(E.mevcut_cikti_dosyalari(["disari.ts", "../etc/passwd"], self.k), [])
        (self.k / "workspace/src/web/dev.ts").write_text("a" * 50_000)
        m = E.gorev_girdileri("x", self.k, ciktilar=["workspace/src/web/dev.ts"])
        self.assertIn("ATLANDI (büyük dosya", m)
        self.assertNotIn("a" * 100, m)

    def test_aciklamadaki_girdi_ile_cakismaz(self):
        m = E.gorev_girdileri("Girdi: workspace/src/web/nuxt.config.ts", self.k, ciktilar=["workspace/src/web/nuxt.config.ts"])
        self.assertEqual(m.count("nuxt.config.ts =====\n"), 1)               # aynı dosya iki kez verilmez
        self.assertIn("GÖREV GİRDİSİ: workspace/src/web/nuxt.config.ts", m)


if __name__ == "__main__":
    unittest.main()
