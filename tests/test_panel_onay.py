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
        self.assertEqual(g["dosyalar"][0]["tur"], "md")
        self.assertEqual([x["id"] for x in g["onaylanirsa"]], ["W1"])           # onaylanırsa başlayacak görev
        self.assertEqual([x["id"] for x in g["reddedilirse"]], ["D1"])          # reddedilirse yeniden çalışacak görev

    def test_onay_ve_ret_kurallari(self):
        r = W.onay_ver({"id": "G1", "karar": "reject", "not": ""})
        self.assertFalse(r["ok"])                                               # ret için gerekçe zorunlu
        self.assertFalse(W.onay_ver({"id": "D1", "karar": "approve"})["ok"])    # insan görevi değil
        r = W.onay_ver({"id": "G1", "karar": "approve", "not": "uygun", "kim": "Test Kişi"})
        self.assertTrue(r["ok"], r)
        self.assertIn("Test Kişi", Path(self.onay_md).read_text(encoding="utf-8"))
        self.assertEqual(W.onaylar()["onaylar"][0]["durum"], "DONE")

    def test_ret_revizyon_ister_ve_geri_bildirim_ekler(self):
        r = W.onay_ver({"id": "G1", "karar": "reject", "not": "Filtre barı eksik", "kim": "Test Kişi"})
        self.assertTrue(r["ok"], r)
        board = B.load()
        _, d1 = B.find_task(board, "D1")
        _, g1 = B.find_task(board, "G1")
        self.assertEqual(d1["status"], B.READY)                                  # tasarım yeniden çalışmaya hazır (bağımlılığı yok)
        self.assertIn("REVİZYON İSTEĞİ (Test Kişi): Filtre barı eksik", d1["description"])
        self.assertNotEqual(g1["status"], B.DONE)                                # kapı onaylanmadı, tasarım bitince yeniden sorulur

    def test_incele_satiri_dizin_ve_dosya_acar(self):
        d = Path(tempfile.mkdtemp())
        eski = W.ROOT
        try:
            W.ROOT = d
            (d / "workspace" / "docs" / "ekranlar" / "m").mkdir(parents=True)
            (d / "workspace" / "docs" / "ekranlar" / "m" / "a.md").write_text("# a")
            (d / "workspace" / "docs" / "ekranlar" / "m" / "_gizli.md").write_text("# g")
            (d / "workspace" / "docs" / "t.html").write_text("<p>x</p>")
            y = W._incele_yollari("Metin. İncele: workspace/docs/ekranlar/m, workspace/docs/t.html, /etc/passwd, ../disari.md")
            self.assertEqual(sorted(y), ["workspace/docs/ekranlar/m/a.md", "workspace/docs/t.html"])   # dizin açılır, gizli/dış yol alınmaz
        finally:
            W.ROOT = eski
            shutil.rmtree(d, ignore_errors=True)

    def test_bayat_pano_onayi_geri_almaz(self):
        bayat = B.load()                                              # koşucunun uzun görev başında aldığı bellek görüntüsü
        self.assertTrue(W.onay_ver({"id": "G1", "karar": "approve", "kim": "Test Kişi"})["ok"])
        B.save(bayat)                                                 # görev bitince bayat panoyu bütünüyle yazar
        _, g = B.find_task(B.load(), "G1")
        self.assertEqual(g["status"], B.DONE)                         # insan onayı kaybolmadı

    def test_aciklama_temiz_ve_dolayli_etki(self):
        a = W._aciklama_temiz("İNSAN KAPISI. X sunulur; onaylanır `python3 scripts/insan_onayi.py approve G1`. İncele: a.md, b")
        self.assertNotIn("python3", a)
        self.assertNotIn("İncele", a)
        self.assertNotIn("İNSAN KAPISI", a)
        d = W.onaylar()
        # W1 doğrudan G1'e bağlı; zincir bitince dolaylı görevler de listelenir (burada tek halka)
        self.assertEqual([x["id"] for x in d["onaylar"][0]["onaylanirsa"]], ["W1"])

    def test_gorsel_okuma_ve_eslestirme(self):
        d = Path(tempfile.mkdtemp())
        eski = W.ROOT
        try:
            W.ROOT = d
            g = d / "workspace" / "docs" / "ekranlar" / "_gorsel"
            g.mkdir(parents=True)
            (g / "a.png").write_bytes(b"\x89PNG\r\n\x1a\nXX")
            (g.parent / "m").mkdir()
            (g.parent / "m" / "a.md").write_text("# a")
            veri, hata = W.gorsel_oku("workspace/docs/ekranlar/_gorsel/a.png")
            self.assertIsNotNone(veri)
            for kotu in ("../etc/passwd", "/etc/passwd", "workspace/docs/ekranlar/m/a.md"):
                self.assertIsNone(W.gorsel_oku(kotu)[0], kotu)               # yol kaçışı ve png dışı reddedilir
            # görsel eşleştirme: ekranlar/<modül>/<ad>.md ↔ ekranlar/_gorsel/<ad>.png
            B.save(B.normalize({"sprints": [{"id": "S1", "name": "s", "order": 0, "tasks": [
                {"id": "G9", "title": "g", "description": "İncele: workspace/docs/ekranlar/m", "role": "human", "phase": "test",
                 "outputs": [str(d / "o.md")], "depends_on": [], "status": B.READY, "order": 0}]}]}))
            o = [x for x in W.onaylar()["onaylar"] if x["id"] == "G9"][0]
            self.assertEqual([x["ad"] for x in o["gorseller"]], ["a"])
        finally:
            W.ROOT = eski
            shutil.rmtree(d, ignore_errors=True)

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


class DosyaMeta(unittest.TestCase):
    def test_varsayim_ve_okunamadi_isaretlenir(self):
        d = Path(tempfile.mkdtemp())
        eski = W.ROOT
        try:
            W.ROOT = d
            (d / "workspace").mkdir()
            (d / "workspace" / "a.md").write_text("> **Varsayım:** `x.md` bu görevde okunamadı (okuma izni yok).\n> **Varsayım:** B bilinmiyor.\nbilinmiyor\n")
            (d / "workspace" / "b.md").write_text("> **Varsayım:** kapsam dar.\n")
            a, b = W._dosya_meta("workspace/a.md"), W._dosya_meta("workspace/b.md")
            self.assertEqual((a["varsayim"], a["okunamadi"], a["bilinmiyor"]), (2, True, 1))
            self.assertEqual((b["varsayim"], b["okunamadi"]), (1, False))
        finally:
            W.ROOT = eski
            shutil.rmtree(d, ignore_errors=True)
