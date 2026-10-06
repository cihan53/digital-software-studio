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
