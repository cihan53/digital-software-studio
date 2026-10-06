"""[RENDER] talepleri web_engineer'a gider; çözüm dosyası talep metninden çıktıya girer (issue #225)."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import studio_yetkilisi as Y


class RenderRol(unittest.TestCase):
    def test_render_talebi_web_engineer(self):
        t = {"baslik": "[RENDER] [TALEP-003] S7-T1 tarayıcıda çizim doğrulaması başarısız",
             "aciklama": "kaynak import fetch pipeline sync curl scraper etl Failed to resolve component: SignalsPanel", "sayfa_url": "/"}
        self.assertEqual(Y.tespit_et_kategori(t)["id"], "web_engineer")

    def test_render_olmayan_veri_talebi_etkilenmez(self):
        t = {"baslik": "scraper pipeline etl kaynak senkron hatası", "aciklama": "", "sayfa_url": "/"}
        self.assertEqual(Y.tespit_et_kategori(t)["id"], "data_engineer")

    def test_talepten_dosyalar_yapilandirmayi_ilk_alir(self):
        d = Path(tempfile.mkdtemp())
        for rel in ("workspace/src/web/nuxt.config.ts", "workspace/src/web/app/components/shell/A.vue", "workspace/src/web/app/components/shell/B.vue",
                    "workspace/src/web/app/components/shell/C.vue", "workspace/src/web/app/components/shell/D.vue"):
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text("x")
        eski = Y.ROOT
        try:
            Y.ROOT = d
            metin = ("Düzeltilecek dosya: workspace/src/web/nuxt.config.ts\n- A → workspace/src/web/app/components/shell/A.vue\n"
                     "- B → workspace/src/web/app/components/shell/B.vue\n- C → workspace/src/web/app/components/shell/C.vue\n- D → workspace/src/web/app/components/shell/D.vue")
            dosyalar = Y.talepten_dosyalar({"baslik": "[RENDER] x", "aciklama": metin})
            self.assertEqual(dosyalar[0], "workspace/src/web/nuxt.config.ts")
            self.assertEqual(len(dosyalar), 4)
        finally:
            Y.ROOT = eski


if __name__ == "__main__":
    unittest.main()
