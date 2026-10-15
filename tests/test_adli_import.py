"""Import kapısı: hedef modülde olmayan adlandırılmış/varsayılan import (issue #309)."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import kalite_kapilari as K


def kur(dosyalar):
    d = Path(tempfile.mkdtemp()).resolve()
    (d / "workspace/src/web").mkdir(parents=True)
    (d / "workspace/src/web/nuxt.config.ts").write_text("export default defineNuxtConfig({})")
    for rel, ic in dosyalar.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(ic)
    return d


def kos(d, dosyalar):
    eski = K.ROOT
    try:
        K.ROOT = d
        return K.import_cozumleme_hatalari(dosyalar)
    finally:
        K.ROOT = eski


DATA = ("export let developersState: X[] = []\n"
        "export function getDeveloperList(search?: string): X[] { return developersState }\n"
        "export const getById = (id: string) => id\nexport type DeveloperRow = {}\nconst gizli = 1\nexport { gizli as acik }\n")


class AdliImport(unittest.TestCase):
    P = "workspace/src/web/server/api/developers/"

    def test_gemini_vakasi_olmayan_ad_yakalanir_ve_oneri_verilir(self):
        d = kur({self.P + "data.ts": DATA, self.P + "index.get.ts": "import { defineEventHandler } from 'h3'\nimport { getDevelopers } from './data'\n"})
        h = kos(d, [self.P + "index.get.ts"])
        self.assertEqual(len(h), 1)
        self.assertIn("'getDevelopers'", h[0])
        self.assertIn("getDeveloperList", h[0])                                  # en yakın ad önerilir: ajan doğru adı bulur

    def test_var_olan_adlar_alias_ve_tip_importu_gecer(self):
        d = kur({self.P + "data.ts": DATA, self.P + "a.ts": "import { getDeveloperList, getById as g, acik } from './data'\nimport type { Yok } from './data'\nimport { type DeveloperRow } from './data'\n"})
        self.assertEqual(kos(d, [self.P + "a.ts"]), [])

    def test_cok_satirli_import(self):
        d = kur({self.P + "data.ts": DATA, self.P + "a.ts": "import {\n  getDeveloperList,\n  yokOlan,\n} from './data'\n"})
        h = kos(d, [self.P + "a.ts"])
        self.assertEqual(len(h), 1)
        self.assertIn("'yokOlan'", h[0])

    def test_varsayilan_import(self):
        d = kur({self.P + "data.ts": DATA, self.P + "d.ts": "export default 1\n", self.P + "a.ts": "import X from './data'\nimport Y from './d'\n"})
        h = kos(d, [self.P + "a.ts"])
        self.assertEqual(len(h), 1)
        self.assertIn("'X'", h[0])

    def test_belirsiz_hedefler_denetlenmez(self):
        d = kur({self.P + "wild.ts": "export * from './baska'\n", self.P + "cjs.js": "module.exports = { a: 1 }\n", self.P + "C.vue": "<script setup></script>\n",
                 self.P + "a.ts": "import { x } from './wild'\nimport { a } from './cjs'\nimport { c } from './C.vue'\n"})
        self.assertEqual(kos(d, [self.P + "a.ts"]), [])

    def test_nuxt_alias_hedefi(self):
        d = kur({"workspace/src/web/shared/utils.ts": "export const a = 1\n", self.P + "a.ts": "import { a, b } from '#shared/utils'\n"})
        h = kos(d, [self.P + "a.ts"])
        self.assertEqual(len(h), 1)
        self.assertIn("'b'", h[0])


if __name__ == "__main__":
    unittest.main()


class ProjeTaramasi(unittest.TestCase):
    def test_tarama_bulguda_tek_build_talebi_acar_tekrar_acmaz(self):
        from unittest import mock
        import studio_engine as E
        import musteri_talepleri as MT
        d = kur({"workspace/src/web/server/data.ts": "export function getList(){}\n", "workspace/src/web/server/a.get.ts": "import { getLists } from './data'\n"})
        acilan = []
        eski = (E.ROOT, K.ROOT)
        try:
            E.ROOT = d
            K.ROOT = d
            with mock.patch.object(E, "_auto_talep_uat", side_effect=lambda t, c, **kw: acilan.append((t["id"], c, kw))), \
                    mock.patch.object(MT, "load_data", return_value={"talepler": []}):
                E._proje_import_taramasi("S9")
            self.assertEqual(len(acilan), 1)
            self.assertEqual(acilan[0][0], "TARAMA-S9")
            self.assertIn("getLists", acilan[0][1])
            self.assertEqual(acilan[0][2]["kaynak"], "BUILD")
            acilan.clear()
            with mock.patch.object(E, "_auto_talep_uat", side_effect=lambda t, c, **kw: acilan.append(1)), \
                    mock.patch.object(MT, "load_data", return_value={"talepler": [{"baslik": "[BUILD] TARAMA-S9 x", "durum": "GELISTIRILIYOR"}]}):
                E._proje_import_taramasi("S10")
            self.assertEqual(acilan, [])                                       # açık tarama talebi varken yenisi açılmaz
        finally:
            E.ROOT, K.ROOT = eski
