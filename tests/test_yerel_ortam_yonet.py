"""Panelden yerel ortam yönetimi (issue #191)."""
import shutil
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import yerel_ortam_yonet as YO


def bos_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class YerelOrtam(unittest.TestCase):
    def setUp(self):
        self.k = Path(tempfile.mkdtemp()).resolve()
        (self.k / "workspace").mkdir()
        self.port = bos_port()

    def tearDown(self):
        YO.durdur(self.k, [self.port])
        shutil.rmtree(self.k, ignore_errors=True)

    def test_betik_yokken_baslatilmaz(self):
        d = YO.durum(self.k, [self.port])
        self.assertFalse(d["betik_var"])
        self.assertFalse(YO.baslat(self.k, [self.port])["ok"])

    def test_baslat_log_port_durdur(self):
        (self.k / "workspace" / "yerel_ortam.sh").write_text(
            f"#!/usr/bin/env bash\necho merhaba-ortam\nexec python3 -m http.server {self.port} --bind 127.0.0.1\n")
        r = YO.baslat(self.k, [self.port])
        self.assertTrue(r["ok"], r)
        self.assertFalse(YO.baslat(self.k, [self.port])["ok"])                      # çift başlatma reddedilir
        for _ in range(40):
            if YO.durum(self.k, [self.port])["durum"] == "calisiyor":
                break
            time.sleep(0.25)
        d = YO.durum(self.k, [self.port])
        self.assertEqual(d["durum"], "calisiyor", d)
        self.assertTrue(d["portlar"][0]["acik"])
        self.assertIn("merhaba-ortam", YO.log_oku(self.k))
        YO.durdur(self.k, [self.port])
        time.sleep(0.5)
        self.assertEqual(YO.durum(self.k, [self.port])["durum"], "durdu")
        self.assertIn("durduruldu", YO.log_oku(self.k))


    def test_portu_dinlemeyen_nuxt_dev_ve_kilit_temizlenir(self):
        import subprocess
        kilit = self.k / "workspace/src/web/.nuxt/nuxt.lock"
        kilit.parent.mkdir(parents=True)
        kilit.write_text("kilit")
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "node_modules/.bin/../nuxt/bin/nuxt.mjs", "dev"], cwd=self.k)
        try:
            time.sleep(0.5)
            YO.durdur(self.k, [self.port])
            for _ in range(20):
                if p.poll() is not None:
                    break
                time.sleep(0.25)
            self.assertIsNotNone(p.poll())                       # artık nuxt dev kapandı
            self.assertFalse(kilit.exists())                     # kilit dosyası silindi
        finally:
            if p.poll() is None:
                p.kill()


if __name__ == "__main__":
    unittest.main()


class PortSozlesmesi305(unittest.TestCase):
    def setUp(self):
        self.k = Path(tempfile.mkdtemp()).resolve()
        (self.k / "workspace").mkdir()
        import json
        (self.k / "workspace" / "studio.config.json").write_text(json.dumps(
            {"live": {"ports": [3200]}, "deney": {"portlar": {"nuxt": 3200, "backend": 8280, "mock": 4210, "panel": 8092}}}), encoding="utf-8")

    def tearDown(self):
        YO.durdur(self.k, [3200])
        shutil.rmtree(self.k, ignore_errors=True)

    def test_ortam_degiskenleri_configten_tum_adlarla(self):
        e = YO.ortam_degiskenleri(self.k)
        for ad in ("WEB_PORT", "NUXT_PORT", "PORT", "FRONTEND_PORT", "APP_PORT", "DEV_PORT"):
            self.assertEqual(e[ad], "3200")
        self.assertEqual((e["BACKEND_PORT"], e["API_PORT"], e["MOCK_PORT"]), ("8280", "8280", "4210"))

    def test_sabit_varsayilan_port_uyarisi(self):
        (self.k / "workspace" / "yerel_ortam.sh").write_text('WEB_PORT="${WEB_PORT:-3100}"\nMOCK_PORT="${MOCK_PORT:-4210}"\n', encoding="utf-8")
        u = YO.port_uyarilari(self.k)
        self.assertEqual(len(u), 1)
        self.assertIn("3100", u[0])
        (self.k / "workspace" / "yerel_ortam.sh").write_text('WEB_PORT="${WEB_PORT:-3200}"\n', encoding="utf-8")
        self.assertEqual(YO.port_uyarilari(self.k), [])

    def test_baslat_betige_sozlesmeyi_verir(self):
        cikti = self.k / "env.txt"
        (self.k / "workspace" / "yerel_ortam.sh").write_text(f'echo "$WEB_PORT $PORT $MOCK_PORT" > {cikti}\nsleep 1\n', encoding="utf-8")
        self.assertTrue(YO.baslat(self.k, [3200])["ok"])
        for _ in range(40):
            if cikti.exists() and cikti.read_text().strip():
                break
            time.sleep(0.1)
        self.assertEqual(cikti.read_text().split(), ["3200", "3200", "4210"])        # betik 3100 varsaysa bile config portu gelir

    def test_devops_rolu_port_sozlesmesini_bilir(self):
        import json
        org = json.loads((ROOT / "org_chart.json").read_text(encoding="utf-8"))
        d = next(a for a in org["hierarchy"] if a["id"] == "devops_engineer")
        self.assertIn("PORT SÖZLEŞMESİ", d["system_prompt"])


