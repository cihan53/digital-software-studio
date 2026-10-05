"""Deney kolları kurulumu (issue #175): yalıtım, ortak girdi, kola özgü ayar, push güvenliği."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARAC = ROOT / "scripts" / "deney_kur.py"


def git_ok() -> bool:
    return subprocess.run(["git", "rev-parse", "--git-dir"], cwd=ROOT, capture_output=True).returncode == 0


@unittest.skipUnless(git_ok(), "git deposu yok")
class DeneyKur(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        # kaynak proje (keşif çıktısı olan)
        k = cls.tmp / "kaynak"
        out = k / "workspace" / "docs" / "ekranlar"
        (out / "_ham").mkdir(parents=True)
        for r in ("/a", "/a/x", "/b"):
            slug = r.strip("/").replace("/", "-") or "kok"
            (out / "_ham" / f"{slug}.json").write_text(json.dumps({"durum": "tamam", "wid": ["w"], "th": ["k"], "cv": 0, "modals": [], "api": ["/api/a"]}))
        (out / "_ham" / "_durum.json").write_text(json.dumps({"bitti": {"/a": "tamam", "/a/x": "tamam", "/b": "tamam"}}))
        (out / "_api_semalari.json").write_text(json.dumps({"GET /api/a": {"durum": 200, "sema": "x", "birimler": ["/a", "/a/x"]}}))
        (k / "workspace" / "docs" / "org_chart.json").write_text(json.dumps({"hierarchy": [{"id": "x"}]}))
        (k / "workspace" / "studio.config.json").write_text(json.dumps({"analysis": {"output_dir": "workspace/docs/ekranlar"},
                                                                       "source": {"live_url": "https://x.example"}}))
        cls.brief = cls.tmp / "brief.md"
        cls.brief.write_text("Merhaba, kısa bir tohum brief.\n", encoding="utf-8")
        # framework: bu deponun şu anki commit'i (yerel klon, ağ yok)
        r = subprocess.run([sys.executable, str(ARAC), "kur", "--kaynak", str(k), "--hedef", str(cls.tmp), "--onek", "deney", "--brief", str(cls.brief),
                            "--kollar", "claude,gemini", "--framework-url", str(ROOT), "--plan"], capture_output=True, text=True)
        cls.cikti = r.stdout + r.stderr
        cls.rc = r.returncode

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_kurulum_basarili(self):
        self.assertEqual(self.rc, 0, self.cikti)

    def test_framework_remote_push_kapali_origin_yok(self):
        d = self.tmp / "deney-claude"
        r = subprocess.run(["git", "remote", "-v"], cwd=d, capture_output=True, text=True).stdout
        self.assertIn("framework", r)
        self.assertIn("DISABLED", r)                                  # framework deposuna push edilemez
        self.assertNotIn("origin", r)                                 # yanlışlıkla origin'e push yok

    def test_kola_ozgu_ayarlar_ve_ortak_girdi(self):
        c, g = self.tmp / "deney-claude", self.tmp / "deney-gemini"
        sc, sg = (c / "workspace/calistir.sh").read_text(), (g / "workspace/calistir.sh").read_text()
        self.assertIn('STUDIO_BACKEND="claude"', sc)
        self.assertIn('STUDIO_BACKEND="agy"', sg)
        self.assertIn('STUDIO_WEB_PORT="8090"', sc)
        self.assertIn('STUDIO_WEB_PORT="8091"', sg)                   # portlar çakışmaz
        self.assertNotIn("\r", sc)                                    # LF
        oc = json.loads((c / "workspace/deney.json").read_text())
        og = json.loads((g / "workspace/deney.json").read_text())
        for alan in ("brief", "org_chart", "planlama", "envanter"):
            self.assertEqual(oc["girdi"][alan], og["girdi"][alan], alan)   # ortak girdi paketi aynı

    def test_plan_uretildi_ve_aynidir(self):
        import sqlite3
        planlar = []
        for ad in ("claude", "gemini"):
            db = self.tmp / f"deney-{ad}" / "workspace" / "studio.db"
            self.assertTrue(db.exists())
            c = sqlite3.connect(db)
            rows = c.execute("select id, rol, baslik, aciklama, ciktilar, bagimlilik from pano_gorevleri order by sprint_id, sira").fetchall()
            self.assertGreater(len(rows), 10)
            planlar.append(rows)
        self.assertEqual(planlar[0], planlar[1])                      # deterministik: iki kolda görevler birebir aynı

    def test_framework_dosyalari_proje_deposunda_izlenmez(self):
        d = self.tmp / "deney-claude"
        izl = subprocess.run(["git", "ls-files"], cwd=d, capture_output=True, text=True).stdout.split()
        self.assertNotIn("basla.sh", izl)
        self.assertNotIn("studio_engine.py", izl)
        self.assertTrue((d / "basla.sh").exists())                    # diskte durur
        self.assertIn("workspace/docs/proje_kapsami.md", izl)         # proje dosyaları izlenir
        self.assertNotIn("workspace/studio.db", izl)

    def test_sifir_kurulum_analiz_kopyalamaz(self):
        r = subprocess.run([sys.executable, str(ARAC), "kur", "--sifir", "--kaynak-yol", str(self.tmp / "kaynak"), "--canli-url", "https://x.example", "--tur", "angular-spa",
                            "--hedef", str(self.tmp), "--onek", "sifir", "--brief", str(self.brief), "--kollar", "devin", "--framework-url", str(ROOT)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = self.tmp / "sifir-devin"
        self.assertFalse((d / "workspace/docs/ekranlar").exists())
        self.assertFalse((d / "workspace/docs/org_chart.json").exists())
        cfg = json.loads((d / "workspace/studio.config.json").read_text())
        self.assertEqual(cfg["source"]["live_url"], "https://x.example")
        self.assertNotIn("planlama", cfg)
        self.assertTrue((d / "workspace/docs/proje_kapsami.md").exists())
        self.assertIn('STUDIO_WEB_PORT="8092"', (d / "workspace/calistir.sh").read_text())   # tek kol kurulsa da devin portu sabit
        self.assertEqual(subprocess.run(["git", "status", "--short"], cwd=d, capture_output=True, text=True).stdout.strip(), "")

    def test_var_olan_klasorun_uzerine_yazmaz(self):
        r = subprocess.run([sys.executable, str(ARAC), "kur", "--kaynak", str(self.tmp / "kaynak"), "--hedef", str(self.tmp), "--onek", "deney",
                            "--kollar", "claude", "--framework-url", str(ROOT)], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("zaten var", r.stdout + r.stderr)

    def test_esitle_briefi_kopyalar_hash_tablosu(self):
        c, g = self.tmp / "deney-claude", self.tmp / "deney-gemini"
        (c / "workspace/docs/proje_kapsami.md").write_text("Görüşmeyle genişlemiş brief.\n", encoding="utf-8")
        r = subprocess.run([sys.executable, str(ARAC), "esitle", "--kaynak-kol", str(c), "--hedefler", str(g)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((g / "workspace/docs/proje_kapsami.md").read_text(encoding="utf-8"), "Görüşmeyle genişlemiş brief.\n")
        self.assertIn("✓", r.stdout)


if __name__ == "__main__":
    unittest.main()
