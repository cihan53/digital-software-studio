"""Mod 2 (var olan proje devralma, mutabakat ve eklemeli planlama) testleri (issue #321)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import mevcut_proje_analizi as MPA
import mod2_mutabakat as M2
import studio_board as B


class Mod2AkisiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "workspace" / "src" / "api").mkdir(parents=True)
        (self.tmp / "workspace" / "src" / "api" / "server.py").write_text("print('manuel kod')\n", encoding="utf-8")
        (self.tmp / "workspace" / "docs").mkdir(parents=True, exist_ok=True)
        self._eski_sohbet = os.environ.get("STUDIO_SOHBET_AGENT")
        os.environ["STUDIO_SOHBET_AGENT"] = "0"

    def tearDown(self):
        if self._eski_sohbet is None:
            os.environ.pop("STUDIO_SOHBET_AGENT", None)
        else:
            os.environ["STUDIO_SOHBET_AGENT"] = self._eski_sohbet

    def test_tahribatsiz_analiz_mevcut_koda_dokunmaz(self):
        eski_icerik = (self.tmp / "workspace" / "src" / "api" / "server.py").read_text(encoding="utf-8")
        durum = MPA.analiz_calistir(self.tmp, hizli=True)
        self.assertTrue(durum["envanter"]["var"])
        self.assertEqual(durum["envanter"]["dosya_sayisi"], 1)
        self.assertIn("api", durum["envanter"]["bilesenler"])
        self.assertTrue((self.tmp / "workspace" / "docs" / "mevcut_proje_analizi.md").is_file())
        self.assertTrue((self.tmp / "workspace" / "docs" / "mevcut_proje_durumu.json").is_file())
        self.assertEqual(
            (self.tmp / "workspace" / "src" / "api" / "server.py").read_text(encoding="utf-8"),
            eski_icerik,
        )

    def test_mutabakat_kilidi_ve_eklemeli_planlama(self):
        MPA.analiz_calistir(self.tmp, hizli=True)
        r = M2.istek_ekle("Kullanıcı profil sayfasına dışa aktarma butonu eklensin", tur="ISTEK", oncelik="YUKSEK", kok=self.tmp)
        self.assertTrue(r["ok"])
        paket = M2.oneri_paketi_olustur(self.tmp)
        self.assertTrue(paket["ok"])
        self.assertGreaterEqual(len(paket["maddeler"]), 1)

        # Onaysız planlamaya geçilemez
        kilit = M2.planlamaya_aktar(self.tmp)
        self.assertFalse(kilit["ok"])

        # Tüm maddeleri karara bağla (ilk madde ONAYLANDI, diğerleri REDDEDILDI)
        for idx, m in enumerate(paket["maddeler"]):
            karar = "ONAYLANDI" if idx == 0 else "REDDEDILDI"
            kr = M2.karar_ver(m["id"], karar, "test onayı", kok=self.tmp)
            self.assertTrue(kr["ok"])
        self.assertTrue(M2.mutabakat_hazir_mi(M2.yukle(self.tmp)))

        # Mevcut studio.db geçmişini izole edip korunduğunu doğrula
        eski_db = B.DB_PATH
        eski_root = B.ROOT
        try:
            B.ROOT = self.tmp
            B.DB_PATH = self.tmp / "workspace" / "studio.db"
            mevcut_board = {
                "project": "test-proj",
                "sprints": [{
                    "id": "S1",
                    "name": "Eski Sprint",
                    "status": B.DONE,
                    "tasks": [{"id": "S1-T1", "title": "Eski iş", "role": "backend_engineer", "phase": "develop", "status": B.DONE}],
                }],
            }
            B.save(mevcut_board)

            sonuc = M2.planlamaya_aktar(self.tmp)
            self.assertTrue(sonuc["ok"])
            guncel = B.load()
            self.assertEqual(len(guncel["sprints"]), 2)
            self.assertEqual(guncel["sprints"][0]["id"], "S1")
            self.assertEqual(guncel["sprints"][0]["tasks"][0]["status"], B.DONE)
            self.assertEqual(guncel["sprints"][1]["id"], sonuc["sprint_id"])

            # Idempotent kontrol: ikinci çağrı tekrar sprint eklemez
            sonuc2 = M2.planlamaya_aktar(self.tmp)
            self.assertTrue(sonuc2["ok"])
            self.assertEqual(len(B.load()["sprints"]), 2)
        finally:
            B.ROOT = eski_root
            B.DB_PATH = eski_db

    def test_studio_version_tracked_files_dahil(self):
        ver = json.loads((ROOT / "studio.version").read_text(encoding="utf-8"))
        tf = set(ver.get("tracked_files") or [])
        self.assertIn("scripts/mevcut_proje_analizi.py", tf)
        self.assertIn("scripts/mod2_mutabakat.py", tf)

    def test_basla_sh_mod2_korumasi(self):
        # basla.sh sözdizimi geçerli olmalı
        r = subprocess.run(["bash", "-n", str(ROOT / "basla.sh")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
