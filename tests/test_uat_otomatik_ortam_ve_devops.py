"""UAT Canlı Ortam Otomasyonu, Durum Bayrağı ve DevOps Hatası Devri Testleri (issue #338)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import studio_board as B  # noqa: E402
import studio_engine as E  # noqa: E402
import onarim as ON  # noqa: E402


class UatOtomatikOrtamVeDevopsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.eski_control = B.CONTROL_DIR
        B.CONTROL_DIR = Path(self.tmp) / "workspace" / ".control"
        B.CONTROL_DIR.mkdir(parents=True, exist_ok=True)
        E.run_board.__dict__.pop("_canli_oto", None)

    def tearDown(self):
        B.CONTROL_DIR = self.eski_control
        E.run_board.__dict__.pop("_canli_oto", None)

    def test_yerel_ortam_bayrak_yaz_ve_oku(self):
        """Bayrak 'baslatiliyor', 'hazir', 'hata', 'durdu' değerlerini doğru yazar ve okur."""
        B.yerel_ortam_bayrak_yaz("baslatiliyor", {"portlar": [3000, 3001]})
        b1 = B.yerel_ortam_bayrak_oku()
        self.assertEqual(b1["durum"], "baslatiliyor")
        self.assertEqual(b1["detay"]["portlar"], [3000, 3001])
        self.assertTrue(b1["zaman"])

        B.yerel_ortam_bayrak_yaz("hazir")
        b2 = B.yerel_ortam_bayrak_oku()
        self.assertEqual(b2["durum"], "hazir")

        B.yerel_ortam_bayrak_yaz("hata", {"neden": "zaman_asimi"})
        b3 = B.yerel_ortam_bayrak_oku()
        self.assertEqual(b3["durum"], "hata")
        self.assertEqual(b3["detay"]["neden"], "zaman_asimi")

    def test_canli_otomatik_baslat_bayraklari_yonetir(self):
        """_canli_otomatik_baslat başarılı ve başarısız durumlarda doğru bayrakları koyar."""
        eski_live_baslatilabilir = B.live_baslatilabilir
        eski_live_up = B.live_up
        eski_ortam_hazirla = ON.ortam_hazirla
        eski_audit = B.audit
        try:
            B.live_baslatilabilir = lambda: True
            B.audit = lambda *a, **k: None

            # Başarılı senaryo
            B.live_up = lambda: True
            ON.ortam_hazirla = lambda root: True
            ok = E._canli_otomatik_baslat({"id": "S1-T2"})
            self.assertTrue(ok)
            b = B.yerel_ortam_bayrak_oku()
            self.assertEqual(b["durum"], "hazir")

            # Başarısız senaryo
            E.run_board.__dict__.pop("_canli_oto", None)
            B.live_up = lambda: False
            ON.ortam_hazirla = lambda root: False
            ok = E._canli_otomatik_baslat({"id": "S1-T2"})
            self.assertFalse(ok)
            b = B.yerel_ortam_bayrak_oku()
            self.assertEqual(b["durum"], "hata")
        finally:
            B.live_baslatilabilir = eski_live_baslatilabilir
            B.live_up = eski_live_up
            ON.ortam_hazirla = eski_ortam_hazirla
            B.audit = eski_audit

    def test_ortam_hatasi_devopsa_devret(self):
        """Ortam başlatılamadığında UAT BLOCKED olur, devops onarım görevi panoya eklenir."""
        task = {
            "id": "S12-T4",
            "title": "[TALEP-011] Müşteri Kabulü & UAT Doğrulama Denetimi",
            "role": "uat_auditor",
            "status": "READY"
        }
        sprint = {
            "id": "S12",
            "tasks": [task]
        }
        board = {
            "sprints": [sprint]
        }

        eski_git_auto_commit = E.git_auto_commit
        E.git_auto_commit = lambda msg: None
        import musteri_talepleri as MT
        eski_yeni_talep = MT.yeni_talep
        MT.yeni_talep = lambda **kw: {"id": "TALEP-999"}
        eski_guncelle = MT.guncelle
        MT.guncelle = lambda *a, **k: None
        try:
            E._ortam_hatasi_devopsa_devret(task, sprint, board)

            # 1. UAT görevi BLOCKED olmalı (takılı kalmamalı)
            self.assertEqual(task["status"], "BLOCKED")
            self.assertIn("DevOps", task.get("note", ""))

            # 2. Panoya devops_engineer onarım görevi eklenmeli
            gorev_ids = [t["id"] for t in sprint["tasks"]]
            self.assertIn("S12-DEVOPS", gorev_ids)
            devops_gorev = sprint["tasks"][0]
            self.assertEqual(devops_gorev["id"], "S12-DEVOPS")
            self.assertEqual(devops_gorev["role"], "devops_engineer")
            self.assertEqual(devops_gorev["status"], "READY")
        finally:
            E.git_auto_commit = eski_git_auto_commit
            MT.yeni_talep = eski_yeni_talep
            MT.guncelle = eski_guncelle


if __name__ == "__main__":
    unittest.main()
