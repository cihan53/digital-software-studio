"""Panel insan onayları: onaylar(), onay_ver(), dosya erişimi ve HTTP güvenlik kontrolleri (issue #155)."""
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
import studio_board as B  # noqa: E402
import studio_web as W  # noqa: E402


def _board(onay_md: str) -> dict:
    t = lambda i, role, st, dep, out: {"id": i, "title": i, "description": f"{i} görevi", "role": role, "phase": "develop",
                                       "outputs": out, "depends_on": dep, "status": st, "order": 0}
    return {"sprints": [{"id": "S1", "name": "s", "order": 0, "tasks": [
        t("D1", "ui_designer", B.DONE, [], ["workspace/docs/tasarim/x.md"]),
        t("G1", "human", B.READY, ["D1"], [onay_md]),
        t("W1", "web_engineer", B.TODO, ["G1"], ["workspace/src/web/modules/x/"])]}]}


class PanelOnay(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.eski_db = B.DB_PATH
        B.DB_PATH = self.tmp / "t.db"
        self.onay_md = str(self.tmp / "onay.md")
        B.save(B.normalize(_board(self.onay_md)))

    def tearDown(self):
        B.DB_PATH = self.eski_db
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_listele_ve_incele_dosyasi(self):
        d = W.onaylar()
        g = d["onaylar"][0]
        self.assertEqual((g["id"], g["durum"], d["bekleyen"]), ("G1", "READY", 1))
        self.assertEqual(g["incele"], ["workspace/docs/tasarim/x.md"])        # bağımlı tasarım görevinin çıktısı

    def test_onay_ve_ret_kurallari(self):
        r = W.onay_ver({"id": "G1", "karar": "reject", "not": ""})
        self.assertFalse(r["ok"])                                               # ret için gerekçe zorunlu
        self.assertFalse(W.onay_ver({"id": "D1", "karar": "approve"})["ok"])    # insan görevi değil
        r = W.onay_ver({"id": "G1", "karar": "approve", "not": "uygun", "kim": "Test Kişi"})
        self.assertTrue(r["ok"], r)
        self.assertIn("Test Kişi", Path(self.onay_md).read_text(encoding="utf-8"))
        self.assertEqual(W.onaylar()["onaylar"][0]["durum"], "DONE")

    def test_dosya_yolu_kacisi_engellenir(self):
        for yol in ("../../etc/passwd", "/etc/passwd", "studio_engine.py", "workspace/../studio_web.py"):
            self.assertFalse(W.onay_dosya(yol)["ok"], yol)

    def test_http_post_guvenligi(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), W.Handler)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            def post(headers, body):
                req = urllib.request.Request(f"http://127.0.0.1:{port}/api/onay", data=json.dumps(body).encode(), headers=headers, method="POST")
                try:
                    return urllib.request.urlopen(req, timeout=10).status
                except urllib.error.HTTPError as e:
                    return e.code
            self.assertEqual(post({"Content-Type": "application/json", "Origin": "http://evil.example"}, {"id": "G1", "karar": "approve"}), 403)
            self.assertEqual(post({"Content-Type": "text/plain"}, {"id": "G1", "karar": "approve"}), 400)
            self.assertEqual(W.onaylar()["onaylar"][0]["durum"], "READY")        # reddedilen istekler karar vermedi
            self.assertEqual(post({"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"}, {"id": "G1", "karar": "approve", "not": "ok"}), 200)
            self.assertEqual(W.onaylar()["onaylar"][0]["durum"], "DONE")
        finally:
            srv.shutdown()


if __name__ == "__main__":
    unittest.main()
