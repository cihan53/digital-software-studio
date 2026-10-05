"""kesif_yaz + izin etiketleri + gezgin uçtan uca güvenlik testi (issue #132)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
import urllib.parse
import http.server
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import studio_config as C  # noqa: E402
import kesif_denetle as K  # noqa: E402
import kesif_yaz as Y  # noqa: E402
import analiz_dogrula as A  # noqa: E402

D = C._merge(C.DEFAULTS, {"discovery": {"allow": {"hosts": ["h.io"]}}})["discovery"]
CHROME = os.environ.get("CHROME_PATH", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

RAW = {"birim": "/items", "durum": "tamam", "url": "https://h.io/items", "desc": "Kayıtları listeler ve yönetir, uzun açıklama.",
       "h": ["Items"], "wid": ["w-1"], "btn": ["New item", "Clear Filters"], "tabs": [], "th": ["Name", "Status"], "inp": ["Search"],
       "sel": 1, "pick": 0, "api": ["/api/items"], "cv": 0, "txt": "No items found",
       "modals": [{"label": "New item", "acildi": True, "tur": "modal", "baslik": "Add", "alanlar": ["Name"], "butonlar": ["Close", "Add"]},
                  {"label": "Add user", "atlandi": "yasak etiket"}],
       "post_istekleri": []}


class IzinEtiket(unittest.TestCase):
    def test_yasak_etiketler(self):
        for lab in ("Save changes", "Delete", "Bulk Merge", "Export CSV", "Refresh Data"):
            self.assertFalse(K.izin("https://h.io/x", "reversible", lab, D)[0], lab)
        for lab in ("New Team", "Add widget", "Filter"):
            self.assertTrue(K.izin("https://h.io/x", "reversible", lab, D)[0], lab)


class Yaz(unittest.TestCase):
    def test_sablon_kanit_ve_tavan(self):
        cfg = C._merge(C.DEFAULTS, {})
        txt = Y.render(RAW, cfg["analysis"]["template"], cfg["analysis"]["max_words_l1"])
        self.assertIn("## modal ve çekmeceler", txt)
        self.assertIn("tıklanmadı (yasak etiket)", txt)
        self.assertIn("[kaynak: https://h.io/items]", txt)
        self.assertIn("## roller\nbilinmiyor", txt)          # gözlenmeyen alan uydurulmaz
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "a.md"
            p.write_text(txt, encoding="utf-8")
            errs, lv = A.check_file(p, cfg["analysis"])
            self.assertEqual((errs, lv), ([], "L1"))


class Roller(unittest.TestCase):
    def test_angular_guard_ve_rol_miras(self):
        import kesif_roller as R
        with tempfile.TemporaryDirectory() as t:
            app = Path(t) / "src" / "app" / "routes"
            (app / "admin").mkdir(parents=True)
            (app / "routes-routing.module.ts").write_text("""
const routes = [{ path: '', canActivate: [AuthGuard], children: [
  { path: 'home', canActivate: [NgxPermissionsGuard, MenuGuard],
    data: { isHomeRedirect: true, permissions: { only: [UserRoleEnum.ROLE_ADMIN, UserRoleEnum.ROLE_USER], redirectTo: 'admin' } } },
  { path: 'admin', loadChildren: () => import('./admin/admin.module').then(m => m.AdminModule),
    data: { requiredMenu: SidebarMenuEnum.ADMIN_PANEL, forbiddenRedirect: '/403' } },
  { path: 'open', component: X },
]}];""")
            (app / "admin" / "admin-routing.module.ts").write_text("""
