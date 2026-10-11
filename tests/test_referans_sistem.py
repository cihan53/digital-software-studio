"""Referans sistem: analiz/plan/tasarım görevleri eski sistem erişilemezse bekletilir (issue #277)."""
import http.server
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import studio_board as B  # noqa: E402
import referans_sistem as RS  # noqa: E402
import envanter_asamasi as EA  # noqa: E402


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response({"/ok": 200, "/giris": 401, "/hata": 503}.get(self.path, 404))
        self.end_headers()

    def log_message(self, *a):
        pass


class Referans(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def cfg(self, yol="ok", **kw):
        return {"source": {"path": tempfile.gettempdir(), "live_url": f"http://127.0.0.1:{self.port}/{yol}"}, **kw}

    def test_tanimsiz_proje_etkilenmez(self):
        self.assertFalse(RS.tanimli({}))
        self.assertEqual(RS.hazir_mi({}), (True, ""))

    def test_ayakta_ve_giris_isteyen_hazir(self):
        self.assertTrue(RS.hazir_mi(self.cfg("ok"))[0])
        self.assertTrue(RS.durum(self.cfg("giris"), onbellek=False)["hazir"])          # 401: ayakta, giriş istiyor

    def test_5xx_ve_ulasilamayan_hazir_degil(self):
        ok, neden = RS.hazir_mi(self.cfg("hata"))
        self.assertFalse(ok)
        self.assertIn("503", neden)
        ok, neden = RS.hazir_mi({"source": {"path": tempfile.gettempdir(), "live_url": "http://127.0.0.1:9/"}})
        self.assertFalse(ok)
        self.assertIn("erişilemiyor", neden)

    def test_kaynak_yoksa_hazir_degil_ve_referans_alani_oncelikli(self):
        ok, neden = RS.hazir_mi({"source": {"path": "/yok/yok"}})
        self.assertFalse(ok)
        self.assertIn("kaynak kodu yok", neden)
        c = {"source": {"path": "/yok/yok"}, "referans": {"kaynak": tempfile.gettempdir(), "url": f"http://127.0.0.1:{self.port}/ok"}}
        self.assertEqual(RS.tanim(c)["kaynak"], tempfile.gettempdir())
        self.assertTrue(RS.hazir_mi(c)[0])

    def test_roller_referans_gerektirir_canli_gerektirmez(self):
        for r in ("envanter_analisti", "ui_designer", "sprint_planner"):
            self.assertTrue(B.needs_referans({"role": r}))
            self.assertFalse(B.needs_live({"role": r, "title": "UAT ziyaretçi", "description": ""}))
        self.assertFalse(B.needs_referans({"role": "web_engineer"}))

    def test_envanter_gorevleri_referans_adresini_icerir(self):
        c = self.cfg("ok")
        self.assertIn("REFERANS SİSTEM", EA.referans_notu(c))
        self.assertIn(f"127.0.0.1:{self.port}", EA.referans_notu(c))
        self.assertEqual(EA.referans_notu({"source": {"path": "/x"}}), "")

    def test_analist_webfetch_araci(self):
        org = json.loads((ROOT / "org_chart.json").read_text(encoding="utf-8"))
        r = next(a for a in org["hierarchy"] if a["id"] == EA.ANALIST)
        self.assertIn("WebFetch", r["tools"])


if __name__ == "__main__":
    unittest.main()
