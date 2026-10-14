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


class KotaBekleme297(unittest.TestCase):
    def test_claude_zaman_ayristirma(self):
        from datetime import datetime
        z = KU.claude_zaman("Oct 14 at 2:09pm (Europe/Istanbul)", simdi=datetime(2026, 10, 14, 9, 0).astimezone())
        self.assertEqual((z.month, z.day, z.hour, z.minute), (10, 14, 14, 9))
        self.assertEqual(KU.claude_zaman("Oct 20 at 10pm (Europe/Istanbul)").hour, 22)
        self.assertIsNone(KU.claude_zaman("yarın"))
        self.assertIn("sifirlanma_iso", KU.claude_ayristir(CLAUDE)[0])

    def test_bekleme_hedefi_en_gec_sifirlanma_ve_grup_suzgeci(self):
        sat = [{"grup": "Gemini Models", "pencere": "Haftalık", "kalan": 0, "sifirlanma_iso": "2026-10-14T06:20:41Z"},
               {"grup": "Gemini Models", "pencere": "5 saatlik", "kalan": 0, "sifirlanma_iso": "2026-10-14T11:00:00Z"},
               {"grup": "Gemini Models", "pencere": "x", "kalan": None, "durum": "disabled", "sifirlanma_iso": ""},
               {"grup": "Claude and GPT models", "pencere": "Haftalık", "kalan": 100, "sifirlanma_iso": "2026-10-21T06:10:52Z"}]
        hedef, tuk = KU.bekleme_hedefi(sat, "Gemini")
        self.assertEqual(len(tuk), 2)
        self.assertEqual((hedef.hour, hedef.minute), (11, 0))                       # hepsi sıfırlanmadan sürmez → en geç olan
        self.assertEqual(KU.bekleme_hedefi(sat, "Claude and GPT")[0], None)         # o grup tükenmemiş
        self.assertEqual(KU.bekleme_hedefi([], "Gemini"), (None, []))

    def test_motor_sifirlanmaya_kadar_bekler_panele_yazar_ve_temizler(self):
        import studio_engine as E
        from datetime import datetime, timedelta, timezone
        hedef = datetime.now(timezone.utc) + timedelta(minutes=30)
        sat = [{"grup": "Gemini Models", "pencere": "Haftalık"}]
        saat = {"t": 1000.0}

        def zaman():
            saat["t"] += 400.0
            return saat["t"]

        E._SIFIRLANMA_BEKLENEN.clear()
        istekler = []
        with mock.patch.object(KU, "limit_bilgisi", return_value=(hedef, sat)), mock.patch.object(E.time, "time", side_effect=zaman), \
                mock.patch.object(E.time, "sleep"), mock.patch.object(E.B, "is_set", return_value=False), mock.patch.object(E.B, "value_of", return_value=None), \
                mock.patch.object(E.B, "request", side_effect=lambda *a, **k: istekler.append(("request", a[0]))), \
                mock.patch.object(E.B, "clear", side_effect=lambda n: istekler.append(("clear", n))), mock.patch.object(E.B, "audit"):
            self.assertTrue(E._sifirlanmaya_kadar_bekle("429", "agy", ""))
            self.assertEqual(istekler[0], ("request", "limit_bekliyor"))
            self.assertEqual(istekler[-1], ("clear", "limit_bekliyor"))
            self.assertFalse(E._sifirlanmaya_kadar_bekle("429", "agy", ""))       # aynı hedef ikinci kez beklenmez (sonsuz döngü yok)
            self.assertFalse(E._sifirlanmaya_kadar_bekle("429", "devin", ""))     # devin'de bilgi yok → eski davranış

    def test_azami_sinirdan_uzak_sifirlanma_beklenmez(self):
        import studio_engine as E
        from datetime import datetime, timedelta, timezone
        E._SIFIRLANMA_BEKLENEN.clear()
        hedef = datetime.now(timezone.utc) + timedelta(hours=400)
        with mock.patch.object(KU, "limit_bilgisi", return_value=(hedef, [{"grup": "g", "pencere": "p"}])):
            self.assertFalse(E._sifirlanmaya_kadar_bekle("429", "agy", ""))

    def test_panel_nedeni(self):
        import gozlem as GO
        n = GO.bekleme_nedeni(None, {"limit_bekliyor": '{"backend": "agy", "pencereler": "Gemini Models Haftalık", "sifirlanma": "14.10 09:20", "gorev": "S36-T5"}'}, True, None, {}, False)
        self.assertEqual(n["kod"], "kota_sifirlanma")
        self.assertIn("14.10 09:20", n["mesaj"])


if __name__ == "__main__":
    unittest.main()
