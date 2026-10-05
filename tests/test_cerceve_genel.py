"""Çerçeve projeden bağımsız olmalı: başka projenin sabit kuralları yok (issue #201)."""
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import studio_engine as E

YASAK = ("stationRoutes", "operatorRoutes", "/stations", "/operators", "PostGIS", "Fastify", "Canlı Harita", "src/frontend", "npm run migrate")
# Tüm çerçeve kaynaklarında (testler, README ve sürüm geçmişi hariç) bulunmaması gereken projeye özel sözcükler (issue #203)
YASAK_TUM = ("elektriklioto", "cpo_", "epdk", "voltrun", "curl_input", "stationmap", "stationdetail", "postgis", "fastify",
             "istasyon", "stationroutes", "operatorroutes", "/api/v1/stations", "cpanel", "bbox", "gadm")
MUAF = ("tests/", "README.md", "AGENTS.md", "studio.version", "workspace/")


class CercevGenel(unittest.TestCase):
    def test_sabit_proje_sozcugu_yok(self):
        kaynak = (ROOT / "studio_engine.py").read_text(encoding="utf-8")
        for k in YASAK:
            self.assertNotIn(k, kaynak, f"studio_engine.py projeye özel sözcük taşıyor: {k}")

    def test_tum_cerceve_projeden_bagimsiz(self):
        import subprocess
        dosyalar = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split("\n")
        ihlal = []
        for f in dosyalar:
            if not f or f.startswith(MUAF) or not (ROOT / f).is_file():
                continue
            try:
                metin = (ROOT / f).read_text(encoding="utf-8").lower()
            except (UnicodeDecodeError, OSError):
                continue
            ihlal += [f"{f}: {k}" for k in YASAK_TUM if k in metin]
            if re.search(r"harita(?!sı)", metin):                          # 'yol haritası' (roadmap) serbest
                ihlal.append(f"{f}: harita")
        self.assertEqual(ihlal, [], "çerçevede projeye özel sözcükler var")

    def _calistir(self, cfg, app_ts, nuxt=None):
        d = Path(tempfile.mkdtemp())
        (d / "workspace/src/backend/src").mkdir(parents=True)
        (d / "workspace/src/backend/src/app.ts").write_text(app_ts)
        (d / "workspace/src/web").mkdir(parents=True)
        if nuxt is not None:
            (d / "workspace/src/web/nuxt.config.ts").write_text(nuxt)
        eski = (E.ROOT, E._studio_config)
        try:
            E.ROOT = d
            E._studio_config = lambda: (None, cfg)
            return E.self_healing_code_check("workspace/src/backend"), E.self_healing_code_check("workspace/src/web")
        finally:
            E.ROOT, E._studio_config = eski

    def test_varsayilan_denetim_yok(self):
        (b_ok, _), (w_ok, _) = self._calistir({}, "export const app = 1", "export default {}")
        self.assertTrue(b_ok)
        self.assertTrue(w_ok)

    def test_kritik_rotalar_configten(self):
        cfg = {"kalite": {"kritik_rotalar": [{"ad": "Kullanıcı Rotaları", "isaretler": ["userRoutes", "/users"]}]}}
        (b_ok, mesaj), _ = self._calistir(cfg, "export const app = 1")
        self.assertFalse(b_ok)
        self.assertIn("Kullanıcı Rotaları", mesaj)
        (b_ok, _), _ = self._calistir(cfg, "app.register(userRoutes)")
        self.assertTrue(b_ok)

    def test_nuxt_host_kontrolu_opt_in(self):
        cfg = {"kalite": {"nuxt_host_kontrolu": True}}
        _, (w_ok, mesaj) = self._calistir(cfg, "x", "export default {}")
        self.assertFalse(w_ok)
        self.assertIn("nuxt.config.ts", mesaj)
        _, (w_ok, _) = self._calistir(cfg, "x", "export default { devServer: { host: '127.0.0.1' } }")
        self.assertTrue(w_ok)


if __name__ == "__main__":
    unittest.main()
