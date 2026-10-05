"""Bütçe onayı beklenirken koşucu çıkmamalı; onay gelince devam etmeli (issue #215)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import studio_engine as E


class KotaBekle(unittest.TestCase):
    def setUp(self):
        self.eski = (E.B.ledger_check, E.B.is_set, E.time.sleep)
        E.time.sleep = lambda s: None

    def tearDown(self):
        E.B.ledger_check, E.B.is_set, E.time.sleep = self.eski

    def test_onay_gelince_devam(self):
        sayac = {"n": 0}

        def check(t):
            sayac["n"] += 1
            return (sayac["n"] >= 3, "")
        E.B.ledger_check, E.B.is_set = check, lambda b: False
        self.assertTrue(E.kota_onayi_bekle(0.5, azami_sn=3600))
        self.assertEqual(sayac["n"], 3)                                  # iki yoklama bekledi, üçüncüde izin aldı

    def test_stop_bayragi_cikarir(self):
        E.B.ledger_check = lambda t: (False, "dolu")
        E.B.is_set = lambda b: b == "stop"
        self.assertFalse(E.kota_onayi_bekle(0.5, azami_sn=3600))

    def test_zaman_asimi(self):
        E.B.ledger_check = lambda t: (False, "dolu")
        E.B.is_set = lambda b: False
        gercek = [0.0]
        orijinal = E.time.time
        E.time.time = lambda: gercek.__setitem__(0, gercek[0] + 100) or gercek[0]
        try:
            self.assertFalse(E.kota_onayi_bekle(0.5, azami_sn=500))
        finally:
            E.time.time = orijinal


if __name__ == "__main__":
    unittest.main()
