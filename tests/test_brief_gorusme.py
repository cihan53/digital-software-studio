"""Brief görüşmesi (issue #173): rol sırası, cevabın kullanıcı sözleriyle brief'e işlenmesi, LLM'siz yedek, panel API güvenliği."""
import json
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import brief_gorusme as BG  # noqa: E402
import studio_web as W  # noqa: E402


class Gorusme(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.eski = (BG.ROOT, BG.STATE, BG._llm)
        BG.ROOT = self.tmp
        BG.STATE = self.tmp / "workspace" / "docs" / "brief_gorusme.json"
        (self.tmp / "workspace" / "docs").mkdir(parents=True)
        (self.tmp / "workspace" / "docs" / "proje_kapsami.md").write_text("Eski sistemi Vue'ya taşımak istiyorum.\n", encoding="utf-8")
        self.cagrilar = []

        def sahte(rol, sistem, kullanici):
            self.cagrilar.append(rol)
            if "kısa bir konu" in sistem:                     # cevap işleme
                return '{"konu": "Başarı ölçütü", "not": "Ölçülebilir hale getirilmeli."}'
            return json.dumps({"soru": f"{rol} sorusu", "secenekler": ["a", "b"], "bitti": False})
        BG._llm = sahte

    def tearDown(self):
        BG.ROOT, BG.STATE, BG._llm = self.eski
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_roller_sirayla_tek_soru_sorar(self):
        r1 = BG.soru_uret()["tur"]
        self.assertEqual(r1["rol"], "musteri_temsilcisi")
        self.assertEqual(BG.soru_uret()["tur"]["id"], r1["id"])            # cevaplanmamış soru varken yenisi üretilmez
        BG.cevapla("Hızlı ve güvenilir olsun.")
        self.assertEqual(BG.soru_uret()["tur"]["rol"], "product_owner")
        BG.cevapla("Önce yönetici panoları.")
        self.assertEqual(BG.soru_uret()["tur"]["rol"], "cto")

    def test_cevap_kullanici_sozleriyle_rol_etiketli_brief_e_islenir(self):
        BG.soru_uret()
        BG.cevapla("Yönetici panoları ilk gelsin.")
        brief = (self.tmp / "workspace" / "docs" / "proje_kapsami.md").read_text(encoding="utf-8")
        self.assertIn("Eski sistemi Vue'ya taşımak istiyorum.", brief)         # mevcut satırlar silinmez
        self.assertIn("<!-- rol: musteri_temsilcisi -->", brief)
        self.assertIn("**Başarı ölçütü:** Yönetici panoları ilk gelsin.", brief)  # kullanıcının sözü aynen
        self.assertIn("Müşteri Temsilcisi notu:_ Ölçülebilir hale getirilmeli.", brief)

    def test_llm_yoksa_yedek_soru_ve_cevap_yine_islenir(self):
        def bozuk(*a):
            raise RuntimeError("LLM yok")
        BG._llm = bozuk
        t = BG.soru_uret()["tur"]
        self.assertIn("en önemli sonuç", t["soru"])
        self.assertTrue(BG.cevapla("Hızlı.")["ok"])
        self.assertIn("Hızlı.", (self.tmp / "workspace" / "docs" / "proje_kapsami.md").read_text(encoding="utf-8"))

    def test_bos_cevap_ve_soru_yokken_cevap_reddedilir(self):
        self.assertFalse(BG.cevapla("cevap")["ok"])                          # soru yok
        BG.soru_uret()
        self.assertFalse(BG.cevapla("   ")["ok"])

    def test_http_guvenligi(self):
        eski = W._bg
        W._bg = lambda: BG
        srv = ThreadingHTTPServer(("127.0.0.1", 0), W.Handler)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            def post(headers, body):
                req = urllib.request.Request(f"http://127.0.0.1:{port}/api/brief-gorusme", data=json.dumps(body).encode(), headers=headers, method="POST")
                try:
                    return urllib.request.urlopen(req, timeout=10).status
                except urllib.error.HTTPError as e:
                    return e.code
            self.assertEqual(post({"Content-Type": "application/json", "Origin": "http://evil.example"}, {"islem": "soru"}), 403)
            self.assertEqual(post({"Content-Type": "text/plain"}, {"islem": "soru"}), 400)
            self.assertEqual(post({"Content-Type": "application/json"}, {"islem": "soru"}), 200)
            self.assertEqual(BG.ozet()["turlar"][0]["rol"], "musteri_temsilcisi")
        finally:
            srv.shutdown()
            W._bg = eski


if __name__ == "__main__":
    unittest.main()
