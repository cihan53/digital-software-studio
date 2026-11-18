"""Müşteri sohbetinde çoklu (maks 5 adet) görsel desteği testleri (issue #366)."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import studio_board as B  # noqa: E402
import musteri_temsilcisi as MTC  # noqa: E402


class SohbetCokluGorselTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.eski_db = B.DB_PATH
        self.eski_agent = MTC.SOHBET_AGENT
        MTC.SOHBET_AGENT = False
        B.DB_PATH = self.tmp / "studio.db"
        conn = B.db_conn()
        conn.close()

    def tearDown(self):
        B.DB_PATH = self.eski_db
        MTC.SOHBET_AGENT = self.eski_agent
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_gorsel_listesi_coz(self):
        self.assertEqual(MTC._gorsel_listesi_coz(None), [])
        self.assertEqual(MTC._gorsel_listesi_coz(""), [])
        self.assertEqual(MTC._gorsel_listesi_coz("workspace/docs/a.png"), ["workspace/docs/a.png"])
        self.assertEqual(MTC._gorsel_listesi_coz("workspace/docs/a.png, workspace/docs/b.png"),
                         ["workspace/docs/a.png", "workspace/docs/b.png"])
        self.assertEqual(MTC._gorsel_listesi_coz(json.dumps(["workspace/docs/1.png", "workspace/docs/2.png"])),
                         ["workspace/docs/1.png", "workspace/docs/2.png"])

    def test_mesaj_gonder_coklu_gorsel_ve_taslak(self):
        oid = MTC.oturum_ac("Test Müşterisi")
        yollar = [
            "workspace/docs/sohbet_gorselleri/resim1.png",
            "workspace/docs/sohbet_gorselleri/resim2.png",
            "workspace/docs/sohbet_gorselleri/resim3.png",
        ]
        res = MTC.mesaj_gonder(oid, "Ödeme ekranında hata alıyorum", gorsel_yollari=yollar)
        self.assertTrue(res.get("oturum_id"))

        # Veritabanında saklanan mesajı kontrol et
        msgs = MTC.mesajlar(oid)
        musteri_msg = [m for m in msgs if m["gonderen"] == "musteri"][0]
        cozulmus_yollar = MTC._gorsel_listesi_coz(musteri_msg.get("gorsel_yolu"))
        self.assertEqual(cozulmus_yollar, yollar)

        # Taslak açıklamasında tüm görseller Markdown linki olarak yer almalı
        asistan_msg = [m for m in msgs if m["gonderen"] == "asistan"][0]
        taslak = asistan_msg.get("taslak")
        if taslak:
            aciklama = taslak.get("aciklama", "")
            for i, y in enumerate(yollar, 1):
                self.assertIn(f"![Ekran Görüntüsü {i}](/api/gorsel?yol={y})", aciklama)

        # Prompt geçmişinde ekli görseller listelenmeli
        gecmis = MTC._gecmis_promptu(oid)
        self.assertIn("Ekli Görseller (3 adet)", gecmis)

    def test_azami_5_gorsel_siniri(self):
        oid = MTC.oturum_ac("Test 5 Sınırı")
        yollar = [f"workspace/docs/sohbet_gorselleri/resim{i}.png" for i in range(1, 9)]  # 8 adet
        MTC.mesaj_gonder(oid, "Çok fazla görsel ekledim", gorsel_yollari=yollar)

        msgs = MTC.mesajlar(oid)
        musteri_msg = [m for m in msgs if m["gonderen"] == "musteri"][0]
        cozulmus_yollar = MTC._gorsel_listesi_coz(musteri_msg.get("gorsel_yolu"))
        self.assertEqual(len(cozulmus_yollar), 5)  # En fazla 5 adet olmalı

    def test_geriye_donuk_tekil_gorsel_uyumlulugu(self):
        oid = MTC.oturum_ac("Tekil Test")
        tek_yol = "workspace/docs/sohbet_gorselleri/tek.png"
        res = MTC.mesaj_gonder(oid, "Tek görsel", gorsel_yolu=tek_yol)

        msgs = MTC.mesajlar(oid)
        musteri_msg = [m for m in msgs if m["gonderen"] == "musteri"][0]
        self.assertEqual(musteri_msg.get("gorsel_yolu"), tek_yol)

        asistan_msg = [m for m in msgs if m["gonderen"] == "asistan"][0]
        taslak = asistan_msg.get("taslak")
        if taslak:
            self.assertIn(f"![Ekran Görüntüsü](/api/gorsel?yol={tek_yol})", taslak.get("aciklama", ""))


if __name__ == "__main__":
    unittest.main()
