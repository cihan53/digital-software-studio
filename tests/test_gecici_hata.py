"""Geçici hata (SIGKILL/interrupted) görevi öldürmez, koşucuyu kapatmaz (issue #311)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import studio_engine as E  # noqa: E402


class GeciciHata(unittest.TestCase):
    def test_kesinti_hatalari_gecici_sayilir(self):
        for m in ("agy hata koduyla çıktı (-9): error: interrupted", "devin hata koduyla çıktı (-15)", "process killed: 9", "error: interrupted"):
            self.assertTrue(E.is_limit_error(m), m)

    def test_deterministik_hatalar_gecici_degil(self):
        for m in ("girdi okunamadı beyanı: çıktı yazılmadı (GİRDİ-EKSİK / okunamadı)", "derleme başarısız (import 3)", "rol bulunamadı: x", "kaynak uygulanmadı"):
            self.assertFalse(E.is_limit_error(m), m)

    def test_azami_deneme_ayari(self):
        self.assertEqual(E.GOREV_HATA_AZAMI, 3)


if __name__ == "__main__":
    unittest.main()