const routes = [{ path: 'users/:id', canActivate: [FeatureToggleGuard] }, { path: '', redirectTo: 'users/1', pathMatch: 'full' }];""")
            out: dict = {}
            R.collect(str(app / "routes-routing.module.ts"), "", {}, out, str(app.parent), set())
            self.assertEqual(out["/home"]["only"], ["ROLE_ADMIN", "ROLE_USER"])
            self.assertEqual(out["/home"]["guards"], ["AuthGuard", "NgxPermissionsGuard", "MenuGuard"])
            self.assertEqual(out["/home"]["perm_redirect"], "admin")
            self.assertEqual(out["/open"]["guards"], ["AuthGuard"])
            self.assertNotIn("only", out["/open"])                      # kardeş rotanın kuralı sızmaz
            self.assertEqual(out["/admin/users/:id"]["menu"], "ADMIN_PANEL")   # lazy modül ebeveynden miras alır
            self.assertIn("FeatureToggleGuard", out["/admin/users/:id"]["guards"])
            self.assertEqual(out["/admin/users/:id"]["forbidden"], "/403")

    def test_roller_metni_ve_kanit(self):
        self.assertEqual(Y.roller_metni(None), "bilinmiyor")
        t = Y.roller_metni({"guards": ["AuthGuard"], "only": ["ROLE_ADMIN"], "perm_redirect": "/", "menu": "X"})
        self.assertIn("izinli roller: ROLE_ADMIN (yetkisizse → /)", t)
        al = Y.alanlar({**RAW, "url": "https://h.io/items"}, 6, {"guards": ["AuthGuard"], "dosya": "routes/a.ts"})
        self.assertIn("[kaynak: src/app/routes/a.ts]", al["roller"])
        self.assertIn("rol/menü kısıtı yok", al["roller"])

    def test_post_uclari_risk_degil_api_yontemi(self):
        al = Y.alanlar({**RAW, "api": ["/api/w"], "post_istekleri": ["POST /api/w"]}, 6)
        self.assertIn("POST /api/w", al["api uçları"])
        self.assertEqual(al["riskler"], "bilinmiyor")


SITE = """<html><title>Home</title><body><main><h1>Home</h1><p>Bu sayfa ana özet ekranıdır ve test amaçlıdır, uzun açıklama.</p>
<button id=n>New item</button><button id=s>Save all</button><button id=d>Delete</button>
<table><tbody><tr onclick="location.href='/items/7'"><td>row1</td><td>x</td></tr></tbody></table>
<div id=dlg role=dialog style="display:none"><h2>Add Item</h2><input placeholder="Title"><button aria-label=Close>x</button><button id=a>Add</button></div></main>
<script>
window.__tik=[];
for (const b of document.querySelectorAll('button')) b.addEventListener('click',()=>{fetch('/tik?b='+b.textContent)});
document.getElementById('n').onclick=()=>{dlg.style.display='block'};
document.querySelector('[aria-label=Close]').onclick=()=>{dlg.style.display='none'};
fetch('/api/items');</script></body></html>"""


@unittest.skipUnless(shutil.which("node") and Path(CHROME).exists(), "node/Chrome yok")
class GezginUcAnca(unittest.TestCase):
    def test_yalniz_guvenli_butonlar_tiklanir(self):
        tiklar = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(s):
                if s.path.startswith("/tik"):
                    tiklar.append(urllib.parse.unquote(s.path.split("b=")[1]))
                    body, ct = b"{}", "application/json"
                elif s.path.startswith("/api"):
                    body, ct = b'{"status":"Finished","owner":"Secret Name","n":3,"rows":[{"id":"6abcb8c88594b2864be38ece"}]}', "application/json"
                elif s.path.startswith("/items/"):
                    body, ct = "<html><body><main><h1>Item</h1><p>Detay ekranı açıklaması yeterince uzun bir metindir.</p></main></body></html>".encode(), "text/html; charset=utf-8"
                elif s.path.startswith("/login"):
                    body, ct = b"<html><body>login</body></html>", "text/html"
                else:
                    body, ct = SITE.encode(), "text/html; charset=utf-8"
                s.send_response(200); s.send_header("content-type", ct); s.end_headers(); s.wfile.write(body)

            def log_message(*a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / "inv.txt").write_text("/home\n/items\n/items/:id\n/items/:id/edit\n/login\n")
            cfg = {"source": {"live_url": f"http://127.0.0.1:{port}"},
                   "analysis": {"output_dir": str(t / "docs")},
                   "discovery": {"goal": "g", "questions": ["q"], "allow": {"hosts": [f"127.0.0.1:{port}"]},
                                 "skip_routes": ["^/login"], "inventory": str(t / "inv.txt"), "log": str(t / "docs" / "log.jsonl")}}
            (t / "cfg.json").write_text(json.dumps(cfg))
            env = {**os.environ, "STUDIO_CONFIG": str(t / "cfg.json"), "STUDIO_KESIF_PROFIL": str(t / "prof")}
            r = subprocess.run(["node", "scripts/kesif_gezgin.mjs", "--sema", "--gorsel"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
            srv.shutdown()
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("New item", tiklar)
            for yasak in ("Save all", "Delete", "Add"):
                self.assertNotIn(yasak, tiklar, f"yasak/dialog-içi buton tıklandı: {yasak}")
            raw = json.loads((t / "docs" / "_ham" / "home.json").read_text())
            self.assertTrue(raw["modals"][0]["acildi"])
            self.assertTrue(raw["modals"][0]["kapandi"])
            # :param rotası satır tıklamasıyla örneklendi; /login atlandı (oturum yok sanılmadı)
            item = json.loads((t / "docs" / "_ham" / "items-id.json").read_text())
            self.assertEqual(item["durum"], "tamam", item)
            self.assertEqual(item["url"].rsplit("/", 1)[-1], "7")
            self.assertFalse((t / "docs" / "_ham" / "login.json").exists())
            edit = json.loads((t / "docs" / "_ham" / "items-id-edit.json").read_text())
            self.assertEqual((edit["durum"], edit.get("tahmin")), ("tamam", True), edit)   # kimlik türetme
            # API şeması: alan adı/tip var, DEĞER yok (enum yalnız status benzeri alanlarda)
            sema = (t / "docs" / "_api_semalari.json").read_text()
            self.assertIn("GET /api/items", sema)
            self.assertNotIn("Secret Name", sema)
            self.assertIn('"Finished"', sema)
            # referans ekran görüntüsü: geçerli PNG
            png = (t / "docs" / "_gorsel" / "home.png").read_bytes()
            self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
            self.assertGreater(len(png), 500)
            # Chrome profili serbest: süreç temizlendi
            ps = subprocess.run(["pgrep", "-f", str(t / "prof")], capture_output=True, text=True)
            self.assertEqual(ps.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
