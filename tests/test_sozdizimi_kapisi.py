"""Kaynak sözdizimi kapısı, model özel-token artefaktı, faz kapanış engeli (issue #315)."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import kalite_kapilari as K  # noqa: E402
import studio_engine as E  # noqa: E402
import studio_board as B  # noqa: E402
import karar_verici_triage as KVT  # noqa: E402
import faz_planla as FP  # noqa: E402


def esbuild_var():
    if K._esbuild_yolu(None):
        return True
    import glob
    for yol in glob.glob("/Users/*/PROJECT/*/workspace/src/*/node_modules/.bin/esbuild"):          # yerel geliştirici makinesi: bir projenin esbuild'ini kullan
        import os
        os.environ["STUDIO_ESBUILD"] = yol
        return True
    return False


def kur(dosyalar):
    d = Path(tempfile.mkdtemp()).resolve()
    (d / "workspace/src/web").mkdir(parents=True)
    (d / "workspace/src/web/nuxt.config.ts").write_text("export default defineNuxtConfig({})")
    for rel, ic in dosyalar.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(ic, encoding="utf-8")
    return d


def kos(d, dosyalar):
    eski = K.ROOT
    try:
        K.ROOT = d
        return K.sozdizimi_hatalari(dosyalar)
    finally:
        K.ROOT = eski


class OzelToken(unittest.TestCase):
    P = "workspace/src/web/components/app/"

    def test_ozel_token_artefakti_dosya_sonundan_temizlenir(self):
        m = "export interface A { x?: string }\n<|close|>argument<|sep|><|close|>call<|sep|><|close|>tools<|sep|>\n"
        self.assertEqual(E.temizle_arac_artefakti(m, "types.ts").strip(), "export interface A { x?: string }")
        self.assertEqual(E.temizle_arac_artefakti("const a = '<|x|>'\nconsole.log(a)\n", "a.ts"), "const a = '<|x|>'\nconsole.log(a)\n")   # satır ortası dokunulmaz (kapı yakalar)

    def test_kapi_ozel_tokeni_yakalar(self):
        d = kur({self.P + "types.ts": "export type A = 1\n<|close|>argument<|sep|>\n"})
        h = kos(d, [self.P + "types.ts"])
        self.assertEqual(len(h), 1)
        self.assertIn("özel token artefaktı", h[0])
        self.assertIn(":2:", h[0])


@unittest.skipUnless(esbuild_var(), "esbuild yok")
class Sozdizimi(unittest.TestCase):
    P = "workspace/src/web/pages/"

    def _esb(self):
        d = kur({})
        gercek = K._esbuild_yolu(None)
        if not gercek:
            self.skipTest("esbuild kurulu değil")
        (d / "workspace/src/web/node_modules/.bin").mkdir(parents=True)
        (d / "workspace/src/web/node_modules/.bin/esbuild").symlink_to(gercek)
        return d

    def test_yorumu_erken_kapatan_ve_gecerli_kod(self):
        d = self._esb()
        (d / self.P).mkdir(parents=True)
        (d / self.P / "bozuk.ts").write_text("/**\n * Nuxt `**/-*.*` ignore kuralı\n */\nexport const a = 1\n", encoding="utf-8")
        (d / self.P / "iyi.ts").write_text("/** normal yorum */\nexport const b = (x: number): number => x + 1\n", encoding="utf-8")
        h = kos(d, [self.P + "bozuk.ts", self.P + "iyi.ts"])
        self.assertEqual(len(h), 1)
        self.assertIn("bozuk.ts", h[0])
        self.assertIn("sözdizimi hatası", h[0])

    def test_vue_script_blogu_denetlenir_sablon_atlanir(self):
        d = self._esb()
        (d / self.P).mkdir(parents=True)
        (d / self.P / "A.vue").write_text("<script setup lang=\"ts\">\nconst a: number = \n</script>\n<template><div/></template>\n", encoding="utf-8")
        (d / self.P / "B.vue").write_text("<script setup lang=\"ts\">\nconst b: number = 1\n</script>\n<template><div>{{ b }}</div></template>\n", encoding="utf-8")
        h = kos(d, [self.P + "A.vue", self.P + "B.vue"])
        self.assertEqual(len(h), 1)
        self.assertIn("A.vue", h[0])


class FazKapanis(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.eski = (B.DB_PATH, KVT.FAZLAR_FILE)
        B.DB_PATH = self.tmp / "t.db"
        KVT.FAZLAR_FILE = self.tmp / "fazlar.json"
        (self.tmp / "workspace/docs/faz_planlari").mkdir(parents=True)
        KVT.save_fazlar({"fazlar": [{"id": "FAZ-1", "ad": "a", "durum": "AKTIF"}, {"id": "FAZ-2", "ad": "b", "durum": "PLANLANDI", "kilitli": True}]})
        (self.tmp / "workspace/docs/faz_planlari/FAZ-1.uygulandi").write_text("1", encoding="utf-8")

    def tearDown(self):
        B.DB_PATH, KVT.FAZLAR_FILE = self.eski
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rapor(self, metin):
        import os
        import time
        p = self.tmp / "workspace/docs/uat_kabul_raporu.md"
        p.write_text(metin, encoding="utf-8")
        t = time.time() + 5
        os.utime(p, (t, t))                                          # faz planından sonra üretilmiş

    def board(self):
        return B.normalize({"sprints": [{"id": "S1", "name": "s", "order": 0, "tasks": [
            {"id": "S1-T1", "title": "x", "description": "", "role": "web_engineer", "phase": "develop", "outputs": ["workspace/x"], "depends_on": [],
             "status": B.DONE, "note": "", "talep_id": None, "order": 0, "priority": 0}]}]})

    def test_uat_reddi_fazi_durdurur(self):
        self.rapor("# UAT\n\n## Yönetim Özeti — KARAR: FAZ-1 KAPANIŞA HAZIR DEĞİL (REDDEDİLDİ)\n")
        self.assertIsNotNone(FP.kapanis_engeli("FAZ-1", self.tmp))
        self.assertIsNone(FP.otomatik_ilerlet(self.board(), self.tmp))

    def test_kabul_ve_eski_rapor_engellemez(self):
        self.rapor("# UAT\n\nKARAR: KABUL EDİLDİ\n")
        self.assertIsNone(FP.kapanis_engeli("FAZ-1", self.tmp))
        self.assertEqual(FP.otomatik_ilerlet(self.board(), self.tmp), "FAZ-2")

    def test_faz_oncesi_red_raporu_sayilmaz(self):
        import os
        p = self.tmp / "workspace/docs/uat_kabul_raporu.md"
        p.write_text("KARAR: REDDEDİLDİ\n", encoding="utf-8")
        os.utime(p, (1000, 1000))                                     # plan uygulanmadan önceki rapor
        self.assertIsNone(FP.kapanis_engeli("FAZ-1", self.tmp))

    def test_kapanis_talebi_cozulunce_engel_kalkar(self):
        from unittest import mock
        import musteri_talepleri as MT
        self.rapor("KARAR: REDDEDİLDİ\n")
        FP.kapanis_talep_yolu("FAZ-1", self.tmp).write_text(json.dumps({"talep": "TALEP-9"}), encoding="utf-8")
        with mock.patch.object(MT, "getir", return_value={"durum": "GELISTIRILIYOR"}):
            self.assertEqual(FP.kapanis_engeli("FAZ-1", self.tmp)["talep"], "TALEP-9")
        with mock.patch.object(MT, "getir", return_value={"durum": "COZULDU"}):
            self.assertIsNone(FP.kapanis_engeli("FAZ-1", self.tmp))

    def test_panel_nedeni(self):
        import gozlem as GO
        ctrl = {"faz_kapanis_engeli": json.dumps({"faz": "FAZ-2", "neden": "UAT reddetti", "talep": "TALEP-9"})}
        n = GO.bekleme_nedeni(None, ctrl, True, None, {}, False)
        self.assertEqual(n["kod"], "faz_kapanis_engeli")
        self.assertIn("TALEP-9", n["mesaj"])


if __name__ == "__main__":
    unittest.main()
