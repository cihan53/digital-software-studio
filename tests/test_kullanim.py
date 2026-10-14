"""LLM kullanım ekranı veri katmanı (issue #295)."""
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import kullanim as KU  # noqa: E402

AGY = ("Gemini Models\tWeekly Limit Remaining\t0%\t2026-10-14T06:20:41Z\n"
       "Gemini Models\tFive Hour Limit Remaining\tdisabled\t\n"
       "Claude and GPT models\tWeekly Limit Remaining\t100%\t2026-10-21T06:10:52Z\n")
CLAUDE = ("You are currently using your subscription\n\nCurrent session: 6% used · resets Oct 14 at 2:10pm (Europe/Istanbul)\n"
          "Current week (all models): 1% used · resets Oct 20 at 10pm (Europe/Istanbul)\n")


class Kullanim(unittest.TestCase):
    def test_agy_ayristir(self):
        s = KU.agy_ayristir(AGY)
        self.assertEqual(len(s), 3)
        self.assertEqual((s[0]["grup"], s[0]["pencere"], s[0]["kalan"]), ("Gemini Models", "Haftalık", 0))
        self.assertIsNone(s[1]["kalan"])
        self.assertEqual(s[1]["durum"], "disabled")
        self.assertEqual(s[2]["kalan"], 100)

    def test_claude_ayristir(self):
        s = KU.claude_ayristir(CLAUDE)
        self.assertEqual([(r["pencere"], r["kalan"]) for r in s], [("Oturum", 94), ("Haftalık (tüm modeller)", 99)])
        self.assertIn("Europe/Istanbul", s[0]["sifirlanma"])

    def test_cikti_yoksa_hata_doner(self):
        with mock.patch.object(KU, "_calistir", return_value=(1, "bulunamadı")):
            self.assertEqual(KU.agy_kullanim()["satirlar"], [])
            self.assertTrue(KU.agy_kullanim()["hata"])
        with mock.patch.object(KU, "_calistir", return_value=(0, "Logged in (via Devin).")):
            self.assertTrue(KU.devin_kullanim()["oturum"])
        with mock.patch.object(KU, "_calistir", return_value=(1, "Not logged in")):
            self.assertFalse(KU.devin_kullanim()["oturum"])

    def test_onbellek_hemen_doner_ve_arka_planda_yeniler(self):
        KU._ONBELLEK.update(zaman=0.0, veri=None, yenileniyor=False)
        with mock.patch.object(KU, "topla", return_value={"zaman": "x", "saglayicilar": {}, "proje": {}}):
            ilk = KU.getir(ROOT)
            self.assertEqual(ilk["zaman"], "")                    # veri henüz yok, çağrı bloklanmadı
            for _ in range(50):
                if not KU._ONBELLEK["yenileniyor"]:
                    break
                time.sleep(0.05)
            self.assertEqual(KU.getir(ROOT)["zaman"], "x")

    def test_metin_ciktisi(self):
        m = KU.metin({"saglayicilar": {"agy": {"ad": "Gemini (agy)", "satirlar": KU.agy_ayristir(AGY)}, "devin": {"ad": "Devin", "satirlar": [], "oturum": True}},
                      "proje": {"cagri": 3, "token_in": 10, "token_out": 5}})
        self.assertIn("%0 kalan", m)
        self.assertIn("Oturum: açık", m)


if __name__ == "__main__":
    unittest.main()
