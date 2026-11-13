#!/usr/bin/env python3
"""
tests/test_mobil_kanit.py
Mobil Canlı Önizleme, Emülatör Yönetimi ve UAT Çözüm Kanıtı Birim Testleri
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import studio_board as B
import mobil_yonetici as MY
import cozum_kaniti as CK


class TestMobilKanit(unittest.TestCase):

    def test_mobil_durum(self):
        durum = MY.genel_mobil_durum()
        self.assertTrue(durum.get("ok"))
        self.assertIn("adb_var", durum)
        self.assertIn("emulator_var", durum)
        self.assertIn("avd_listesi", durum)
        self.assertIsInstance(durum["avd_listesi"], list)

    def test_kanit_ekle_ve_getir(self):
        kid = B.kanit_ekle(
            talep_id="TEST-001",
            gorev_id="S99-T1",
            baslik="Mobil Harita Pinleme Düzeltildi",
            sorun="Harita üzerinde istasyonlar görünmüyordu.",
            cozum="Mobil koordinat projeksiyonu güncellendi.",
            sonuc="DOĞRULANDI",
            teknik_detay="station_map.dart güncellendi.",
            musteri_ozeti="Mobil harita ekranındaki istasyon görünümü düzeltildi.",
            ekran_goruntuleri=["workspace/docs/uat_kanitlari/test.png"],
            kaynak="test"
        )
        self.assertIsInstance(kid, int)
        self.assertGreater(kid, 0)

        # Tekil getir
        k = B.kanit_getir(kid)
        self.assertIsNotNone(k)
        self.assertEqual(k["talep_id"], "TEST-001")
        self.assertEqual(k["baslik"], "Mobil Harita Pinleme Düzeltildi")
        self.assertEqual(k["ekran_goruntuleri"], ["workspace/docs/uat_kanitlari/test.png"])

        # Talep bazlı listele
        liste = B.kanit_listele(talep_id="TEST-001")
        self.assertTrue(any(x["id"] == kid for x in liste))

    def test_otomatik_sentez(self):
        s = CK.otomatik_talep_kaniti_sentezle("TEST-002")
        self.assertEqual(s["talep_id"], "TEST-002")
        self.assertIn("sorun", s)
        self.assertIn("cozum", s)
        self.assertIn("musteri_ozeti", s)


if __name__ == "__main__":
    unittest.main()
