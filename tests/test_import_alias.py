"""Import kapısı Nuxt alias'larını da çözer (issue #241)."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import kalite_kapilari as K


def kur(dosyalar, nuxt=True):
    d = Path(tempfile.mkdtemp()).resolve()
    if nuxt:
        (d / "workspace/src/web").mkdir(parents=True)
        (d / "workspace/src/web/nuxt.config.ts").write_text("export default defineNuxtConfig({})")
    for rel, ic in dosyalar.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(ic)
    return d


class ImportAlias(unittest.TestCase):
    def _calistir(self, d, dosyalar):
        eski = K.ROOT
        try:
            K.ROOT = d
            return K.import_cozumleme_hatalari(dosyalar)
        finally:
            K.ROOT = eski

    def test_eksik_shared_alias_hata(self):
        d = kur({"workspace/src/web/app/stores/settings.ts": "import { x } from '#shared/schemas/settings'\n"})
        h = self._calistir(d, ["workspace/src/web/app/stores/settings.ts"])
        self.assertEqual(len(h), 1)
        self.assertIn("#shared/schemas/settings", h[0])
        self.assertIn("alias", h[0])

    def test_var_olan_aliaslar_gecer(self):
        d = kur({
            "workspace/src/web/app/pages/a.vue": "<script setup>\nimport { s } from '#shared/schemas/settings'\nimport B from '~/components/B.vue'\n"
                                                 "import { u } from '~~/server/utils/mock/state'\nconst l = () => import('@/utils/lazy')\n</script>",
            "workspace/src/web/shared/schemas/settings.ts": "export const s = 1",
            "workspace/src/web/app/components/B.vue": "<template/>",
            "workspace/src/web/server/utils/mock/state.ts": "export const u = 1",
            "workspace/src/web/app/utils/lazy/index.ts": "export default 1",
        })
        self.assertEqual(self._calistir(d, ["workspace/src/web/app/pages/a.vue"]), [])

    def test_nuxt_olmayan_projede_alias_denetlenmez(self):
        d = kur({"workspace/src/web/app/a.ts": "import x from '@/yok/dosya'\n"}, nuxt=False)     # nuxt.config yok: başka bundler alias'ı olabilir
        self.assertEqual(self._calistir(d, ["workspace/src/web/app/a.ts"]), [])

    def test_nuxt_ic_aliaslar_etkilenmez(self):
        d = kur({"workspace/src/web/app/a.ts": "import { useRoute } from '#imports'\nimport t from '#app'\n"})
        self.assertEqual(self._calistir(d, ["workspace/src/web/app/a.ts"]), [])


if __name__ == "__main__":
    unittest.main()
