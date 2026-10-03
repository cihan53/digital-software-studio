"""tespit_et_kategori / talepten_dosyalar birim testleri (issue #124)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import studio_yetkilisi as Y  # noqa: E402


class KategoriTespit(unittest.TestCase):
    def test_tasarim_talebi_backend_a_gitmez(self):
        t = {"baslik": "Tasarım önizlemesi ile uygulama stilleri uyuşmuyor "
                       "(Tailwind v4 @theme)",
             "aciklama": "workspace/src/backend yok; import rest api sync "
                         "pipeline kapı etl route",
             "sayfa_url": "/"}
        self.assertEqual(Y.tespit_et_kategori(t)["id"], "ui_designer")

    def test_kisa_kelime_alt_dizgi_eslesmez(self):
        # 'api' ⊄ 'kapı', 'rest' ⊄ 'restore', 'etl' ⊄ 'metlik'
        t = {"baslik": "Kapı simgesi restore metlik", "aciklama": "",
             "sayfa_url": "/"}
        self.assertEqual(Y.tespit_et_kategori(t)["id"], "web_engineer")

    def test_gercek_backend_talebi(self):
        t = {"baslik": "REST API endpoint 500 dönüyor", "aciklama": "",
             "sayfa_url": "/"}
        self.assertEqual(Y.tespit_et_kategori(t)["id"], "backend_engineer")

    def test_eslesme_yoksa_varsayilan(self):
        t = {"baslik": "Buton tıklanmıyor", "aciklama": "", "sayfa_url": "/"}
        self.assertEqual(Y.tespit_et_kategori(t)["id"], "web_engineer")

    def test_ui_designer_kod_rolune_eslenir(self):
        self.assertEqual(Y._KOD_ROLU["ui_designer"], "web_engineer")


class DosyaCozumu(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "workspace/src/web/assets/css").mkdir(parents=True)
        (self.root / "workspace/src/web/assets/css/main.css").write_text("")
        (self.root / "workspace/src/web/app.config.ts").write_text("")
        self._eski = Y.ROOT
        Y.ROOT = self.root

    def tearDown(self):
        Y.ROOT = self._eski
        self.tmp.cleanup()

    def test_frontend_yolu_projeye_cozulur(self):
        self.assertEqual(Y._proje_yolu_coz("workspace/src/frontend/assets/"),
                         "workspace/src/web/assets/")

    def test_talepteki_mevcut_dosyalar(self):
        t = {"baslik": "x", "aciklama": "assets/css/main.css ve app.config.ts "
             "ile workspace/src/web (dizin) ve yok.vue"}
        self.assertEqual(Y.talepten_dosyalar(t),
                         ["workspace/src/web/assets/css/main.css",
                          "workspace/src/web/app.config.ts"])


if __name__ == "__main__":
    unittest.main()
