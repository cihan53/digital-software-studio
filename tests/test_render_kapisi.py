"""Render kapısı (headless Chrome, CDP) ve önizleme profili (issue #217)."""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import yerel_ortam_yonet as YO

CHROME = os.environ.get("CHROME_PATH") or next((p for p in (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser") if Path(p).exists()), None)

IYI = "<html><body><header>h</header><nav>n</nav><main>Merhaba dünya içerik</main></body></html>"
KOTU = "<html><body><script>console.warn('[Vue warn]: Failed to resolve component: AppHeader')</script><main>içerik var</main></body></html>"
BOS = "<html><body></body></html>"


LOGIN = ("<html><body><header>h</header><nav>n</nav><main><form onsubmit='return false'>"
         "<input name='username'><input type='password' name='password'>"
         "<button type='submit' onclick=\"localStorage.oturum='1';location.href='/korumali'\">Giriş</button></form></main></body></html>")
KORUMALI = ("<html><body><script>if(!localStorage.oturum)location.href='/login'</script>"
            "<header>h</header><nav>n</nav><main>Gizli içerik burada</main></body></html>")


class Sunucu(BaseHTTPRequestHandler):
    def do_GET(self):
        govde = {"/iyi": IYI, "/kotu": KOTU, "/bos": BOS, "/login": LOGIN, "/korumali": KORUMALI}.get(self.path, IYI).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(govde)

    def log_message(self, *a):
        pass


@unittest.skipUnless(CHROME and shutil.which("node"), "Chrome/node yok")
class RenderKapisi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        cls.port = s.getsockname()[1]
        s.close()
        cls.srv = HTTPServer(("127.0.0.1", cls.port), Sunucu)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def _calistir(self, rotalar, dosyalar=None):
        kok = Path(tempfile.mkdtemp())
        for rel, icerik in (dosyalar or {}).items():
            (kok / rel).parent.mkdir(parents=True, exist_ok=True)
            (kok / rel).write_text(icerik)
        (kok / "workspace/docs").mkdir(parents=True)
        (kok / "workspace/studio.config.json").write_text(json.dumps({"live": {"ports": [self.port]}}))
        (kok / "workspace/uat_checklist.json").write_text(json.dumps({"rotalar": rotalar, "cati": {"haric": []}}))
        r = subprocess.run(["node", str(ROOT / "scripts/render_kapisi.mjs")], env={**os.environ, "STUDIO_KOK": str(kok)}, capture_output=True, text=True, timeout=120)
        return r, kok

    def test_temiz_sayfa_gecer(self):
        r, kok = self._calistir(["/iyi"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((kok / "workspace/docs/ekran_goruntuleri/iyi.png").exists())
        self.assertIn("✓", (kok / "workspace/docs/render_raporu.md").read_text())

    def test_vue_uyarisi_ve_eksik_cati_basarisiz(self):
        r, kok = self._calistir(["/iyi", "/kotu", "/bos"])
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        rapor = (kok / "workspace/docs/render_raporu.md").read_text()
        self.assertIn("Failed to resolve component: AppHeader", rapor)      # konsol uyarısı yakalandı
        self.assertIn("çatı eksik", rapor)                                  # header/nav yok
        self.assertIn("sayfa boş", rapor)

    def test_tani_cozulemeyen_bilesen_ve_kayit_adi(self):
        r, kok = self._calistir(["/kotu"], dosyalar={"workspace/src/web/app/components/shell/AppHeader.vue": "<template><div/></template>"})
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("TANI", r.stdout)
        self.assertIn("ShellAppHeader", r.stdout)                            # Nuxt kayıt adı
        self.assertIn("pathPrefix: false", r.stdout)                         # tek seferde çözüm önerisi
        self.assertIn("## Tanı", (kok / "workspace/docs/render_raporu.md").read_text())

    def test_otomatik_giris_mock_tohumundan(self):
        tohum = {"workspace/src/web/app/data/adapters/mock/auth.ts": "export const USERS = [{ username: 'ceo', password: 'Demo1234!' }]"}
        r, kok = self._calistir(["/korumali"], dosyalar=tohum)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Otomatik giriş yapıldı: ceo", r.stdout)
        self.assertNotIn("→ /login", r.stdout)                              # korumalı rota gerçekten doğrulandı
        r2, _ = self._calistir(["/korumali"])                                # tohum yoksa uyarı, rota login'e yönlenir
        self.assertIn("test hesabı bulunamadı", r2.stdout)

    def test_canli_sistem_yoksa_atlanir(self):
        kok = Path(tempfile.mkdtemp())
        (kok / "workspace").mkdir()
        (kok / "workspace/studio.config.json").write_text(json.dumps({"live": {"ports": [1]}}))
        r = subprocess.run(["node", str(ROOT / "scripts/render_kapisi.mjs")], env={**os.environ, "STUDIO_KOK": str(kok)}, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 3)


class OnizlemeProfili(unittest.TestCase):
    def setUp(self):
        self.k = Path(tempfile.mkdtemp()).resolve()
        (self.k / "workspace/src/web").mkdir(parents=True)
        (self.k / "workspace/studio.config.json").write_text(json.dumps({"live": {"ports": [3000]}}))

    def test_komut_package_json_betiklerinden(self):
        (self.k / "workspace/src/web/package.json").write_text(json.dumps({"scripts": {"build": "x", "preview": "y"}}))
        komut = YO.onizleme_komutu(self.k)
        self.assertIn("npm run build", komut)
        self.assertIn("-- --port 3001", komut)                              # dev portun bir fazlası
        (self.k / "workspace/src/web/pnpm-lock.yaml").write_text("")
        self.assertIn("pnpm run preview --port 3001", YO.onizleme_komutu(self.k))

    def test_betik_yoksa_baslatilmaz(self):
        (self.k / "workspace/src/web/package.json").write_text(json.dumps({"scripts": {"dev": "x"}}))
        self.assertIsNone(YO.onizleme_komutu(self.k))
        self.assertFalse(YO.baslat(self.k, profil="onizleme")["ok"])
        self.assertFalse(YO.durum(self.k, profil="onizleme")["betik_var"])

    def test_profiller_ayri_pid_ve_log(self):
        self.assertNotEqual(YO._pidf(self.k, "onizleme"), YO._pidf(self.k, "yerel_ortam"))
        self.assertNotEqual(YO._logf(self.k, "onizleme"), YO._logf(self.k, "yerel_ortam"))


if __name__ == "__main__":
    unittest.main()
