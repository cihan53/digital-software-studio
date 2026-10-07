"""Canlı ortamı çerçeve açar (v2, issue #263)."""
import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import studio_board as B  # noqa: E402
import studio_engine as E  # noqa: E402
import onarim as ON  # noqa: E402


class CanliOtomatik(unittest.TestCase):
    def setUp(self):
        self.e = (B.live_baslatilabilir, B.live_up, ON.ortam_hazirla, B.audit)
        self.cagri = []
        B.live_baslatilabilir = lambda: True
        B.audit = lambda *a, **k: None
        self.acik = False
        B.live_up = lambda: self.acik
        E.run_board.__dict__.pop("_canli_oto", None)
        os.environ.pop("STUDIO_CANLI_OTOMATIK", None)

        def hazirla(kok, yeniden=False, bekle_sn=150):
            self.cagri.append(1)
            self.acik = self.basarili
            return self.basarili
        self.basarili = True
        ON.ortam_hazirla = hazirla

    def tearDown(self):
        B.live_baslatilabilir, B.live_up, ON.ortam_hazirla, B.audit = self.e
        os.environ.pop("STUDIO_CANLI_OTOMATIK", None)
        E.run_board.__dict__.pop("_canli_oto", None)

    def test_kapaliyken_baslatir(self):
        self.assertTrue(E._canli_otomatik_baslat({"id": "S1-T1"}))
        self.assertEqual(len(self.cagri), 1)

    def test_basarisizlikta_aralik_ve_sinir(self):
        self.basarili = False
        self.assertFalse(E._canli_otomatik_baslat({"id": "S1-T1"}))
        self.assertFalse(E._canli_otomatik_baslat({"id": "S1-T1"}))     # aralık dolmadı
        self.assertEqual(len(self.cagri), 1)
        for _ in range(5):                                              # aralık dolmuş say, sınıra kadar dene
            E.run_board._canli_oto["son"] = time.time() - E.CANLI_DENEME_ARALIK_SN - 1
            E._canli_otomatik_baslat({"id": "S1-T1"})
        self.assertEqual(len(self.cagri), E.CANLI_DENEME_SINIR)

    def test_kapatma_ve_betiksiz(self):
        os.environ["STUDIO_CANLI_OTOMATIK"] = "0"
        self.assertFalse(E._canli_otomatik_baslat({"id": "S1-T1"}))
        os.environ.pop("STUDIO_CANLI_OTOMATIK")
        B.live_baslatilabilir = lambda: False
        self.assertFalse(E._canli_otomatik_baslat({"id": "S1-T1"}))
        self.assertEqual(self.cagri, [])


if __name__ == "__main__":
    unittest.main()
