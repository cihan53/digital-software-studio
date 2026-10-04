"""servis_kapat + studio_ctl çıkış menüsü testleri (issue #145)."""
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import servis_kapat as SK  # noqa: E402


def bos_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def sunucu(cwd: Path, port: int) -> subprocess.Popen:
    p = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"], cwd=cwd,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return p
        except OSError:
            time.sleep(0.1)
    p.kill()
    raise RuntimeError("test sunucusu başlamadı")


class ServisKapat(unittest.TestCase):
    def test_yalniz_proje_icindeki_surecler_kapanir(self):
        with tempfile.TemporaryDirectory() as proje, tempfile.TemporaryDirectory() as baska:
            (Path(proje) / "workspace").mkdir()
            pi, po = bos_port(), bos_port()
            icerde, disarda = sunucu(Path(proje) / "workspace", pi), sunucu(Path(baska), po)
            try:
                s = SK.servisler(Path(proje), portlar_panel=bos_port(), portlar_ortam=[pi, po])
                self.assertEqual(list(s["ortam"]), [pi])                    # dışarıdaki port listeye girmez
                log = SK.kapat(panel=False, ortam=True, kok=Path(proje), portlar_panel=bos_port(), portlar_ortam=[pi, po])
                self.assertTrue(any(f":{pi}" in x for x in log))
                time.sleep(0.5)
                self.assertIsNotNone(icerde.poll())                         # proje içindeki kapandı
                self.assertIsNone(disarda.poll())                           # dışarıdaki dokunulmadı
            finally:
                for p in (icerde, disarda):
                    if p.poll() is None:
                        p.kill()
                    p.wait()

    def test_panel_pid_dosyasi(self):
        with tempfile.TemporaryDirectory() as proje:
            (Path(proje) / "workspace").mkdir()
            port = bos_port()
            p = sunucu(Path(proje) / "workspace", port)
            try:
                (Path(proje) / "workspace" / ".web.pid").write_text(str(p.pid))
                s = SK.servisler(Path(proje), portlar_panel=bos_port(), portlar_ortam=[])
                self.assertEqual(s["panel"], [p.pid])
                SK.kapat(panel=True, ortam=False, kok=Path(proje), portlar_panel=bos_port(), portlar_ortam=[])
                time.sleep(0.5)
                self.assertIsNotNone(p.poll())
                self.assertFalse((Path(proje) / "workspace" / ".web.pid").exists())
            finally:
                if p.poll() is None:
                    p.kill()
                p.wait()


class CikisMenusu(unittest.TestCase):
    def test_env_ile_dogrudan_secim(self):
        import studio_ctl as CTL
        cagrilar = []
        eski = CTL.servis_kapat
        CTL.servis_kapat = lambda **kw: cagrilar.append(kw) or "ok"
        try:
            os.environ["STUDIO_CIKIS"] = "ekran"
            self.assertTrue(CTL.cikis_sec(0, None))
            self.assertEqual(cagrilar, [])                                  # servis kapanmaz
            os.environ["STUDIO_CIKIS"] = "vazgec"
            self.assertFalse(CTL.cikis_sec(0, None))
        finally:
            CTL.servis_kapat = eski
            os.environ.pop("STUDIO_CIKIS", None)


if __name__ == "__main__":
    unittest.main()
